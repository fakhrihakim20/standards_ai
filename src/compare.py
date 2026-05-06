from __future__ import annotations

from .search import search_chunks


def retrieve_by_body(topic: str, bodies: list[str], top_k: int) -> dict[str, list[dict]]:
    """Retrieve evidence separately for each selected standards body."""
    return {body: search_chunks(topic, body=body, top_k=top_k) for body in bodies}

