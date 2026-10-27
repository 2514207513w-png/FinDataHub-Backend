import pytest
from app.utils import split_text, validate_pdf


def test_chunks_have_overlap_and_cover_text():
    text = "abcdefghij"
    assert split_text(text, chunk_size=6, overlap=2) == ["abcdef", "efghij"]


def test_empty_document():
    assert split_text("  \n\t  ") == []


def test_invalid_chunk_config():
    with pytest.raises(ValueError):
        split_text("abc", chunk_size=2, overlap=2)


def test_rejects_invalid_pdf():
    with pytest.raises(ValueError):
        validate_pdf(b"not-a-pdf", 1024)


def test_accepts_small_pdf_header():
    validate_pdf(b"%PDF-1.7\nanything", 1024)
