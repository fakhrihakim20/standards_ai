from __future__ import annotations

from pathlib import Path

import fitz

from .ocr import OcrUnavailableError, ocr_pdf_page
from .utils import clean_text


def extract_pdf_pages(
    pdf_path: Path,
    use_ocr: bool = False,
    ocr_language: str = "eng+ind",
    ocr_engine: str = "paddleocr",
    ocr_min_chars: int = 80,
) -> tuple[list[dict], list[str]]:
    """Extract text page by page with PyMuPDF.

    When enabled, OCR is used only for pages with little or no extractable text.
    Returns page records and warnings.
    """
    warnings: list[str] = []
    pages: list[dict] = []
    ocr_used = False
    ocr_failed = False
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return [], [f"{pdf_path.name}: cannot open PDF ({exc})"]

    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            text = clean_text(page.get_text("text") or "")
            extraction_method = "text"
            if use_ocr and len(text) < ocr_min_chars:
                try:
                    ocr_text = ocr_pdf_page(page, language=ocr_language, engine=ocr_engine)
                    if len(ocr_text) > len(text):
                        text = ocr_text
                        extraction_method = "ocr"
                        ocr_used = True
                except OcrUnavailableError as exc:
                    if not ocr_failed:
                        warnings.append(f"{pdf_path.name}: OCR unavailable ({exc})")
                        ocr_failed = True
            pages.append({"page": page_index + 1, "text": text, "method": extraction_method})
    except Exception as exc:
        warnings.append(f"{pdf_path.name}: extraction failed ({exc})")
    finally:
        doc.close()

    total_chars = sum(len(p["text"]) for p in pages)
    if not pages:
        warnings.append(f"{pdf_path.name}: empty or malformed PDF.")
    elif total_chars == 0:
        if use_ocr:
            warnings.append(f"{pdf_path.name}: no extractable text found after OCR.")
        else:
            warnings.append(f"{pdf_path.name}: no extractable text found. Enable OCR for scanned PDFs.")
    elif total_chars / max(len(pages), 1) < 80:
        if use_ocr and ocr_used:
            warnings.append(f"{pdf_path.name}: OCR was used for scanned or low-text pages.")
        else:
            warnings.append(f"{pdf_path.name}: very little extractable text found; this may be scanned. Enable OCR for better extraction.")
    elif ocr_used:
        warnings.append(f"{pdf_path.name}: OCR was used for scanned or low-text pages.")
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
