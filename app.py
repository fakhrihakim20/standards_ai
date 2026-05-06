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


def apply_material_you_theme(theme_mode: str) -> None:
    """Apply a Material You New Tab inspired day/night visual theme."""
    st.markdown(
        """
        <style>
        :root {
          --pp-bg: #0f1117;
          --pp-canvas: #151822;
          --pp-panel: #1d2230;
          --pp-panel-soft: #252b3a;
          --pp-field: #10131b;
          --pp-border: #343b4f;
          --pp-border-strong: #4a5268;
          --pp-text: #f5f7fb;
          --pp-muted: #9aa4b8;
          --pp-faint: #68738a;
          --pp-cyan: #31e0c5;
          --pp-blue: #6bb8ff;
          --pp-purple: #a78bfa;
          --pp-pink: #ff6fae;
          --pp-yellow: #ffd166;
          --pp-red: #ff6b78;
          --pp-green: #5de4a7;
          --pp-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
        }

        .stApp {
          color: var(--pp-text);
          background:
            radial-gradient(circle at 16% 8%, rgba(49, 224, 197, 0.10), transparent 28%),
            radial-gradient(circle at 84% 12%, rgba(255, 111, 174, 0.09), transparent 26%),
            linear-gradient(135deg, rgba(255,255,255,0.025) 25%, transparent 25%) 0 0 / 26px 26px,
            var(--pp-bg);
        }

        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, #11141d 0%, #181d28 100%);
          border-right: 1px solid var(--pp-border);
          box-shadow: 12px 0 40px rgba(0, 0, 0, 0.20);
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
          color: var(--pp-text);
        }

        [data-testid="stSidebar"] h1 {
          font-size: 18px;
          line-height: 1.25;
          padding-bottom: 10px;
          border-bottom: 1px solid var(--pp-border);
        }

        .block-container {
          max-width: 1220px;
          padding-top: 38px;
          padding-bottom: 56px;
        }

        h1, h2, h3 {
          color: var(--pp-text);
          letter-spacing: 0;
        }

        h1 {
          font-size: 34px;
          line-height: 1.1;
          font-weight: 760;
          margin-bottom: 18px;
        }

        h2, h3 {
          border-bottom: 0;
          padding-bottom: 8px;
        }

        p, label, span, div {
          color: inherit;
        }

        [data-testid="stMarkdownContainer"] p,
        [data-testid="stCaptionContainer"],
        .stCaptionContainer {
          color: var(--pp-muted);
        }

        [data-testid="stMetric"] {
          background:
            linear-gradient(135deg, rgba(49, 224, 197, 0.08), transparent 36%),
            var(--pp-panel);
          border: 1px solid var(--pp-border);
          border-radius: 8px;
          padding: 14px 16px;
          box-shadow: var(--pp-shadow);
        }

        [data-testid="stMetricLabel"] {
          color: var(--pp-muted);
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.02em;
        }

        [data-testid="stMetricValue"] {
          color: var(--pp-text);
        }

        [data-testid="stExpander"] {
          border: 1px solid var(--pp-border);
          border-radius: 8px;
          background: rgba(29, 34, 48, 0.88);
          box-shadow: none;
        }

        [data-testid="stExpander"] details summary {
          color: var(--pp-text);
          font-weight: 650;
        }

        .stTabs [data-baseweb="tab-list"] {
          gap: 6px;
          border-bottom: 0;
          background: rgba(15, 17, 23, 0.58);
          padding: 8px;
          border-radius: 8px 8px 0 0;
        }

        .stTabs [data-baseweb="tab"] {
          border-radius: 6px;
          padding: 10px 15px;
          color: var(--pp-muted);
          border: 1px solid transparent;
          background: transparent;
        }

        .stTabs [aria-selected="true"] {
          color: var(--pp-text);
          border: 1px solid rgba(49, 224, 197, 0.42);
          background: linear-gradient(135deg, rgba(49, 224, 197, 0.14), rgba(167, 139, 250, 0.11));
          box-shadow: inset 0 -2px 0 var(--pp-cyan);
        }

        .stButton > button {
          border-radius: 6px;
          border: 1px solid var(--pp-border-strong);
          background: var(--pp-panel-soft);
          color: var(--pp-text);
          font-weight: 600;
          box-shadow: none;
          min-height: 40px;
        }

        .stButton > button[kind="primary"] {
          background: linear-gradient(135deg, var(--pp-cyan), var(--pp-blue));
          border-color: rgba(49, 224, 197, 0.55);
          color: #081018;
          box-shadow: 0 12px 28px rgba(49, 224, 197, 0.18);
        }

        .stButton > button:hover {
          border-color: var(--pp-cyan);
          color: var(--pp-text);
        }

        .stButton > button[kind="primary"]:hover {
          color: #081018;
          filter: brightness(1.06);
        }

        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"] {
          border-radius: 6px;
          border: 1px solid var(--pp-border);
          background: var(--pp-field);
          color: var(--pp-text);
        }

        .stFileUploader section {
          border-radius: 8px;
          border: 1px dashed var(--pp-border-strong);
          background: rgba(16, 19, 27, 0.74);
        }

        .stTextInput input:focus,
        .stTextArea textarea:focus,
        .stNumberInput input:focus {
          border-color: var(--pp-cyan);
          box-shadow: 0 0 0 1px rgba(49, 224, 197, 0.32);
        }

        .stCheckbox label,
        .stRadio label,
        .stSlider label {
          color: var(--pp-text);
        }

        div[data-testid="stDataFrame"] {
          border: 1px solid var(--pp-border);
          border-radius: 8px;
          overflow: hidden;
          box-shadow: var(--pp-shadow);
        }

        .stAlert {
          border-radius: 8px;
          border: 1px solid var(--pp-border);
          background: rgba(29, 34, 48, 0.92);
        }

        [data-testid="stStatusWidget"] {
          border-radius: 8px;
          border: 1px solid var(--pp-border);
          background: rgba(29, 34, 48, 0.94);
        }

        div[data-baseweb="notification"] {
          border-radius: 8px;
        }

        code {
          border-radius: 6px;
          color: var(--pp-cyan);
          background: rgba(49, 224, 197, 0.10);
          border: 1px solid rgba(49, 224, 197, 0.18);
        }

        .stProgress > div > div > div > div {
          background: linear-gradient(90deg, var(--pp-cyan), var(--pp-purple), var(--pp-pink));
        }

        hr {
          border-color: transparent;
        }

        .pp-workspace-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 18px;
          margin: 0 0 22px 0;
          padding: 18px 20px;
          border: 1px solid var(--pp-border);
          border-radius: 8px;
          background:
            linear-gradient(135deg, rgba(49, 224, 197, 0.13), transparent 32%),
            linear-gradient(315deg, rgba(255, 111, 174, 0.10), transparent 34%),
            rgba(29, 34, 48, 0.88);
          box-shadow: var(--pp-shadow);
        }

        .pp-kicker {
          color: var(--pp-cyan);
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }

        .pp-title {
          color: var(--pp-text);
          font-size: 24px;
          font-weight: 780;
          line-height: 1.2;
          margin-top: 4px;
        }

        .pp-token-row {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 8px;
        }

        .pp-token-row span {
          display: inline-flex;
          align-items: center;
          height: 28px;
          padding: 0 10px;
          border-radius: 999px;
          border: 1px solid rgba(49, 224, 197, 0.30);
          background: rgba(16, 19, 27, 0.74);
          color: var(--pp-muted);
          font-size: 12px;
          font-weight: 650;
        }

        @media (max-width: 760px) {
          .pp-workspace-header {
            align-items: flex-start;
            flex-direction: column;
          }

          .pp-token-row {
            justify-content: flex-start;
          }
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


def update_status(status, label: str, state: str = "running") -> None:
    """Update a Streamlit status object, falling back to markdown placeholders."""
    if hasattr(status, "update"):
        status.update(label=label, state=state)
    else:
        status.write(label)


def render_workspace_header(lang: str, theme_mode: str) -> None:
    """Render a compact Material You inspired workspace header."""
    st.markdown(
        f"""
        <div class="pp-workspace-header">
          <div>
            <div class="pp-kicker">Engineering Docs, Simplified</div>
            <div class="pp-title">StandardsAtlas</div>
          </div>
          <div class="pp-token-row">
            <span>PDF</span><span>OCR</span><span>JSONL</span><span>Gemini</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    is_night = theme_mode == "night"
    if is_night:
        wallpaper = (
            "radial-gradient(circle at 18% 10%, rgba(96, 165, 250, 0.18), transparent 30%),"
            "radial-gradient(circle at 82% 8%, rgba(148, 163, 184, 0.12), transparent 28%),"
            "linear-gradient(180deg, #0f172a 0%, #111827 100%)"
        )
    else:
        wallpaper = (
            "radial-gradient(circle at 18% 8%, rgba(40, 85, 113, 0.10), transparent 30%),"
            "radial-gradient(circle at 84% 10%, rgba(148, 163, 184, 0.18), transparent 28%),"
            "linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%)"
        )
    palette = {
        "bg": "#0f172a" if is_night else "#f8fafc",
        "surface": "#111827" if is_night else "#ffffff",
        "surface_soft": "#1f2937" if is_night else "#eef2f7",
        "field": "#0b1220" if is_night else "#f8fafc",
        "border": "#334155" if is_night else "#d7dde8",
        "text": "#f8fafc" if is_night else "#111827",
        "muted": "#cbd5e1" if is_night else "#4b5563",
        "primary": "#60a5fa" if is_night else "#285571",
        "primary_text": "#07111f" if is_night else "#ffffff",
        "secondary": "#93c5fd" if is_night else "#475569",
        "tertiary": "#38bdf8" if is_night else "#0ea5e9",
        "success": "#86efac" if is_night else "#15803d",
        "shadow": "0 18px 44px rgba(0, 0, 0, 0.34)" if is_night else "0 16px 38px rgba(15, 23, 42, 0.10)",
        "alert_bg": "#f1f5f9" if not is_night else "#1e293b",
        "alert_text": "#1f2937" if not is_night else "#e5e7eb",
        "warning_bg": "#fff7ed" if not is_night else "#3b2a12",
        "warning_text": "#9a3412" if not is_night else "#fed7aa",
        "error_bg": "#fef2f2" if not is_night else "#3f1d24",
        "error_text": "#991b1b" if not is_night else "#fecaca",
        "wallpaper": wallpaper,
    }
    st.markdown(
        f"""
        <style>
        :root {{
          --pp-bg: {palette["bg"]};
          --pp-canvas: {palette["surface"]};
          --pp-panel: {palette["surface"]};
          --pp-panel-soft: {palette["surface_soft"]};
          --pp-field: {palette["field"]};
          --pp-border: {palette["border"]};
          --pp-border-strong: {palette["border"]};
          --pp-text: {palette["text"]};
          --pp-muted: {palette["muted"]};
          --pp-faint: {palette["muted"]};
          --pp-cyan: {palette["primary"]};
          --pp-blue: {palette["primary"]};
          --pp-purple: {palette["secondary"]};
          --pp-pink: {palette["tertiary"]};
          --pp-yellow: #ffd8a8;
          --pp-red: #ffb4ab;
          --pp-green: {palette["success"]};
          --pp-shadow: {palette["shadow"]};
        }}

        .stApp {{
          background: {palette["bg"]} !important;
        }}

        h2, h3,
        [data-testid="stSidebar"] h1 {{
          border-bottom: 0 !important;
        }}

        [data-testid="stSidebar"] {{
          background: {palette["surface"]} !important;
          border-right: 1px solid {palette["border"]};
        }}

        [data-testid="stMetric"],
        [data-testid="stExpander"],
        [data-testid="stStatusWidget"],
        .pp-workspace-header {{
          border-radius: 28px !important;
          background: {palette["surface"]} !important;
          box-shadow: {palette["shadow"]};
        }}

        .stButton > button {{
          border-radius: 999px !important;
          background: {palette["surface_soft"]};
          border-color: {palette["border"]};
          color: {palette["text"]};
        }}

        .stButton > button[kind="primary"] {{
          background: {palette["primary"]} !important;
          color: #ffffff !important;
          border-color: transparent !important;
          box-shadow: 0 10px 24px rgba(40, 85, 113, 0.22) !important;
        }}

        .stButton > button[kind="primary"] *,
        .stButton > button[kind="primary"] p {{
          color: #ffffff !important;
        }}

        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"],
        .stFileUploader section {{
          border-radius: 18px !important;
          background: {palette["field"]} !important;
          color: {palette["text"]} !important;
          border-color: {palette["border"]} !important;
        }}

        .stTabs [data-baseweb="tab-list"] {{
          border-radius: 999px !important;
          background: {palette["surface"]} !important;
          border: 0 !important;
          box-shadow: {palette["shadow"]};
        }}

        .stTabs [data-baseweb="tab"] {{
          border-radius: 999px !important;
          color: {palette["muted"]} !important;
          font-weight: 650 !important;
        }}

        .stTabs [aria-selected="true"] {{
          background: {palette["primary"]} !important;
          color: {palette["primary_text"]} !important;
          box-shadow: none !important;
          border-color: transparent !important;
        }}

        .pp-kicker {{
          color: {palette["primary"]} !important;
        }}

        .pp-workspace-header {{
          background: {palette["surface"]} !important;
        }}

        .stTabs [aria-selected="true"] {{
          border: 0 !important;
        }}

        [data-testid="stMetric"],
        [data-testid="stExpander"],
        [data-testid="stStatusWidget"],
        .stAlert,
        div[data-testid="stDataFrame"] {{
          border: 0 !important;
        }}

        .stAlert {{
          background: {palette["alert_bg"]} !important;
          color: {palette["alert_text"]} !important;
          border-color: {palette["border"]} !important;
        }}

        .stAlert * {{
          color: inherit !important;
        }}

        div[data-baseweb="notification"][kind="error"],
        .stAlert[data-baseweb="notification"] {{
          color: {palette["alert_text"]} !important;
        }}

        code {{
          color: {palette["primary"]} !important;
          background: {"#eaf2ff" if not is_night else "#172554"} !important;
          border-color: {"#bfdbfe" if not is_night else "#1d4ed8"} !important;
        }}

        .stProgress > div > div > div > div {{
          background: linear-gradient(90deg, {palette["primary"]}, {palette["tertiary"]}) !important;
        }}

        .pp-token-row span {{
          border-radius: 999px;
          background: {palette["surface_soft"]};
          border-color: {palette["border"]};
          color: {palette["muted"]};
        }}

        [data-testid="stMetric"],
        [data-testid="stExpander"],
        [data-testid="stStatusWidget"],
        .pp-workspace-header,
        .stTabs [data-baseweb="tab-list"] {{
          position: relative;
          overflow: hidden;
          backdrop-filter: blur(10px) saturate(112%);
          -webkit-backdrop-filter: blur(10px) saturate(112%);
          border: 0 !important;
          box-shadow:
            {palette["shadow"]};
        }}

        [data-testid="stMetric"]::before,
        [data-testid="stExpander"]::before,
        [data-testid="stStatusWidget"]::before,
        .pp-workspace-header::before,
        .stTabs [data-baseweb="tab-list"]::before {{
          content: none;
          position: absolute;
          inset: 0;
          pointer-events: none;
          border-radius: inherit;
          background:
            linear-gradient(135deg, rgba(255,255,255,0.48), transparent 34%),
            radial-gradient(circle at 88% 12%, {"rgba(40,85,113,0.16)" if not is_night else "rgba(96,165,250,0.20)"}, transparent 30%),
            radial-gradient(circle at 12% 88%, rgba(255,255,255,0.18), transparent 28%);
          mix-blend-mode: {"normal" if not is_night else "screen"};
          opacity: {"0.62" if not is_night else "0.38"};
        }}

        [data-testid="stMetric"]::after,
        .pp-workspace-header::after {{
          content: none;
          position: absolute;
          pointer-events: none;
          inset: 1px;
          border-radius: inherit;
          border: 1px solid {"rgba(255,255,255,0.54)" if not is_night else "rgba(147,197,253,0.16)"};
          box-shadow:
            0 0 0 1px {"rgba(40,85,113,0.05)" if not is_night else "rgba(96,165,250,0.10)"},
            inset 10px 0 18px {"rgba(40,85,113,0.08)" if not is_night else "rgba(96,165,250,0.08)"},
            inset -10px 0 18px {"rgba(14,165,233,0.07)" if not is_night else "rgba(56,189,248,0.07)"};
        }}

        .stButton > button {{
          backdrop-filter: blur(14px) saturate(135%);
          -webkit-backdrop-filter: blur(14px) saturate(135%);
          box-shadow:
            0 8px 22px {"rgba(15,23,42,0.08)" if not is_night else "rgba(0,0,0,0.28)"};
        }}

        .stTextInput input,
        .stTextArea textarea,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"] {{
          box-shadow:
            inset 0 -1px 0 {"rgba(15,23,42,0.04)" if not is_night else "rgba(255,255,255,0.04)"};
        }}

        summary,
        summary *,
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary *,
        [data-baseweb="tab-list"],
        [data-baseweb="tab-list"] *,
        button[data-baseweb="tab"],
        button[data-baseweb="tab"] *,
        [data-testid="stTab"],
        [data-testid="stTab"] * {{
          border: 0 !important;
          border-bottom: 0 !important;
          outline: 0 !important;
          box-shadow: none !important;
        }}

        [data-baseweb="tab-highlight"] {{
          display: none !important;
          opacity: 0 !important;
          height: 0 !important;
          border: 0 !important;
          box-shadow: none !important;
        }}

        [data-testid="stExpander"] details {{
          border: 0 !important;
          outline: 0 !important;
          box-shadow: none !important;
        }}

        button[data-baseweb="tab"][aria-selected="true"],
        button[data-baseweb="tab"][aria-selected="true"] * {{
          background: {palette["primary"]} !important;
          color: {palette["primary_text"]} !important;
        }}

        .stSelectbox *,
        .stSelectbox [role="combobox"],
        .stSelectbox [aria-haspopup="listbox"],
        .stSelectbox [aria-expanded],
        div[data-baseweb="select"],
        div[data-baseweb="select"] *,
        input[role="combobox"],
        input[aria-haspopup="listbox"] {{
          border: 0 !important;
          outline: 0 !important;
          box-shadow: none !important;
        }}

        .stSelectbox div[data-baseweb="select"],
        div[data-baseweb="select"] {{
          background: {palette["field"]} !important;
          border-radius: 18px !important;
        }}

        input[role="combobox"],
        input[aria-haspopup="listbox"] {{
          background: transparent !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    theme_mode = st.session_state.get("theme_mode", "day")
    apply_material_you_theme(theme_mode)

    current_lang = st.session_state.get("lang_code", "id")
    lang = st.sidebar.selectbox(
        t(current_lang, "language"),
        options=list(LANGUAGES.keys()),
        index=list(LANGUAGES.keys()).index(current_lang),
        format_func=lambda code: LANGUAGES[code],
        key="lang_code",
    )
    language_name = LANGUAGES[lang]
    theme_mode = st.sidebar.radio(
        t(lang, "appearance_mode"),
        options=["day", "night"],
        index=["day", "night"].index(theme_mode) if theme_mode in {"day", "night"} else 0,
        format_func=lambda mode: t(lang, f"{mode}_mode"),
        horizontal=True,
        key="theme_mode",
    )

    render_workspace_header(lang, theme_mode)

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
        with st.expander(t(lang, "drive_sync_settings"), expanded=False):
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
        drive_folder_input = st.session_state.get("drive_folder_input", "")
        drive_path_filter = st.session_state.get("drive_path_filter", "")
        drive_max_depth = st.session_state.get("drive_max_depth", 2)
        drive_max_files = st.session_state.get("drive_max_files", 100)
        drive_recursive = st.session_state.get("drive_recursive", True)
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
        with st.expander(t(lang, "index_cache_settings"), expanded=False):
            cache_folder_input = st.text_input(
                t(lang, "index_cache_folder"),
                value=st.session_state.get("index_cache_folder_input", ""),
                key="index_cache_folder_input",
                help=t(lang, "index_cache_folder_help"),
            )
            if st.button(t(lang, "test_cache_folder")):
                try:
                    diagnostic = diagnose_index_cache_folder(
                        folder_id=cache_folder_input or drive_folder_input or None,
                        service_account_info=get_session_drive_json(),
                        write_test=True,
                    )
                    st.json(diagnostic)
                    capabilities = diagnostic.get("capabilities", {})
                    if not capabilities.get("canAddChildren"):
                        st.warning(t(lang, "cache_folder_no_write"))
                    elif diagnostic.get("write_test") == "ok":
                        st.success(t(lang, "cache_folder_write_ok"))
                    elif diagnostic.get("existing_file_update_test") == "ok":
                        st.success(t(lang, "cache_folder_update_ok"))
                    elif diagnostic.get("write_test") == "failed":
                        st.warning(t(lang, "cache_folder_write_failed"))
                except CloudStoreError as exc:
                    st.error(f"{t(lang, 'cloud_store_error')}: {exc}")
        cache_folder_input = st.session_state.get("index_cache_folder_input", "")
        cache_folder_id = cache_folder_input or drive_folder_input or None
        if cache_folder_id:
            st.caption(f"{t(lang, 'cache_folder_target')}: `{cache_folder_id}`")
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
                with st.status(t(lang, "ask_status_start"), expanded=True) as status:
                    status.write(t(lang, "status_searching"))
                    retrieved = search_chunks(question, body=ask_body, top_k=ask_top_k)
                    status.write(f"{t(lang, 'status_sources_found')}: {len(retrieved)}")
                    if not retrieved:
                        update_status(status, t(lang, "status_no_sources"), "error")
                        st.warning(t(lang, "no_results"))
                    else:
                        status.write(t(lang, "status_building_prompt"))
                        prompt = build_ask_prompt(question, retrieved, language_name, lang)
                        try:
                            status.write(t(lang, "status_calling_gemini"))
                            answer = generate_answer(
                                prompt,
                                api_key=get_session_gemini_key(),
                                model_name=get_session_gemini_model(),
                            )
                            update_status(status, t(lang, "status_done"), "complete")
                            st.subheader(t(lang, "answer"))
                            st.markdown(answer)
                        except MissingGeminiApiKeyError:
                            update_status(status, t(lang, "status_failed"), "error")
                            st.error(t(lang, "missing_api"))
                        except GeminiClientError as exc:
                            update_status(status, t(lang, "status_failed"), "error")
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
                with st.status(t(lang, "compare_status_start"), expanded=True) as status:
                    status.write(t(lang, "status_searching_by_body"))
                    grouped = retrieve_by_body(topic, selected, compare_top_k)
                    evidence_count = sum(len(items) for items in grouped.values())
                    status.write(f"{t(lang, 'status_sources_found')}: {evidence_count}")
                    if not any(grouped.values()):
                        update_status(status, t(lang, "status_no_sources"), "error")
                        st.warning(t(lang, "no_results"))
                    else:
                        status.write(t(lang, "status_building_prompt"))
                        prompt = build_compare_prompt(topic, grouped, language_name)
                        try:
                            status.write(t(lang, "status_calling_gemini"))
                            answer = generate_answer(
                                prompt,
                                api_key=get_session_gemini_key(),
                                model_name=get_session_gemini_model(),
                            )
                            update_status(status, t(lang, "status_done"), "complete")
                            st.subheader(t(lang, "answer"))
                            st.markdown(answer)
                        except MissingGeminiApiKeyError:
                            update_status(status, t(lang, "status_failed"), "error")
                            st.error(t(lang, "missing_api"))
                        except GeminiClientError as exc:
                            update_status(status, t(lang, "status_failed"), "error")
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
