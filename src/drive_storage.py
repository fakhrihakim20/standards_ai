from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .utils import PDF_DIR, ensure_data_dirs

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleDriveConfigError(RuntimeError):
    """Raised when Google Drive credentials or folder ID are missing."""


class GoogleDriveSyncError(RuntimeError):
    """Raised when Google Drive listing or download fails."""


def _load_env() -> None:
    """Load .env when python-dotenv is installed."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ModuleNotFoundError:
        return


def _read_streamlit_secret(key: str) -> Any:
    """Read a Streamlit secret if Streamlit is available and configured."""
    try:
        import streamlit as st

        return st.secrets.get(key)
    except Exception:
        return None


def get_drive_folder_id() -> str:
    """Return the configured Google Drive folder ID."""
    _load_env()
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID") or _read_streamlit_secret("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        raise GoogleDriveConfigError("GOOGLE_DRIVE_FOLDER_ID is missing.")
    return str(folder_id).strip()


def _load_service_account_info() -> dict[str, Any]:
    """Load service account credentials from secrets, env JSON, or local file."""
    _load_env()
    secret_info = _read_streamlit_secret("GOOGLE_SERVICE_ACCOUNT_JSON")
    if secret_info:
        if isinstance(secret_info, dict):
            return dict(secret_info)
        return json.loads(str(secret_info))

    env_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if env_json:
        return json.loads(env_json)

    file_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if file_path:
        with Path(file_path).expanduser().open("r", encoding="utf-8") as f:
            return json.load(f)

    raise GoogleDriveConfigError("GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE is missing.")


def get_drive_service():
    """Create a read-only Google Drive API service."""
    try:
        info = _load_service_account_info()
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=[DRIVE_READONLY_SCOPE],
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except GoogleDriveConfigError:
        raise
    except Exception as exc:
        raise GoogleDriveConfigError(str(exc)) from exc


def list_drive_pdfs(folder_id: str | None = None) -> list[dict[str, str]]:
    """List PDF files in the configured Google Drive folder."""
    folder_id = folder_id or get_drive_folder_id()
    service = get_drive_service()
    query = (
        f"'{folder_id}' in parents and trashed = false and "
        "mimeType = 'application/pdf'"
    )
    try:
        files: list[dict[str, str]] = []
        page_token = None
        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                    pageToken=page_token,
                    orderBy="name",
                )
                .execute()
            )
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return files
    except Exception as exc:
        raise GoogleDriveSyncError(str(exc)) from exc


def sync_drive_pdfs(folder_id: str | None = None, dest_dir: Path = PDF_DIR) -> dict[str, Any]:
    """Download PDFs from Google Drive into the local PDF folder.

    The local folder is temporary storage on Streamlit Cloud. The app still indexes
    locally into JSONL and never sends full PDFs to Gemini.
    """
    ensure_data_dirs()
    folder_id = folder_id or get_drive_folder_id()
    service = get_drive_service()
    files = list_drive_pdfs(folder_id)
    downloaded: list[str] = []
    warnings: list[str] = []

    for file_info in files:
        file_id = file_info["id"]
        file_name = Path(file_info["name"]).name
        if not file_name.lower().endswith(".pdf"):
            file_name = f"{file_name}.pdf"
        target_path = dest_dir / file_name
        try:
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            target_path.write_bytes(buffer.getvalue())
            downloaded.append(file_name)
        except Exception as exc:
            warnings.append(f"{file_name}: {exc}")

    return {
        "folder_id": folder_id,
        "available": len(files),
        "downloaded": len(downloaded),
        "files": downloaded,
        "warnings": warnings,
    }
