from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.compare import retrieve_by_body
from src.drive_storage import GoogleDriveConfigError, GoogleDriveSyncError, sync_drive_pdfs
from src.gemini_client import GeminiClientError, MissingGeminiApiKeyError, generate_answer, get_model_name
from src.i18n import LANGUAGES, TOPIC_CHIPS, t
from src.indexing import build_index, list_pdfs
from src.prompts import build_ask_prompt, build_compare_prompt
from src.search import search_chunks
from src.utils import BODIES, CHUNKS_PATH, PDF_DIR, STANDARDS_INDEX_PATH, ensure_data_dirs, read_json, read_jsonl


def source_caption(chunk: dict, lang: str) -> str:
    return (
        f"{t(lang, 'body')}: {chunk.get('body', '-')} | "
        f"{t(lang, 'standard')}: {chunk.get('standard_number') or '-'} | "
        f"{t(lang, 'source_file')}: {chunk.get('source_file') or '-'} | "
        f"{t(lang, 'clause')}: {chunk.get('clause') or '-'} | "
        f"{t(lang, 'page')}: {chunk.get('page') or '-'} | "
        f"{t(lang, 'score')}: {chunk.get('score', '-')}"
    )


def render_chunks(chunks: list[dict], lang: str) -> None:
    for i, chunk in enumerate(chunks, start=1):
        with st.expander(f"{i}. {source_caption(chunk, lang)}"):
            st.write(chunk.get("text", ""))


def apply_topic_chip(state_key: str, value: str) -> None:
    existing = st.session_state.get(state_key, "")
    st.session_state[state_key] = f"{existing} {value}".strip() if existing else value


def render_topic_chips(lang: str, state_key: str) -> None:
    st.caption(t(lang, "topic_helpers"))
    labels = TOPIC_CHIPS.get(lang, TOPIC_CHIPS["id"])
    cols = st.columns(3)
    for idx, (label, value) in enumerate(labels):
        with cols[idx % 3]:
            st.button(label, key=f"{state_key}_{idx}", on_click=apply_topic_chip, args=(state_key, value))


def main() -> None:
    load_dotenv()
    ensure_data_dirs()
    st.set_page_config(page_title=t("id", "app_title"), layout="wide")

    current_lang = st.session_state.get("lang_code", "id")
    lang = st.sidebar.selectbox(
        t(current_lang, "language"),
        options=list(LANGUAGES.keys()),
        index=list(LANGUAGES.keys()).index(current_lang),
        format_func=lambda code: LANGUAGES[code],
        key="lang_code",
    )
    language_name = LANGUAGES[lang]

    st.sidebar.title(t(lang, "app_title"))
    st.sidebar.write(f"**{t(lang, 'gemini_model')}:** `{get_model_name()}`")
    st.sidebar.write(f"**{t(lang, 'data_folder')}:** `{PDF_DIR}`")
    st.sidebar.info(t(lang, "privacy"))

    tabs = st.tabs([t(lang, "index_pdfs"), t(lang, "search"), t(lang, "ask"), t(lang, "compare"), t(lang, "settings")])

    with tabs[0]:
        st.header(t(lang, "index_pdfs"))
        st.subheader(t(lang, "drive_sync"))
        st.caption(t(lang, "drive_sync_help"))
        drive_col1, drive_col2 = st.columns(2)
        if drive_col1.button(t(lang, "sync_drive"), type="secondary"):
            try:
                with st.spinner(t(lang, "sync_drive")):
                    sync_result = sync_drive_pdfs()
                drive_col2.metric(t(lang, "drive_pdfs_found"), sync_result["available"])
                st.success(f"{t(lang, 'drive_sync_success')} {t(lang, 'downloaded_files')}: {sync_result['downloaded']}")
                if sync_result["files"]:
                    st.dataframe(pd.DataFrame({"PDF": sync_result["files"]}), use_container_width=True)
                if sync_result["warnings"]:
                    st.warning(t(lang, "warnings"))
                    for warning in sync_result["warnings"]:
                        st.write(f"- {warning}")
            except GoogleDriveConfigError:
                st.error(t(lang, "drive_config_missing"))
            except GoogleDriveSyncError as exc:
                st.error(f"{t(lang, 'drive_error')}: {exc}")
        else:
            drive_col2.metric(t(lang, "drive_pdfs_found"), "-")

        pdfs = list_pdfs()
        st.metric(t(lang, "pdfs_found"), len(pdfs))
        if pdfs:
            st.dataframe(pd.DataFrame({"PDF": [p.name for p in pdfs]}), use_container_width=True)
        else:
            st.warning(t(lang, "no_pdfs"))

        standards = read_json(STANDARDS_INDEX_PATH, [])
        chunks = read_jsonl(CHUNKS_PATH)
        st.subheader(t(lang, "index_status"))
        st.write(t(lang, "index_exists") if CHUNKS_PATH.exists() else t(lang, "no_index"))
        col1, col2 = st.columns(2)
        col1.metric(t(lang, "standards_indexed"), len(standards))
        col2.metric(t(lang, "chunks_created"), len(chunks))
        use_ocr = st.checkbox(t(lang, "use_ocr"), value=True, help=t(lang, "ocr_help"))
        ocr_language = st.selectbox(t(lang, "ocr_language"), ["eng+ind", "eng", "ind"], index=0)

        if st.button(t(lang, "rebuild_index"), type="primary"):
            with st.spinner(t(lang, "rebuild_index")):
                result = build_index(use_ocr=use_ocr, ocr_language=ocr_language)
            st.success(f"{t(lang, 'standards_indexed')}: {result['standards']} | {t(lang, 'chunks_created')}: {result['chunks']}")
            if result["warnings"]:
                st.warning(t(lang, "warnings"))
                for warning in result["warnings"]:
                    st.write(f"- {warning}")

    with tabs[1]:
        st.header(t(lang, "search"))
        query = st.text_input(t(lang, "question"), key="search_query")
        body = st.selectbox(t(lang, "body_filter"), ["ALL"] + BODIES, key="search_body")
        top_k = st.slider(t(lang, "num_excerpts"), 1, 20, 8, key="search_top_k")
        if st.button(t(lang, "search_button"), type="primary"):
            if not query.strip():
                st.error(t(lang, "empty_query"))
            else:
                results = search_chunks(query, body=body, top_k=top_k)
                if not results:
                    st.warning(t(lang, "no_results"))
                else:
                    render_chunks(results, lang)

    with tabs[2]:
        st.header(t(lang, "ask"))
        render_topic_chips(lang, "ask_question")
        question = st.text_area(t(lang, "question"), key="ask_question", height=120)
        ask_body = st.selectbox(t(lang, "body_filter"), ["ALL"] + BODIES, key="ask_body")
        ask_top_k = st.slider(t(lang, "num_excerpts"), 1, 15, 8, key="ask_top_k")
        if st.button(t(lang, "ask_gemini"), type="primary"):
            if not question.strip():
                st.error(t(lang, "empty_query"))
            else:
                retrieved = search_chunks(question, body=ask_body, top_k=ask_top_k)
                if not retrieved:
                    st.warning(t(lang, "no_results"))
                else:
                    prompt = build_ask_prompt(question, retrieved, language_name, lang)
                    try:
                        answer = generate_answer(prompt)
                        st.subheader(t(lang, "answer"))
                        st.markdown(answer)
                    except MissingGeminiApiKeyError:
                        st.error(t(lang, "missing_api"))
                    except GeminiClientError as exc:
                        st.error(f"{t(lang, 'gemini_error')}: {exc}")
                    st.subheader(t(lang, "retrieved_sources"))
                    render_chunks(retrieved, lang)

    with tabs[3]:
        st.header(t(lang, "compare"))
        render_topic_chips(lang, "compare_topic")
        topic = st.text_area(t(lang, "comparison_topic"), key="compare_topic", height=120)
        st.caption(t(lang, "selected_bodies"))
        cols = st.columns(len(BODIES))
        selected: list[str] = []
        for idx, body_name in enumerate(BODIES):
            default = body_name in ["IEC", "IEEE", "SPLN"]
            if cols[idx].checkbox(body_name, value=default, key=f"compare_{body_name}"):
                selected.append(body_name)
        compare_top_k = st.slider(t(lang, "num_excerpts"), 1, 10, 4, key="compare_top_k")
        if st.button(t(lang, "compare_button"), type="primary"):
            if not topic.strip():
                st.error(t(lang, "empty_query"))
            else:
                grouped = retrieve_by_body(topic, selected, compare_top_k)
                if not any(grouped.values()):
                    st.warning(t(lang, "no_results"))
                else:
                    prompt = build_compare_prompt(topic, grouped, language_name)
                    try:
                        answer = generate_answer(prompt)
                        st.subheader(t(lang, "answer"))
                        st.markdown(answer)
                    except MissingGeminiApiKeyError:
                        st.error(t(lang, "missing_api"))
                    except GeminiClientError as exc:
                        st.error(f"{t(lang, 'gemini_error')}: {exc}")
                    st.subheader(t(lang, "grouped_evidence"))
                    for body_name, evidence in grouped.items():
                        st.markdown(f"### {body_name}")
                        render_chunks(evidence, lang)

    with tabs[4]:
        st.header(t(lang, "settings"))
        st.write(t(lang, "about_text"))
        st.code(t(lang, "data_paths_note"), language="text")


if __name__ == "__main__":
    main()
