from __future__ import annotations

import re


CLAUSE_PATTERNS = [
    re.compile(r"^\s*((?:\d+\.){0,3}\d+)\s+[\w(]", re.IGNORECASE),
    re.compile(r"^\s*(Clause\s+\d+(?:\.\d+)*)\b", re.IGNORECASE),
    re.compile(r"^\s*(Section\s+\d+(?:\.\d+)*)\b", re.IGNORECASE),
    re.compile(r"^\s*(Bab\s+[IVXLCDM]+)\b", re.IGNORECASE),
    re.compile(r"^\s*(Pasal\s+\d+(?:\.\d+)*)\b", re.IGNORECASE),
    re.compile(r"^\s*(Butir\s+\d+(?:\.\d+)*)\b", re.IGNORECASE),
]


def detect_clause(text: str, fallback: str = "") -> str:
    """Find a likely clause/section heading in a chunk or page."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for pattern in CLAUSE_PATTERNS:
            match = pattern.match(line)
            if match:
                return match.group(1).strip()
    return fallback


def split_text_into_chunks(text: str, min_chars: int = 700, max_chars: int = 1200) -> list[str]:
    """Split page text into readable chunks, preferring paragraph boundaries."""
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_text(paragraph, max_chars))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = paragraph

    if current:
        chunks.append(current.strip())

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(merged[-1]) < min_chars and len(merged[-1]) + len(chunk) + 2 <= max_chars:
            merged[-1] = f"{merged[-1]}\n\n{chunk}"
        else:
            merged.append(chunk)
    return merged


def _split_long_text(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
            current = sentence[:max_chars]
            rest = sentence[max_chars:]
            while rest:
                chunks.append(current.strip())
                current = rest[:max_chars]
                rest = rest[max_chars:]
    if current:
        chunks.append(current.strip())
    return chunks

