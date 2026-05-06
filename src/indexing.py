from __future__ import annotations

from pathlib import Path

from .chunking import detect_clause, split_text_into_chunks
from .pdf_extract import extract_pdf_pages, get_page_count
from .utils import (
    CHUNKS_PATH,
    PDF_DIR,
    STANDARDS_INDEX_PATH,
    detect_body,
    detect_standard_number,
    ensure_data_dirs,
    safe_slug,
    write_json,
    write_jsonl,
)


def list_pdfs(pdf_dir: Path = PDF_DIR) -> list[Path]:
    """List PDFs in the storage folder."""
    if not pdf_dir.exists():
        return []
    return sorted(pdf_dir.rglob("*.pdf"))


def build_index(pdf_dir: Path = PDF_DIR, use_ocr: bool = False, ocr_language: str = "eng+ind") -> dict:
    """Extract PDFs and rebuild JSONL/JSON indexes from scratch."""
    ensure_data_dirs()
    pdfs = list_pdfs(pdf_dir)
    chunks: list[dict] = []
    standards: list[dict] = []
    warnings: list[str] = []

    if not pdfs:
        write_jsonl(CHUNKS_PATH, [])
        write_json(STANDARDS_INDEX_PATH, [])
        return {"standards": 0, "chunks": 0, "warnings": ["No PDF files found."]}

    for pdf_path in pdfs:
        body = detect_body(pdf_path.name)
        standard_number = detect_standard_number(pdf_path.name, body)
        source_file = str(pdf_path.relative_to(pdf_dir)).replace("\\", "/")
        pages, pdf_warnings = extract_pdf_pages(pdf_path, use_ocr=use_ocr, ocr_language=ocr_language)
        warnings.extend(pdf_warnings)
        chunk_count = 0
        current_clause = ""

        for page_record in pages:
            page_text = page_record["text"]
            if not page_text:
                continue
            page_clause = detect_clause(page_text, current_clause)
            current_clause = page_clause or current_clause
            for chunk_index, chunk_text in enumerate(split_text_into_chunks(page_text), start=1):
                clause = detect_clause(chunk_text, current_clause)
                current_clause = clause or current_clause
                chunk_count += 1
                page = page_record["page"]
                chunk_id = (
                    f"{safe_slug(body)}_{safe_slug(standard_number)}"
                    f"_p{page}_c{chunk_index:03d}"
                )
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "source_file": source_file,
                        "body": body,
                        "standard_number": standard_number,
                        "title": "",
                        "year": "",
                        "clause": clause,
                        "page": page,
                        "text": chunk_text,
                        "topic_tags": [],
                    }
                )

        if chunk_count == 0:
            warnings.append(f"{pdf_path.name}: no chunks created.")
        standards.append(
            {
                "source_file": source_file,
                "body": body,
                "standard_number": standard_number,
                "title": "",
                "year": "",
                "page_count": get_page_count(pdf_path),
                "chunk_count": chunk_count,
            }
        )

    write_jsonl(CHUNKS_PATH, chunks)
    write_json(STANDARDS_INDEX_PATH, standards)
    return {"standards": len(standards), "chunks": len(chunks), "warnings": warnings}
