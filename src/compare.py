from __future__ import annotations

from pathlib import Path

from .search import search_chunks


def retrieve_by_body(topic: str, bodies: list[str], top_k: int, chunks_path: Path | None = None) -> dict[str, list[dict]]:
    """Retrieve evidence separately for each selected standards body."""
    kwargs = {"chunks_path": chunks_path} if chunks_path else {}
    return {body: search_chunks(topic, body=body, top_k=top_k, **kwargs) for body in bodies}
