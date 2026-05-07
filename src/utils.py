from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"
INDEX_DIR = DATA_DIR / "index"
CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
STANDARDS_INDEX_PATH = INDEX_DIR / "standards_index.json"
DRIVE_MANIFEST_PATH = INDEX_DIR / "drive_manifest.json"

BODIES = ["IEC", "IEEE", "SPLN", "SNI", "OTHER"]


def ensure_data_dirs() -> None:
    """Create local data folders used by the prototype."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)


def safe_user_slug(email: str) -> str:
    """Create a filesystem-safe user slug for per-account local data."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (email or "guest").strip().lower()).strip("._-")
    return cleaned[:80] or "guest"


def user_data_paths(email: str) -> dict[str, Path]:
    """Return per-Google-account data paths for PDFs and indexes."""
    user_root = DATA_DIR / "users" / safe_user_slug(email)
    index_dir = user_root / "index"
    return {
        "root": user_root,
        "pdf_dir": user_root / "pdfs",
        "index_dir": index_dir,
        "chunks_path": index_dir / "chunks.jsonl",
        "standards_index_path": index_dir / "standards_index.json",
        "drive_manifest_path": index_dir / "drive_manifest.json",
    }


def ensure_user_data_dirs(email: str) -> dict[str, Path]:
    """Create and return per-account data directories."""
    paths = user_data_paths(email)
    paths["pdf_dir"].mkdir(parents=True, exist_ok=True)
    paths["index_dir"].mkdir(parents=True, exist_ok=True)
    return paths


def reset_user_cache(email: str) -> None:
    """Delete local PDFs and OCR/index files for one account without crashing on locked folders."""
    paths = user_data_paths(email)
    user_root = paths["root"]
    if user_root.exists():
        for item in sorted(user_root.rglob("*"), key=lambda path: len(path.parts), reverse=True):
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink(missing_ok=True)
                elif item.is_dir():
                    item.rmdir()
            except OSError:
                continue
        for directory in (paths["index_dir"], paths["pdf_dir"], user_root):
            try:
                if directory.exists():
                    directory.rmdir()
            except OSError:
                continue
    ensure_user_data_dirs(email)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file. Missing files return an empty list."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write dictionaries as UTF-8 JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path, default: Any) -> Any:
    """Read a JSON file, returning default when missing."""
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """Write pretty UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def detect_body(filename: str) -> str:
    """Detect likely standards body from a file name."""
    upper = filename.upper()
    for body in ["SPLN", "IEEE", "IEC", "SNI"]:
        if re.search(rf"(^|[^A-Z0-9]){body}([^A-Z0-9]|$)", upper):
            return body
    return "OTHER"


def detect_standard_number(filename: str, body: str) -> str:
    """Detect a simple standard identifier from a file name."""
    stem = Path(filename).stem
    cleaned = re.sub(r"[_\-]+", " ", stem).strip()
    if body == "OTHER":
        return cleaned
    pattern = re.compile(rf"\b{body}\s*([A-Z]*\s*)?(\d+[A-Z0-9\-/.:]*)", re.IGNORECASE)
    match = pattern.search(cleaned)
    if match:
        suffix = re.sub(r"\s+", " ", match.group(0)).strip()
        return suffix.upper()
    return f"{body} {cleaned}" if body not in cleaned.upper() else cleaned


def clean_text(text: str) -> str:
    """Normalize PDF text while preserving readable clauses and symbols."""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_slug(value: str) -> str:
    """Create a compact ASCII-ish id fragment."""
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return value[:60] or "chunk"
