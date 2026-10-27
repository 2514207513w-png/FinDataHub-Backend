from celery import Celery
from sqlalchemy import select, delete
from .config import settings
from .db import SessionLocal
from .models import Document, DocumentChunk, IngestionJob
from .utils import extract_pdf_text, split_text

celery_app = Celery("findatahub", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="ingest_document", bind=True, max_retries=2)
def ingest_document(self, job_id: str):
    # Claim the job atomically. Re-delivery after completion is a no-op.
    with SessionLocal.begin() as db:
        job = db.execute(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()).scalar_one()
        if job.status == "completed":
            return {"status": "already_completed"}
        if job.status == "running":
            return {"status": "already_running"}
        job.status = "running"
        document_id = job.document_id
        doc = db.get(Document, document_id)
        path = doc.storage_path

    try:
        text = extract_pdf_text(path)
        chunks = split_text(text)
        if not chunks:
            raise ValueError("PDF contains no extractable text; OCR is not implemented")
        with SessionLocal.begin() as db:
            job = db.execute(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()).scalar_one()
            if job.status == "completed":
                return {"status": "already_completed"}
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            db.add_all([DocumentChunk(document_id=document_id, position=i, text=c) for i,c in enumerate(chunks)])
            db.get(Document, document_id).status = "ready"
            job.status = "completed"
            job.error = None
        return {"status": "completed", "chunks": len(chunks)}
    except Exception as exc:
        with SessionLocal.begin() as db:
            job = db.get(IngestionJob, job_id)
            job.retries += 1
            job.status = "retrying" if self.request.retries < self.max_retries else "failed"
            job.error = type(exc).__name__[:100]
            if job.status == "failed":
                db.get(Document, job.document_id).status = "failed"
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=3 * (2 ** self.request.retries))
        raise
