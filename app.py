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
from src.i18n import LANGUAGES, t
from src.indexing import build_index, list_pdfs
from src.prompts import build_ask_prompt, build_compare_prompt
from src.search import search_chunks
from src.utils import BODIES, CHUNKS_PATH, PDF_DIR, STANDARDS_INDEX_PATH, ensure_data_dirs, read_json, read_jsonl


def apply_github_theme() -> None:
    """Apply a compact GitHub-inspired visual theme to Streamlit."""
    st.markdown(
        """
        <style>
        :root {
          --gh-canvas: #ffffff;
          --gh-canvas-subtle: #f6f8fa;
          --gh-border: #d0d7de;
          --gh-fg: #24292f;
          --gh-muted: #57606a;
          --gh-accent: #0969da;
          --gh-success: #1a7f37;
          --gh-danger: #cf222e;
        }

        .stApp {
          background: var(--gh-canvas);
          color: var(--gh-fg);
        }

        [data-testid="stSidebar"] {
          background: var(--gh-canvas-subtle);
          border-right: 1px solid var(--gh-border);
        }

        [data-testid="stSidebar"] h1 {
          font-size: 20px;
          line-height: 1.25;
        }

        .block-container {
          max-width: 1180px;
          padding-top: 72px;
        }

        h1, h2, h3 {
          color: var(--gh-fg);
          letter-spacing: 0;
        }

        h2, h3 {
          border-bottom: 1px solid var(--gh-border);
          padding-bottom: 8px;
        }

        [data-testid="stMetric"] {
          background: var(--gh-canvas-subtle);
          border: 1px solid var(--gh-border);
          border-radius: 6px;
          padding: 12px 14px;
        }

        [data-testid="stExpander"] {
          border: 1px solid var(--gh-border);
          border-radius: 6px;
          background: var(--gh-canvas);
          box-shadow: none;
        }

        .stTabs [data-baseweb="tab-list"] {
          gap: 0;
          border-bottom: 1px solid var(--gh-border);
        }

        .stTabs [data-baseweb="tab"] {
          border-radius: 6px 6px 0 0;
          padding: 10px 14px;
          color: var(--gh-muted);
        }

        .stTabs [aria-selected="true"] {
          color: var(--gh-fg);
          border: 1px solid var(--gh-border);
          border-bottom: 2px solid var(--gh-canvas);
          background: var(--gh-canvas);
        }

        .stButton > button {
          border-radius: 6px;
          border: 1px solid var(--gh-border);
          background: var(--gh-canvas-subtle);
          color: var(--gh-fg);
          font-weight: 600;
          box-shadow: none;
        }

        .stButton > button[kind="primary"] {
          background: var(--gh-success);
          border-color: rgba(27, 31, 36, 0.15);
          color: #ffffff;
        }

        .stTextInput input,
        .stTextArea textarea,
        .stSelectbox div[data-baseweb="select"],
        .stFileUploader section {
          border-radius: 6px;
        }

        div[data-testid="stDataFrame"] {
          border: 1px solid var(--gh-border);
          border-radius: 6px;
          overflow: hidden;
        }

        .stAlert {
          border-radius: 6px;
          border: 1px solid var(--gh-border);
        }

        code {
          border-radius: 6px;
          color: var(--gh-fg);
          background: var(--gh-canvas-subtle);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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


def get_session_drive_json() -> str | None:
    """Return service account JSON supplied through the UI for this session."""
    uploaded = st.session_state.get("drive_json_upload")
    if uploaded is not None:
        try:
            return uploaded.getvalue().decode("utf-8")
        except Exception:
            return None
    pasted = st.session_state.get("drive_json_paste", "")
    return pasted.strip() or None


def get_session_gemini_key() -> str | None:
    """Return a custom Gemini API key supplied through the UI."""
    return st.session_state.get("custom_gemini_api_key", "").strip() or None


def get_session_gemini_model() -> str:
    """Return a custom Gemini model name or the configured default."""
    return st.session_state.get("custom_gemini_model", "").strip() or get_model_name()


def main() -> None:
    load_dotenv()
    ensure_data_dirs()
    st.set_page_config(page_title=t("id", "app_title"), layout="wide")
    apply_github_theme()

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
    st.sidebar.text_input(
        t(lang, "custom_gemini_api_key"),
        type="password",
        key="custom_gemini_api_key",
        help=t(lang, "custom_gemini_help"),
    )
    st.sidebar.text_input(
        t(lang, "custom_gemini_model"),
        value=get_model_name(),
        key="custom_gemini_model",
    )
    st.sidebar.write(f"**{t(lang, 'gemini_model')}:** `{get_session_gemini_model()}`")
    st.sidebar.write(f"**{t(lang, 'data_folder')}:** `{PDF_DIR}`")
    st.sidebar.info(t(lang, "privacy"))

    tabs = st.tabs([t(lang, "index_pdfs"), t(lang, "ask"), t(lang, "compare"), t(lang, "settings")])

    with tabs[0]:
        st.header(t(lang, "index_pdfs"))
        st.subheader(t(lang, "drive_sync"))
        st.caption(t(lang, "drive_sync_help"))
        drive_folder_input = st.text_input(t(lang, "drive_folder"), key="drive_folder_input")
        st.file_uploader(
            t(lang, "drive_json_upload"),
            type=["json"],
            key="drive_json_upload",
            help=t(lang, "drive_json_help"),
        )
        st.text_area(
            t(lang, "drive_json_paste"),
            key="drive_json_paste",
            height=120,
            help=t(lang, "drive_json_help"),
        )
        drive_col1, drive_col2 = st.columns(2)
        if drive_col1.button(t(lang, "sync_drive"), type="secondary"):
            try:
                with st.spinner(t(lang, "sync_drive")):
                    sync_result = sync_drive_pdfs(
                        folder_id=drive_folder_input or None,
                        service_account_info=get_session_drive_json(),
                    )
                drive_col2.metric(t(lang, "drive_pdfs_found"), sync_result["available"])
                st.success(f"{t(lang, 'drive_sync_success')} {t(lang, 'downloaded_files')}: {sync_result['downloaded']}")
                if sync_result["locations"]:
                    st.subheader(t(lang, "drive_locations"))
                    st.dataframe(pd.DataFrame(sync_result["locations"]), use_container_width=True)
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
        st.header(t(lang, "ask"))
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
                        answer = generate_answer(
                            prompt,
                            api_key=get_session_gemini_key(),
                            model_name=get_session_gemini_model(),
                        )
                        st.subheader(t(lang, "answer"))
                        st.markdown(answer)
                    except MissingGeminiApiKeyError:
                        st.error(t(lang, "missing_api"))
                    except GeminiClientError as exc:
                        st.error(f"{t(lang, 'gemini_error')}: {exc}")
                    st.subheader(t(lang, "retrieved_sources"))
                    render_chunks(retrieved, lang)

    with tabs[2]:
        st.header(t(lang, "compare"))
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
                        answer = generate_answer(
                            prompt,
                            api_key=get_session_gemini_key(),
                            model_name=get_session_gemini_model(),
                        )
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

    with tabs[3]:
        st.header(t(lang, "settings"))
        st.write(t(lang, "about_text"))
        st.code(t(lang, "data_paths_note"), language="text")


if __name__ == "__main__":
    main()
