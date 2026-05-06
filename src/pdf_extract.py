from __future__ import annotations

from pathlib import Path

import fitz

from .utils import clean_text


def extract_pdf_pages(pdf_path: Path) -> tuple[list[dict], list[str]]:
    """Extract text page by page with PyMuPDF.

    Returns page records and warnings. OCR is intentionally not implemented in v1.
    """
    warnings: list[str] = []
    pages: list[dict] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return [], [f"{pdf_path.name}: cannot open PDF ({exc})"]

    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            text = clean_text(page.get_text("text") or "")
            pages.append({"page": page_index + 1, "text": text})
    except Exception as exc:
        warnings.append(f"{pdf_path.name}: extraction failed ({exc})")
    finally:
        doc.close()

    total_chars = sum(len(p["text"]) for p in pages)
    if not pages:
        warnings.append(f"{pdf_path.name}: empty or malformed PDF.")
    elif total_chars == 0:
        warnings.append(f"{pdf_path.name}: no extractable text found. OCR is not implemented yet.")
    elif total_chars / max(len(pages), 1) < 80:
        warnings.append(f"{pdf_path.name}: very little extractable text found; this may be scanned. OCR is not implemented yet.")
    return pages, warnings


def get_page_count(pdf_path: Path) -> int:
    """Return PDF page count, or zero when unreadable."""
    try:
        doc = fitz.open(pdf_path)
        count = doc.page_count
        doc.close()
        return count
    except Exception:
        return 0

