from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from .utils import DRIVE_MANIFEST_PATH, PDF_DIR, ensure_data_dirs, read_json

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
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
            scopes=[DRIVE_SCOPE],
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


def find_child(service, parent_id: str, name: str, mime_type: str | None = None) -> dict[str, str] | None:
    """Find a direct child by exact name."""
    mime_clause = f" and mimeType = '{mime_type}'" if mime_type else ""
    escaped_name = name.replace("'", "\\'")
    query = f"'{parent_id}' in parents and name = '{escaped_name}' and trashed = false{mime_clause}"
    response = service.files().list(q=query, fields="files(id, name, mimeType)", pageSize=1).execute()
    files = response.get("files", [])
    return files[0] if files else None


def ensure_child_folder(service, parent_id: str, name: str) -> str:
    """Create or return a child folder under a Drive parent."""
    existing = find_child(service, parent_id, name, FOLDER_MIME_TYPE)
    if existing:
        return existing["id"]
    metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]}
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_text_file(service, parent_id: str, name: str, content: str, mime_type: str = "application/json") -> str:
    """Create or replace a UTF-8 text file in Google Drive."""
    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype=mime_type, resumable=False)
    existing = find_child(service, parent_id, name)
    if existing:
        updated = service.files().update(fileId=existing["id"], media_body=media, fields="id").execute()
        return updated["id"]
    metadata = {"name": name, "parents": [parent_id], "mimeType": mime_type}
    created = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return created["id"]


def download_text_file(service, parent_id: str, name: str) -> str | None:
    """Download a UTF-8 text file from Google Drive."""
    existing = find_child(service, parent_id, name)
    if not existing:
        return None
    request = service.files().get_media(fileId=existing["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8")


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

        children = _list_drive_children(service, folder_id)
        files = [item for item in children if item.get("mimeType") == "application/pdf"]
        for file_info in files:
            file_info["drive_path"] = f"{path}/{file_info['name']}".strip("/")
        if recursive and max_depth > 0:
            folders = [item for item in children if item.get("mimeType") == FOLDER_MIME_TYPE]
            shortcuts = [
                item
                for item in children
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


def _manifest_by_file_id() -> dict[str, dict[str, Any]]:
    """Return previous Drive manifest entries keyed by Drive file id."""
    entries = read_json(DRIVE_MANIFEST_PATH, [])
    if not isinstance(entries, list):
        return {}
    return {
        str(entry.get("drive_file_id")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("drive_file_id")
    }


def _file_is_unchanged(target_path: Path, file_info: dict[str, str], previous: dict[str, Any] | None) -> bool:
    """Return whether a local PDF already matches Drive metadata from the last sync."""
    if not previous or not target_path.exists():
        return False
    if str(previous.get("modifiedTime") or "") != str(file_info.get("modifiedTime") or ""):
        return False
    if str(previous.get("size") or "") != str(file_info.get("size") or ""):
        return False
    expected_size = file_info.get("size")
    if expected_size and target_path.stat().st_size != int(expected_size):
        return False
    return True


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
    previous_manifest = _manifest_by_file_id()
    downloaded: list[str] = []
    skipped: list[str] = []
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
        location = {
            "file": str(local_relative_path).replace("\\", "/"),
            "drive_path": drive_path,
            "drive_file_id": file_id,
            "drive_web_url": f"https://drive.google.com/file/d/{file_id}/view",
            "modifiedTime": file_info.get("modifiedTime", ""),
            "size": file_info.get("size", ""),
        }
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if _file_is_unchanged(target_path, file_info, previous_manifest.get(file_id)):
                skipped.append(str(local_relative_path))
                locations.append(location)
                continue
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            target_path.write_bytes(buffer.getvalue())
            downloaded.append(str(local_relative_path))
            locations.append(location)
        except Exception as exc:
            warnings.append(f"{file_name}: {exc}")

    return {
        "folder_id": folder_id,
        "available": len(files),
        "downloaded": len(downloaded),
        "skipped": len(skipped),
        "files": downloaded,
        "skipped_files": skipped,
        "locations": locations,
        "warnings": warnings,
    }
