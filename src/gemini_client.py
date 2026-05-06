from __future__ import annotations

import os


class MissingGeminiApiKeyError(RuntimeError):
    """Raised when Gemini is requested without GEMINI_API_KEY."""


class GeminiClientError(RuntimeError):
    """Raised when the Gemini API call fails."""


def _load_env() -> None:
    """Load .env when python-dotenv is installed."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ModuleNotFoundError:
        return


def _read_secret(key: str) -> str | None:
    """Read Streamlit secrets when running on Streamlit Community Cloud."""
    try:
        import streamlit as st

        value = st.secrets.get(key)
        return str(value) if value else None
    except Exception:
        return None


def get_model_name() -> str:
    """Return configured Gemini model name."""
    _load_env()
    return os.getenv("GEMINI_MODEL") or _read_secret("GEMINI_MODEL") or "gemini-2.5-flash"


def generate_answer(prompt: str) -> str:
    """Generate an answer with Gemini.

    Full PDFs are never sent here; callers should pass only retrieved excerpts.
    """
    _load_env()
    api_key = os.getenv("GEMINI_API_KEY") or _read_secret("GEMINI_API_KEY")
    if not api_key:
        raise MissingGeminiApiKeyError("GEMINI_API_KEY is missing.")

    model_name = get_model_name()
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return getattr(response, "text", "") or "No answer returned by Gemini."
    except Exception as exc:
        raise GeminiClientError(str(exc)) from exc
