from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .utils import CHUNKS_PATH, read_jsonl


def search_chunks(query: str, body: str | None = None, top_k: int = 8) -> list[dict]:
    """Search indexed chunks with TF-IDF plus a small keyword overlap boost."""
    query = (query or "").strip()
    if not query:
        return []

    rows = read_jsonl(CHUNKS_PATH)
    if body and body.upper() != "ALL":
        rows = [row for row in rows if row.get("body") == body.upper()]
    if not rows:
        return []

    corpus = [row.get("text", "") for row in rows]
    if not any(corpus):
        return []

    query_terms = set(re.findall(r"\w+", query.lower()))
    try:
        vectorizer = TfidfVectorizer(stop_words=None, ngram_range=(1, 2), max_features=20000)
        matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, matrix).ravel()
    except ValueError:
        similarities = [0.0 for _ in rows]

    results: list[dict] = []
    for row, sim in zip(rows, similarities):
        text_terms = set(re.findall(r"\w+", row.get("text", "").lower()))
        overlap = len(query_terms & text_terms) / max(len(query_terms), 1)
        score = float(sim) + 0.15 * overlap
        if score <= 0:
            continue
        item = dict(row)
        item["score"] = round(score, 4)
        results.append(item)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[: max(1, top_k)]
