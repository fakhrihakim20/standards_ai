from __future__ import annotations

import sys
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.cloud_store import (
    CloudStoreError,
    MissingEncryptionKeyError,
    diagnose_index_cache_folder,
    load_index_cache,
    load_user_settings,
    save_index_cache,
    save_user_settings,
)
from src.compare import retrieve_by_body
from src.drive_storage import GoogleDriveConfigError, GoogleDriveSyncError, sync_drive_pdfs
from src.gemini_client import GeminiClientError, MissingGeminiApiKeyError, generate_answer, get_model_name
from src.i18n import LANGUAGES, t
from src.indexing import build_index, list_pdfs
from src.prompts import build_ask_prompt, build_compare_prompt
from src.search import search_chunks
from src.utils import BODIES, CHUNKS_PATH, DRIVE_MANIFEST_PATH, PDF_DIR, STANDARDS_INDEX_PATH, ensure_data_dirs, read_json, read_jsonl, write_json


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
    source_location = chunk.get("drive_path") or chunk.get("source_file") or "-"
    return (
        f"{t(lang, 'body')}: {chunk.get('body', '-')} | "
        f"{t(lang, 'standard')}: {chunk.get('standard_number') or '-'} | "
        f"{t(lang, 'source_file')}: {source_location} | "
        f"{t(lang, 'clause')}: {chunk.get('clause') or '-'} | "
        f"{t(lang, 'page')}: {chunk.get('page') or '-'} | "
        f"{t(lang, 'score')}: {chunk.get('score', '-')}"
    )


def render_chunks(chunks: list[dict], lang: str) -> None:
    for i, chunk in enumerate(chunks, start=1):
        with st.expander(f"{i}. {source_caption(chunk, lang)}"):
            if chunk.get("drive_web_url"):
                st.markdown(f"[Google Drive PDF]({chunk['drive_web_url']})")
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


def auth_configured() -> bool:
    """Return whether Streamlit OIDC auth secrets are configured."""
    try:
        auth = st.secrets.get("auth")
        return bool(auth and auth.get("client_id") and auth.get("client_secret"))
    except Exception:
        return False


def login_disabled_for_local_dev() -> bool:
    """Allow local development without OAuth when explicitly requested."""
    try:
        secret_value = st.secrets.get("DISABLE_LOGIN")
    except Exception:
        secret_value = None
    value = os.getenv("DISABLE_LOGIN") or secret_value
    return str(value).lower() in {"1", "true", "yes"}


def current_user_email() -> str:
    """Return logged-in user email, or a guest identity for local development."""
    try:
        if st.user.is_logged_in:
            return str(st.user.get("email") or st.user.get("name") or "guest")
    except Exception:
        pass
    return "guest"


def current_user_name() -> str:
    """Return a display name for the current user."""
    try:
        if st.user.is_logged_in:
            return str(st.user.get("name") or st.user.get("email") or "User")
    except Exception:
        pass
    return "Guest"


def login_screen(lang: str) -> None:
    """Render Google login gate."""
    st.header(t(lang, "login_required"))
    st.write(t(lang, "login_intro"))
    if auth_configured():
        if st.button(t(lang, "login_google"), type="primary"):
            try:
                st.login()
            except Exception as exc:
                st.error(f"{t(lang, 'auth_error')} ({type(exc).__name__})")
    else:
        st.warning(t(lang, "auth_not_configured"))


def service_account_email_from_json(raw_json: str | None) -> str:
    """Return client_email from a service account JSON string."""
    if not raw_json:
        return ""
    try:
        return str(json.loads(raw_json).get("client_email", ""))
    except Exception:
        return ""


def load_defaults_to_session(lang: str) -> None:
    """Load encrypted per-user defaults from Drive into session state."""
    try:
        settings = load_user_settings(
            current_user_email(),
            folder_id=st.session_state.get("drive_folder_input") or None,
            service_account_info=get_session_drive_json(),
        )
        if not settings:
            st.toast(t(lang, "defaults_not_found"))
            return
        st.session_state["custom_gemini_api_key"] = settings.get("gemini_api_key", "")
        st.session_state["custom_gemini_model"] = settings.get("gemini_model", get_model_name())
        st.session_state["drive_folder_input"] = settings.get("drive_folder", "")
        st.session_state["drive_json_paste"] = settings.get("drive_service_account_json", "")
        st.toast(t(lang, "defaults_loaded"))
    except MissingEncryptionKeyError:
        st.toast(t(lang, "encryption_missing"))
    except CloudStoreError as exc:
        st.toast(f"{t(lang, 'cloud_store_error')}: {exc}")


def save_defaults_from_session(lang: str) -> None:
    """Save encrypted per-user defaults from session state to Drive."""
    raw_drive_json = get_session_drive_json()
    settings = {
        "gemini_api_key": get_session_gemini_key() or "",
        "gemini_model": get_session_gemini_model(),
        "drive_folder": st.session_state.get("drive_folder_input", ""),
        "drive_service_account_json": raw_drive_json or "",
        "drive_service_account_email": service_account_email_from_json(raw_drive_json),
        "google_account": current_user_email(),
    }
    try:
        save_user_settings(
            current_user_email(),
            settings,
            folder_id=settings["drive_folder"] or None,
            service_account_info=raw_drive_json,
        )
        st.toast(t(lang, "defaults_saved"))
    except MissingEncryptionKeyError:
        st.toast(t(lang, "encryption_missing"))
    except CloudStoreError as exc:
        st.toast(f"{t(lang, 'cloud_store_error')}: {exc}")


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

    if not login_disabled_for_local_dev():
        try:
            if not st.user.is_logged_in:
                login_screen(lang)
                st.stop()
        except Exception:
            login_screen(lang)
            st.stop()

    st.sidebar.title(t(lang, "app_title"))
    st.sidebar.write(f"**{t(lang, 'logged_in_as')}:** {current_user_name()}")
    if auth_configured():
        st.sidebar.button(t(lang, "logout"), on_click=st.logout)
    st.sidebar.button(t(lang, "load_defaults"), on_click=load_defaults_to_session, args=(lang,))
    st.sidebar.button(t(lang, "save_defaults"), on_click=save_defaults_from_session, args=(lang,))
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
        filter_col, depth_col, limit_col = st.columns(3)
        drive_path_filter = filter_col.text_input(
            t(lang, "drive_path_filter"),
            key="drive_path_filter",
            help=t(lang, "drive_path_filter_help"),
        )
        drive_max_depth = depth_col.number_input(
            t(lang, "drive_max_depth"),
            min_value=0,
            max_value=10,
            value=2,
            step=1,
            help=t(lang, "drive_max_depth_help"),
        )
        drive_max_files = limit_col.number_input(
            t(lang, "drive_max_files"),
            min_value=0,
            max_value=10000,
            value=100,
            step=50,
            help=t(lang, "drive_max_files_help"),
        )
        drive_recursive = st.checkbox(t(lang, "drive_recursive"), value=True, help=t(lang, "drive_recursive_help"))
        drive_col1, drive_col2 = st.columns(2)
        if drive_col1.button(t(lang, "sync_drive"), type="secondary"):
            try:
                with st.spinner(t(lang, "sync_drive")):
                    sync_result = sync_drive_pdfs(
                        folder_id=drive_folder_input or None,
                        service_account_info=get_session_drive_json(),
                        recursive=drive_recursive,
                        max_depth=int(drive_max_depth),
                        max_files=None if int(drive_max_files) == 0 else int(drive_max_files),
                        path_filter=drive_path_filter or None,
                    )
                drive_col2.metric(t(lang, "drive_pdfs_found"), sync_result["available"])
                st.success(
                    f"{t(lang, 'drive_sync_success')} "
                    f"{t(lang, 'downloaded_files')}: {sync_result['downloaded']} | "
                    f"{t(lang, 'skipped_files')}: {sync_result.get('skipped', 0)}"
                )
                if sync_result["locations"]:
                    write_json(DRIVE_MANIFEST_PATH, sync_result["locations"])
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

        standards = read_json(STANDARDS_INDEX_PATH, [])
        chunks = read_jsonl(CHUNKS_PATH)
        standards_by_file = {
            item.get("source_file"): item
            for item in standards
            if isinstance(item, dict) and item.get("source_file")
        }
        pdfs = list_pdfs()
        st.metric(t(lang, "pdfs_found"), len(pdfs))
        if pdfs:
            pdf_status_rows = []
            for pdf_path in pdfs:
                source_file = str(pdf_path.relative_to(PDF_DIR)).replace("\\", "/")
                indexed = standards_by_file.get(source_file, {})
                pdf_status_rows.append(
                    {
                        "PDF": source_file,
                        t(lang, "index_marker"): t(lang, "indexed_marker") if indexed else t(lang, "not_indexed_marker"),
                        t(lang, "chunks_created"): indexed.get("chunk_count", 0),
                        t(lang, "cache_marker"): indexed.get("index_status", ""),
                    }
                )
            st.dataframe(pd.DataFrame(pdf_status_rows), use_container_width=True)
        else:
            st.warning(t(lang, "no_pdfs"))

        st.subheader(t(lang, "index_status"))
        st.write(t(lang, "index_exists") if CHUNKS_PATH.exists() else t(lang, "no_index"))
        col1, col2 = st.columns(2)
        col1.metric(t(lang, "standards_indexed"), len(standards))
        col2.metric(t(lang, "chunks_created"), len(chunks))
        if st.session_state.get("last_cache_action"):
            st.info(st.session_state["last_cache_action"])
        active_service_account_email = service_account_email_from_json(get_session_drive_json())
        if active_service_account_email:
            st.caption(f"{t(lang, 'active_service_account')}: `{active_service_account_email}`")
        st.caption(t(lang, "index_cache_help"))
        cache_folder_input = st.text_input(
            t(lang, "index_cache_folder"),
            value=st.session_state.get("index_cache_folder_input", ""),
            key="index_cache_folder_input",
            help=t(lang, "index_cache_folder_help"),
        )
        cache_folder_id = cache_folder_input or drive_folder_input or None
        if cache_folder_id:
            st.caption(f"{t(lang, 'cache_folder_target')}: `{cache_folder_id}`")
        if st.button(t(lang, "test_cache_folder")):
            try:
                diagnostic = diagnose_index_cache_folder(
                    folder_id=cache_folder_id,
                    service_account_info=get_session_drive_json(),
                    write_test=True,
                )
                st.json(diagnostic)
                capabilities = diagnostic.get("capabilities", {})
                if not capabilities.get("canAddChildren"):
                    st.warning(t(lang, "cache_folder_no_write"))
                elif diagnostic.get("write_test") == "ok":
                    st.success(t(lang, "cache_folder_write_ok"))
            except CloudStoreError as exc:
                st.error(f"{t(lang, 'cloud_store_error')}: {exc}")
        cache_col1, cache_col2 = st.columns(2)
        if cache_col1.button(t(lang, "load_index_cache")):
            try:
                cache_result = load_index_cache(
                    folder_id=cache_folder_id,
                    service_account_info=get_session_drive_json(),
                )
                st.session_state["last_cache_action"] = t(lang, "cache_loaded_marker")
                st.success(
                    f"{t(lang, 'index_cache_loaded')} "
                    f"{t(lang, 'standards_indexed')}: {cache_result['standards']} | "
                    f"{t(lang, 'chunks_created')}: {cache_result['chunks']} | "
                    f"{t(lang, 'cache_location')}: {cache_result.get('cache_location', '-')}"
                )
            except CloudStoreError as exc:
                st.error(f"{t(lang, 'cloud_store_error')}: {exc}")
        if cache_col2.button(t(lang, "save_index_cache")):
            try:
                cache_result = save_index_cache(
                    folder_id=cache_folder_id,
                    service_account_info=get_session_drive_json(),
                )
                st.session_state["last_cache_action"] = t(lang, "cache_saved_marker")
                st.success(
                    f"{t(lang, 'index_cache_saved')} "
                    f"{t(lang, 'standards_indexed')}: {cache_result['standards']} | "
                    f"{t(lang, 'chunks_created')}: {cache_result['chunks']} | "
                    f"{t(lang, 'cache_location')}: {cache_result.get('cache_location', '-')}"
                )
            except CloudStoreError as exc:
                st.error(f"{t(lang, 'cloud_store_error')}: {exc}")
        use_ocr = st.checkbox(t(lang, "use_ocr"), value=True, help=t(lang, "ocr_help"))
        ocr_language = st.selectbox(t(lang, "ocr_language"), ["eng+ind", "eng", "ind"], index=0)
        force_rebuild = st.checkbox(t(lang, "force_rebuild"), value=False, help=t(lang, "force_rebuild_help"))

        if st.button(t(lang, "rebuild_index"), type="primary"):
            progress_bar = st.progress(0)
            progress_text = st.empty()

            def update_index_progress(current: int, total: int, source_file: str, action: str) -> None:
                progress_bar.progress(current / max(total, 1))
                action_label = t(lang, "index_skipping") if action == "skip" else t(lang, "index_processing")
                progress_text.write(f"{action_label} {current}/{total}: `{source_file}`")

            result = build_index(
                use_ocr=use_ocr,
                ocr_language=ocr_language,
                force_rebuild=force_rebuild,
                progress_callback=update_index_progress,
            )
            progress_bar.progress(1.0)
            progress_text.write(t(lang, "index_done"))
            st.success(
                f"{t(lang, 'standards_indexed')}: {result['standards']} | "
                f"{t(lang, 'chunks_created')}: {result['chunks']} | "
                f"{t(lang, 'rebuilt_files')}: {result.get('rebuilt', 0)} | "
                f"{t(lang, 'skipped_files')}: {result.get('skipped', 0)}"
            )
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
