from __future__ import annotations

from pathlib import Path

from .chunking import detect_clause, split_text_into_chunks
from .pdf_extract import extract_pdf_pages, get_page_count
from .utils import (
    CHUNKS_PATH,
    DRIVE_MANIFEST_PATH,
    PDF_DIR,
    STANDARDS_INDEX_PATH,
    detect_body,
    detect_standard_number,
    ensure_data_dirs,
    safe_slug,
    write_json,
    write_jsonl,
    read_json,
    read_jsonl,
)


def list_pdfs(pdf_dir: Path = PDF_DIR) -> list[Path]:
    """List PDFs in the storage folder."""
    if not pdf_dir.exists():
        return []
    return sorted(pdf_dir.rglob("*.pdf"))


def _pdf_fingerprint(pdf_path: Path, use_ocr: bool, ocr_language: str) -> dict:
    """Return metadata used to decide whether a PDF needs re-indexing."""
    stat = pdf_path.stat()
    return {
        "file_size": stat.st_size,
        "file_mtime_ns": stat.st_mtime_ns,
        "index_use_ocr": bool(use_ocr),
        "index_ocr_language": ocr_language,
    }


def _is_index_current(standard: dict, fingerprint: dict) -> bool:
    """Return whether an existing standard entry matches current file metadata."""
    return all(standard.get(key) == value for key, value in fingerprint.items())


def build_index(
    pdf_dir: Path = PDF_DIR,
    use_ocr: bool = False,
    ocr_language: str = "eng+ind",
    force_rebuild: bool = False,
    progress_callback=None,
) -> dict:
    """Extract PDFs and build JSONL/JSON indexes, reusing unchanged files."""
    ensure_data_dirs()
    pdfs = list_pdfs(pdf_dir)
    drive_manifest = {
        item.get("file"): item
        for item in read_json(DRIVE_MANIFEST_PATH, [])
        if item.get("file")
    }
    existing_chunks = read_jsonl(CHUNKS_PATH)
    existing_standards = read_json(STANDARDS_INDEX_PATH, [])
    chunks_by_file: dict[str, list[dict]] = {}
    standards_by_file = {
        item.get("source_file"): item
        for item in existing_standards
        if isinstance(item, dict) and item.get("source_file")
    }
    for chunk in existing_chunks:
        source_file = chunk.get("source_file")
        if source_file:
            chunks_by_file.setdefault(source_file, []).append(chunk)

    chunks: list[dict] = []
    standards: list[dict] = []
    warnings: list[str] = []
    skipped = 0
    rebuilt = 0

    if not pdfs:
        if existing_chunks or existing_standards:
            return {
                "standards": len(existing_standards),
                "chunks": len(existing_chunks),
                "rebuilt": 0,
                "skipped": 0,
                "warnings": ["No local PDF files found. Existing index cache was kept."],
            }
        write_jsonl(CHUNKS_PATH, [])
        write_json(STANDARDS_INDEX_PATH, [])
        return {"standards": 0, "chunks": 0, "rebuilt": 0, "skipped": 0, "warnings": ["No PDF files found."]}

    total = len(pdfs)
    for file_index, pdf_path in enumerate(pdfs, start=1):
        body = detect_body(pdf_path.name)
        standard_number = detect_standard_number(pdf_path.name, body)
        source_file = str(pdf_path.relative_to(pdf_dir)).replace("\\", "/")
        drive_info = drive_manifest.get(source_file, {})
        fingerprint = _pdf_fingerprint(pdf_path, use_ocr, ocr_language)
        existing_standard = standards_by_file.get(source_file)
        if (
            not force_rebuild
            and existing_standard
            and chunks_by_file.get(source_file)
            and _is_index_current(existing_standard, fingerprint)
        ):
            if progress_callback:
                progress_callback(file_index, total, source_file, "skip")
            chunks.extend(chunks_by_file[source_file])
            standards.append({**existing_standard, "index_status": "cached"})
            skipped += 1
            continue

        if progress_callback:
            progress_callback(file_index, total, source_file, "index")
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
                        "drive_path": drive_info.get("drive_path", ""),
                        "drive_file_id": drive_info.get("drive_file_id", ""),
                        "drive_web_url": drive_info.get("drive_web_url", ""),
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
        rebuilt += 1
        standards.append(
            {
                "source_file": source_file,
                "drive_path": drive_info.get("drive_path", ""),
                "drive_file_id": drive_info.get("drive_file_id", ""),
                "drive_web_url": drive_info.get("drive_web_url", ""),
                "body": body,
                "standard_number": standard_number,
                "title": "",
                "year": "",
                "page_count": get_page_count(pdf_path),
                "chunk_count": chunk_count,
                **fingerprint,
                "index_status": "indexed",
            }
        )

    write_jsonl(CHUNKS_PATH, chunks)
    write_json(STANDARDS_INDEX_PATH, standards)
    return {
        "standards": len(standards),
        "chunks": len(chunks),
        "rebuilt": rebuilt,
        "skipped": skipped,
        "warnings": warnings,
    }
