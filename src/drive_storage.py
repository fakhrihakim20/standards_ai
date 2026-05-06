from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .utils import PDF_DIR, ensure_data_dirs

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"


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


def parse_drive_folder_id(value: str) -> str:
    """Extract a Google Drive folder ID from a raw ID or folder URL."""
    value = (value or "").strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    return value


def get_drive_folder_id(folder_id: str | None = None) -> str:
    """Return the configured Google Drive folder ID."""
    _load_env()
    folder_id = folder_id or os.getenv("GOOGLE_DRIVE_FOLDER_ID") or _read_streamlit_secret("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        raise GoogleDriveConfigError("GOOGLE_DRIVE_FOLDER_ID is missing.")
    return parse_drive_folder_id(str(folder_id))


def _load_service_account_info(service_account_info: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Load service account credentials from secrets, env JSON, or local file."""
    _load_env()
    if service_account_info:
        if isinstance(service_account_info, dict):
            return service_account_info
        return json.loads(service_account_info)

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


def get_drive_service(service_account_info: dict[str, Any] | str | None = None):
    """Create a read-only Google Drive API service."""
    try:
        info = _load_service_account_info(service_account_info)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=[DRIVE_READONLY_SCOPE],
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except GoogleDriveConfigError:
        raise
    except Exception as exc:
        raise GoogleDriveConfigError(str(exc)) from exc


def _list_drive_children(service, folder_id: str, mime_type: str | None = None) -> list[dict[str, str]]:
    """List direct children in a Drive folder, optionally filtered by MIME type."""
    mime_clause = f" and mimeType = '{mime_type}'" if mime_type else ""
    query = f"'{folder_id}' in parents and trashed = false{mime_clause}"
    files: list[dict[str, str]] = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, shortcutDetails)",
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


def list_drive_pdfs(
    folder_id: str | None = None,
    recursive: bool = True,
    max_depth: int = 5,
    service_account_info: dict[str, Any] | str | None = None,
) -> list[dict[str, str]]:
    """List PDF files in the configured Google Drive folder.

    Recursive listing helps when a standards library is grouped into IEC/IEEE/SPLN
    subfolders.
    """
    folder_id = get_drive_folder_id(folder_id)
    service = get_drive_service(service_account_info)
    return _list_drive_pdfs_with_service(service, folder_id, recursive, max_depth, path="", visited=set())


def _list_drive_pdfs_with_service(
    service,
    folder_id: str,
    recursive: bool,
    max_depth: int,
    path: str,
    visited: set[str],
) -> list[dict[str, str]]:
    """List PDFs using an existing Drive service instance."""
    try:
        if folder_id in visited:
            return []
        visited.add(folder_id)

        files = _list_drive_children(service, folder_id, "application/pdf")
        for file_info in files:
            file_info["drive_path"] = f"{path}/{file_info['name']}".strip("/")
        if recursive and max_depth > 0:
            folders = _list_drive_children(service, folder_id, FOLDER_MIME_TYPE)
            shortcuts = [
                item
                for item in _list_drive_children(service, folder_id, SHORTCUT_MIME_TYPE)
                if item.get("shortcutDetails", {}).get("targetMimeType") == FOLDER_MIME_TYPE
            ]
            for shortcut in shortcuts:
                shortcut["id"] = shortcut["shortcutDetails"]["targetId"]
                folders.append(shortcut)

            for folder in folders:
                folder_path = f"{path}/{folder['name']}".strip("/")
                files.extend(
                    _list_drive_pdfs_with_service(
                        service,
                        folder["id"],
                        recursive=True,
                        max_depth=max_depth - 1,
                        path=folder_path,
                        visited=visited,
                    )
                )
        return files
    except Exception as exc:
        raise GoogleDriveSyncError(str(exc)) from exc


def _local_relative_pdf_path(drive_path: str) -> Path:
    """Map a Drive path to a safe local path under data/pdfs."""
    parts = [part for part in Path(drive_path.replace("\\", "/")).parts if part not in ("", ".", "..")]
    if "pdfs" in parts:
        parts = parts[parts.index("pdfs") + 1 :]
    return Path(*parts) if parts else Path(Path(drive_path).name)


def sync_drive_pdfs(
    folder_id: str | None = None,
    dest_dir: Path = PDF_DIR,
    service_account_info: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Download PDFs from Google Drive into the local PDF folder.

    The local folder is temporary storage on Streamlit Cloud. The app still indexes
    locally into JSONL and never sends full PDFs to Gemini.
    """
    ensure_data_dirs()
    folder_id = get_drive_folder_id(folder_id)
    service = get_drive_service(service_account_info)
    files = _list_drive_pdfs_with_service(service, folder_id, recursive=True, max_depth=5, path="", visited=set())
    downloaded: list[str] = []
    locations: list[dict[str, str]] = []
    warnings: list[str] = []

    for file_info in files:
        file_id = file_info["id"]
        file_name = Path(file_info["name"]).name
        if not file_name.lower().endswith(".pdf"):
            file_name = f"{file_name}.pdf"
        drive_path = file_info.get("drive_path", file_name)
        local_relative_path = _local_relative_pdf_path(drive_path)
        target_path = dest_dir / local_relative_path
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            target_path.write_bytes(buffer.getvalue())
            downloaded.append(str(local_relative_path))
            locations.append({"file": str(local_relative_path), "drive_path": drive_path})
        except Exception as exc:
            warnings.append(f"{file_name}: {exc}")

    return {
        "folder_id": folder_id,
        "available": len(files),
        "downloaded": len(downloaded),
        "files": downloaded,
        "locations": locations,
        "warnings": warnings,
    }
