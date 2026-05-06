from __future__ import annotations

from io import BytesIO

import fitz
from PIL import Image

from .utils import clean_text


class OcrUnavailableError(RuntimeError):
    """Raised when Tesseract OCR is not installed or not callable."""


def ocr_pdf_page(page: fitz.Page, language: str = "eng+ind", dpi: int = 220) -> str:
    """Render a PDF page and extract text with Tesseract OCR."""
    try:
        import pytesseract
    except ModuleNotFoundError as exc:
        raise OcrUnavailableError("pytesseract is not installed.") from exc

    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png")))

    try:
        return clean_text(pytesseract.image_to_string(image, lang=language) or "")
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError("Tesseract executable is not installed.") from exc
    except pytesseract.TesseractError as exc:
        raise OcrUnavailableError(f"Tesseract OCR failed: {exc}") from exc

