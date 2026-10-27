from pypdf import PdfReader


def validate_pdf(blob: bytes, max_bytes: int) -> None:
    if not blob or len(blob) > max_bytes or not blob.startswith(b"%PDF-"):
        raise ValueError("invalid or oversized PDF")


def split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("invalid chunk size/overlap")
    clean = " ".join(text.split())
    if not clean:
        return []
    parts = []
    stride = chunk_size - overlap
    for start in range(0, len(clean), stride):
        part = clean[start : start + chunk_size]
        if part:
            parts.append(part)
        if start + chunk_size >= len(clean):
            break
    return parts


def extract_pdf_text(path: str) -> str:
    reader = PdfReader(path)
    return "\n".join((p.extract_text() or "") for p in reader.pages)
