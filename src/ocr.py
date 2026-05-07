from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import fitz

from .utils import clean_text


class OcrUnavailableError(RuntimeError):
    """Raised when the configured OCR backend is not installed or not callable."""


def _render_page_to_png(page: fitz.Page, dpi: int) -> Path:
    """Render a PDF page to a temporary PNG for OCR engines."""
    zoom = dpi / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    temp = NamedTemporaryFile(delete=False, suffix=".png")
    temp_path = Path(temp.name)
    try:
        temp.write(pixmap.tobytes("png"))
        return temp_path
    finally:
        temp.close()


@lru_cache(maxsize=1)
def _paddle_ocr():
    """Create a cached PaddleOCR instance with lightweight document preprocessing."""
    try:
        from paddleocr import PaddleOCR
    except ModuleNotFoundError as exc:
        raise OcrUnavailableError("PaddleOCR is not installed.") from exc

    try:
        return PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except TypeError:
        try:
            return PaddleOCR(use_angle_cls=False, lang="en")
        except TypeError as exc:
            raise OcrUnavailableError(f"PaddleOCR initialization failed: {exc}") from exc
    except Exception as exc:
        raise OcrUnavailableError(f"PaddleOCR initialization failed: {exc}") from exc


def _extract_texts_from_paddle_result(result: Any) -> list[str]:
    """Extract recognized text from PaddleOCR v2/v3 result shapes."""
    texts: list[str] = []

    def visit(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for key in ("rec_texts", "texts"):
                items = value.get(key)
                if isinstance(items, list):
                    texts.extend(str(item) for item in items if str(item).strip())
            for key in ("text", "transcription"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    texts.append(item)
            return
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1]:
                candidate = value[1][0]
                if isinstance(candidate, str) and candidate.strip():
                    texts.append(candidate)
                    return
            for item in value:
                visit(item)
            return
        json_value = getattr(value, "json", None)
        if callable(json_value):
            visit(json_value())
            return
        if isinstance(json_value, dict):
            visit(json_value)

    visit(result)
    return texts


def _paddle_ocr_image(image_path: Path) -> str:
    ocr = _paddle_ocr()
    try:
        if hasattr(ocr, "predict"):
            result = ocr.predict(str(image_path))
        else:
            result = ocr.ocr(str(image_path), cls=False)
    except Exception as exc:
        raise OcrUnavailableError(f"PaddleOCR failed: {exc}") from exc
    return clean_text("\n".join(_extract_texts_from_paddle_result(result)))


def _tesseract_ocr_image(image_path: Path, language: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise OcrUnavailableError("Tesseract dependencies are not installed.") from exc

    try:
        return clean_text(pytesseract.image_to_string(Image.open(image_path), lang=language) or "")
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError("Tesseract executable is not installed.") from exc
    except pytesseract.TesseractError as exc:
        raise OcrUnavailableError(f"Tesseract OCR failed: {exc}") from exc


def ocr_pdf_page(page: fitz.Page, language: str = "eng+ind", dpi: int = 220, engine: str = "paddleocr") -> str:
    """Render a PDF page and extract text with PaddleOCR by default."""
    image_path = _render_page_to_png(page, dpi)
    try:
        if engine == "tesseract":
            return _tesseract_ocr_image(image_path, language)
        try:
            return _paddle_ocr_image(image_path)
        except OcrUnavailableError:
            return _tesseract_ocr_image(image_path, language)
    finally:
        try:
            image_path.unlink(missing_ok=True)
        except Exception:
            pass
