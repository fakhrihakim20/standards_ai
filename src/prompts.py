from __future__ import annotations


INSUFFICIENT = {
    "id": "Cuplikan standar yang ditemukan belum cukup untuk menjawab ini dengan yakin.",
    "en": "The retrieved standards excerpts are insufficient to answer this confidently.",
}


def citation_label(chunk: dict) -> str:
    clause = chunk.get("clause") or "-"
    standard = chunk.get("standard_number") or chunk.get("source_file") or "-"
    return f"{chunk.get('body', '-')}; {standard}; clause/section {clause}; page {chunk.get('page', '-')}"


def format_context(chunks: list[dict]) -> str:
    """Create compact cited context for Gemini without exposing full PDFs."""
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        parts.append(
            f"[{i}] {citation_label(chunk)}\n"
            f"Excerpt:\n{chunk.get('text', '')[:1800]}"
        )
    return "\n\n".join(parts)


def build_ask_prompt(question: str, chunks: list[dict], language_name: str, lang_code: str) -> str:
    context = format_context(chunks)
    insufficient = INSUFFICIENT.get(lang_code, INSUFFICIENT["id"])
    return f"""You are an electrical engineering standards assistant.

Output language:
{language_name}

Answer only using the retrieved excerpts below.
Do not rely on outside knowledge unless explicitly marked as background.
Do not reproduce long copyrighted passages.
Summarize instead.
For every important technical claim, cite:
- standard body
- standard number or source file
- clause/section if available
- page number

If the retrieved excerpts are insufficient, say:
"{insufficient}"

Question:
{question}

Retrieved excerpts:
{context}
"""


def build_compare_prompt(topic: str, grouped_chunks: dict[str, list[dict]], language_name: str) -> str:
    contexts = {body: format_context(grouped_chunks.get(body, [])) for body in ["IEC", "IEEE", "SPLN", "SNI", "OTHER"]}
    return f"""You are an electrical engineering standards comparison assistant.

Output language:
{language_name}

Compare the selected standards only using the retrieved excerpts.
Do not use outside knowledge unless clearly marked as background.
Do not reproduce long copyrighted passages.

If a standard body has no relevant retrieved excerpt:
- In Bahasa Indonesia, write "tidak ditemukan dalam konteks yang diambil."
- In English, write "not found in retrieved context."

Topic:
{topic}

Retrieved IEC excerpts:
{contexts["IEC"]}

Retrieved IEEE excerpts:
{contexts["IEEE"]}

Retrieved SPLN excerpts:
{contexts["SPLN"]}

Retrieved SNI excerpts:
{contexts["SNI"]}

Retrieved OTHER excerpts:
{contexts["OTHER"]}

Output format:
1. Short summary / Ringkasan singkat
2. Markdown comparison table with columns:
   - Aspect / Aspek
   - IEC
   - IEEE
   - SPLN
   - SNI
   - Practical meaning / Makna praktis
3. Practical engineering interpretation / Interpretasi teknis praktis
4. Missing or uncertain evidence / Bukti yang belum lengkap atau belum pasti
5. Citations / Sitasi
"""

