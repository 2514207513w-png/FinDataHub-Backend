import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
import redis
from fastapi import FastAPI, Depends, File, HTTPException, UploadFile, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, get_db, SessionLocal
from .models import User, Product, Document, IngestionJob, DocumentChunk
from .security import pwd, create_token, current_user, require_writer
from .utils import validate_pdf
from .worker import ingest_document

cache = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=0.2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (len(settings.jwt_secret) < 32 or settings.jwt_secret.startswith("CHANGE_ME")) or not settings.bootstrap_admin_password or settings.bootstrap_admin_password.startswith("CHANGE_ME"):
        raise RuntimeError("Configure a strong JWT_SECRET and BOOTSTRAP_ADMIN_PASSWORD in .env")
    # For a learning MVP. For deployment, use Alembic migrations instead.
    Base.metadata.create_all(engine)
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    with SessionLocal.begin() as db:
        existing = db.scalar(select(User).where(User.email == settings.bootstrap_admin_email))
        if existing is None:
            db.add(User(email=settings.bootstrap_admin_email, hashed_password=pwd.hash(settings.bootstrap_admin_password), role="admin"))
    yield


app = FastAPI(title="FinDataHub starter", lifespan=lifespan)


class LoginInput(BaseModel):
    email: str
    password: str


class NewUserInput(BaseModel):
    email: str
    password: str = Field(min_length=12)
    role: str = "viewer"


class ProductInput(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=200)
    risk_level: str = "unknown"
    source_url: str | None = None


class ProductPatch(BaseModel):
    name: str | None = None
    risk_level: str | None = None
    source_url: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/auth/token")
def token(data: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    if not user or not pwd.verify(data.password, user.hashed_password):
        raise HTTPException(401, "invalid credentials")
    return {"access_token": create_token(user), "token_type": "bearer", "role": user.role}


@app.post("/api/v1/users", status_code=201)
def create_user(data: NewUserInput, db: Session = Depends(get_db), admin=Depends(current_user)):
    if admin.role != "admin":
        raise HTTPException(403, "admin required")
    if data.role not in ("viewer", "analyst"):
        raise HTTPException(400, "invalid role")
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(409, "user exists")
    user = User(email=data.email, hashed_password=pwd.hash(data.password), role=data.role)
    db.add(user)
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/api/v1/products", status_code=201)
def create_product(item: ProductInput, db: Session = Depends(get_db), _=Depends(require_writer)):
    if db.scalar(select(Product.id).where(Product.code == item.code)):
        raise HTTPException(409, "product code exists")
    product = Product(**item.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id, "code": product.code, "name": product.name, "risk_level": product.risk_level}


@app.get("/api/v1/products")
def list_products(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), _=Depends(current_user)):
    rows = db.scalars(select(Product).order_by(Product.code).limit(limit).offset(offset)).all()
    total = db.scalar(select(func.count()).select_from(Product))
    return {"total": total, "items": [{"id": p.id, "code": p.code, "name": p.name, "risk_level": p.risk_level} for p in rows]}


@app.patch("/api/v1/products/{code}")
def patch_product(code: str, data: ProductPatch, db: Session = Depends(get_db), _=Depends(require_writer)):
    product = db.scalar(select(Product).where(Product.code == code))
    if not product:
        raise HTTPException(404, "product not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    try:
        cache.delete(f"product:{code}")
    except redis.RedisError:
        pass
    return {"id": product.id, "code": product.code, "name": product.name, "risk_level": product.risk_level}


@app.get("/api/v1/products/{code}")
def get_product(code: str, db: Session = Depends(get_db), _=Depends(current_user)):
    key = f"product:{code}"
    try:
        cached = cache.get(key)
        if cached:
            import json
            return json.loads(cached)
    except redis.RedisError:
        pass  # Cache failure does not break source-of-truth reads.
    product = db.scalar(select(Product).where(Product.code == code))
    if not product:
        raise HTTPException(404, "product not found")
    result = {"id": product.id, "code": product.code, "name": product.name, "risk_level": product.risk_level, "source_url": product.source_url}
    try:
        import json
        cache.setex(key, settings.cache_ttl_seconds, json.dumps(result))
    except redis.RedisError:
        pass
    return result


@app.post("/api/v1/products/{code}/documents", status_code=202)
def upload_document(code: str, file: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(require_writer)):
    product = db.scalar(select(Product).where(Product.code == code))
    if not product:
        raise HTTPException(404, "product not found")
    blob = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    try:
        validate_pdf(blob, settings.max_upload_mb * 1024 * 1024)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    digest = hashlib.sha256(blob).hexdigest()
    existing = db.scalar(select(Document).where(Document.product_id == product.id, Document.sha256 == digest))
    if existing:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == existing.id))
        return {"document_id": existing.id, "job_id": job.id, "status": job.status, "deduplicated": True}
    path = Path(settings.upload_dir) / f"{uuid4()}.pdf"
    path.write_bytes(blob)
    document = Document(product_id=product.id, sha256=digest, filename=Path(file.filename or "upload.pdf").name[:255], storage_path=str(path))
    db.add(document)
    db.flush()
    job = IngestionJob(document_id=document.id)
    db.add(job)
    db.commit()
    try:
        ingest_document.delay(job.id)
    except Exception:
        job.status = "dispatch_failed"
        db.commit()
    return {"document_id": document.id, "job_id": job.id, "status": job.status, "deduplicated": False}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    job = db.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"id": job.id, "document_id": job.document_id, "status": job.status, "retries": job.retries, "error": job.error}


@app.post("/api/v1/jobs/{job_id}/retry", status_code=202)
def retry_dispatch(job_id: str, db: Session = Depends(get_db), _=Depends(require_writer)):
    job = db.get(IngestionJob, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if job.status not in ("dispatch_failed", "failed"):
        raise HTTPException(409, "job is not retryable")
    job.status = "queued"
    db.commit()
    try:
        ingest_document.delay(job.id)
    except Exception:
        job.status = "dispatch_failed"
        db.commit()
    return {"job_id": job.id, "status": job.status}


@app.get("/api/v1/documents/{document_id}/chunks")
def get_chunks(document_id: str, db: Session = Depends(get_db), _=Depends(current_user)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "document not found")
    if doc.status != "ready":
        raise HTTPException(409, f"document is {doc.status}")
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.position)).all()
    return {"document_id": document_id, "chunks": [{"position": c.position, "text": c.text} for c in chunks]}
