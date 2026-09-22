"""Lightweight text extraction used ONLY for classification (a quick,
cheap read of the document to decide its type) — not the full schema
extraction, which happens later in the pipeline once a template is
chosen. Keeping this separate and cheap avoids running a full AI
extraction call before we even know which schema to extract against.
"""
import io

from pypdf import PdfReader


def extract_preview_text(file_bytes: bytes, max_chars: int = 2000) -> str:
    """Pull a rough text preview from a PDF (or fall back to treating the
    bytes as plain text for non-PDF uploads). Good enough for
    classification — does not need to be perfect OCR."""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
        if text.strip():
            return text[:max_chars]
    except Exception:
        pass

    # Fallback: not a parseable PDF — try decoding as plain text
    try:
        return file_bytes.decode("utf-8", errors="ignore")[:max_chars]
    except Exception:
        return ""