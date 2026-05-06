from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .drive_storage import (
    GoogleDriveConfigError,
    download_text_file,
    ensure_child_folder,
    find_child,
    get_drive_folder_id,
    get_drive_service,
    upload_text_file,
)
from .utils import CHUNKS_PATH, DRIVE_MANIFEST_PATH, STANDARDS_INDEX_PATH, read_jsonl, write_json, write_jsonl

CACHE_FOLDER_NAME = ".standards_ai_cache"
USER_SETTINGS_FOLDER_NAME = "user_settings"
INDEX_CACHE_FOLDER_NAME = "index_cache"
LEGACY_INDEX_CACHE_FOLDER_NAME = "index"
INDEX_CACHE_FILES = ("chunks.jsonl", "standards_index.json", "drive_manifest.json")
CHUNKS_CACHE_NAMES = ("chunks.jsonl", "chunk.jsonl")
STANDARDS_CACHE_NAMES = ("standards_index.json", "standard_index.json", "standards.json")
DRIVE_MANIFEST_CACHE_NAMES = ("drive_manifest.json", "manifest.json")
INDEX_CACHE_NAME_GROUPS = {
    "chunks": CHUNKS_CACHE_NAMES,
    "standards": STANDARDS_CACHE_NAMES,
    "drive_manifest": DRIVE_MANIFEST_CACHE_NAMES,
}


class CloudStoreError(RuntimeError):
    """Raised when cloud cache/settings storage fails."""


class MissingEncryptionKeyError(CloudStoreError):
    """Raised when encrypted user settings are requested without a key."""


def _read_secret(key: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(key)
        return str(value) if value else None
    except Exception:
        return None


def _get_encryption_key() -> bytes:
    key = os.getenv("APP_ENCRYPTION_KEY") or _read_secret("APP_ENCRYPTION_KEY")
    if not key:
        raise MissingEncryptionKeyError("APP_ENCRYPTION_KEY is missing.")
    return key.encode("utf-8")


def _fernet() -> Fernet:
    try:
        return Fernet(_get_encryption_key())
    except ValueError as exc:
        raise MissingEncryptionKeyError("APP_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def user_settings_filename(email: str) -> str:
    """Create a privacy-preserving settings filename for a user email."""
    digest = hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()
    return f"{digest}.json"


def _cache_folder(service, root_folder_id: str) -> str:
    return ensure_child_folder(service, root_folder_id, CACHE_FOLDER_NAME)


def _settings_folder(service, root_folder_id: str) -> str:
    cache_id = _cache_folder(service, root_folder_id)
    return ensure_child_folder(service, cache_id, USER_SETTINGS_FOLDER_NAME)


def _index_folder(service, root_folder_id: str) -> str:
    cache_id = _cache_folder(service, root_folder_id)
    return ensure_child_folder(service, cache_id, INDEX_CACHE_FOLDER_NAME)


def _find_index_folder(service, root_folder_id: str) -> str | None:
    """Find the nested index cache folder without creating missing folders."""
    cache_folder = find_child(service, root_folder_id, CACHE_FOLDER_NAME)
    if not cache_folder:
        return None
    index_folder = find_child(service, cache_folder["id"], INDEX_CACHE_FOLDER_NAME)
    return index_folder["id"] if index_folder else None


def _list_cache_file_names(service, folder_id: str) -> list[str]:
    """List direct file names in a cache folder for diagnostics and detection."""
    files: list[str] = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(name, mimeType)",
                pageToken=page_token,
                orderBy="name",
                pageSize=1000,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        files.extend(str(item.get("name", "")) for item in response.get("files", []) if item.get("name"))
        page_token = response.get("nextPageToken")
        if not page_token:
            return files


def _find_existing_cache_name(service, folder_id: str, names: tuple[str, ...]) -> str | None:
    """Return the first matching cache filename from a canonical/legacy name list."""
    for name in names:
        if find_child(service, folder_id, name):
            return name
    return None


def _has_cache_group(service, folder_id: str, names: tuple[str, ...]) -> bool:
    return _find_existing_cache_name(service, folder_id, names) is not None


def _download_first_existing_text_file(service, folder_id: str, names: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Download the first available cache file from a canonical/legacy name list."""
    for name in names:
        text = download_text_file(service, folder_id, name)
        if text is not None:
            return name, text
    return None, None


def _parse_json_cache_file(name: str, text: str, default: Any) -> Any:
    """Parse a cache JSON file with a file-specific error message."""
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CloudStoreError(f"{name} is not valid JSON: line {exc.lineno}, column {exc.colno}.") from exc


def _parse_chunks_cache_file(name: str, text: str) -> list[dict[str, Any]]:
    """Parse chunks cache as JSONL, JSON array, or legacy multiline JSONL."""
    text = text.lstrip("\ufeff")
    if not text.strip():
        return []
    if text.lstrip().startswith("["):
        rows = _parse_json_cache_file(name, text, [])
        if not isinstance(rows, list):
            raise CloudStoreError(f"{name} must contain a JSON array or JSONL rows.")
        return [row for row in rows if isinstance(row, dict)]

    rows: list[dict[str, Any]] = []
    buffer = ""
    start_line = 1
    last_error: json.JSONDecodeError | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() and not buffer:
            continue
        if not buffer:
            start_line = line_number
        candidate = raw_line if not buffer else f"{buffer}\\n{raw_line}"
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            buffer = candidate
            last_error = exc
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
        buffer = ""
        start_line = line_number + 1
        last_error = None

    if buffer:
        message = "unknown parse error"
        if last_error:
            message = f"line {start_line}, column {last_error.colno}: {last_error.msg}"
        raise CloudStoreError(f"{name} is not valid JSONL. Last incomplete record starts at {message}.")
    return rows


def _cache_folder_candidates(service, root_folder_id: str) -> list[tuple[str, str]]:
    """Return possible cache folders, preferring the nested managed folder."""
    candidates: list[tuple[str, str]] = []
    try:
        index_folder = _find_index_folder(service, root_folder_id)
    except HttpError as exc:
        if exc.resp.status not in {403, 404}:
            raise
        index_folder = None
    if index_folder:
        candidates.append((index_folder, "nested"))
    legacy_index_folder = find_child(service, root_folder_id, LEGACY_INDEX_CACHE_FOLDER_NAME)
    if legacy_index_folder:
        candidates.append((legacy_index_folder["id"], "index"))
    candidates.append((root_folder_id, "root"))
    return candidates


def _index_folder_for_save(service, root_folder_id: str) -> tuple[str, str]:
    """Return a folder id for saving index cache, falling back to the selected root."""
    if all(_has_cache_group(service, root_folder_id, names) for names in INDEX_CACHE_NAME_GROUPS.values()):
        return root_folder_id, "root"
    try:
        return _index_folder(service, root_folder_id), "nested"
    except HttpError as exc:
        if exc.resp.status in {403, 404}:
            return root_folder_id, "root"
        raise


def _index_folder_for_load(service, root_folder_id: str) -> tuple[str, str]:
    """Return a folder id for loading index cache without requiring create permission."""
    for folder_id, cache_location in _cache_folder_candidates(service, root_folder_id):
        has_chunks = _has_cache_group(service, folder_id, CHUNKS_CACHE_NAMES)
        has_standards = _has_cache_group(service, folder_id, STANDARDS_CACHE_NAMES)
        if has_chunks and has_standards:
            return folder_id, cache_location
    return _cache_folder_candidates(service, root_folder_id)[0]


def _target_cache_name(service, folder_id: str, names: tuple[str, ...]) -> str:
    """Use an existing legacy filename if present, otherwise the canonical first name."""
    return _find_existing_cache_name(service, folder_id, names) or names[0]


def _missing_cache_groups_for_folder(service, folder_id: str) -> list[str]:
    """Return canonical filenames for cache groups with no matching file or alias."""
    missing: list[str] = []
    for names in INDEX_CACHE_NAME_GROUPS.values():
        if not _has_cache_group(service, folder_id, names):
            missing.append(names[0])
    return missing


def _drive_permission_help(exc: HttpError, folder_id: str) -> CloudStoreError:
    """Return a user-actionable error for common Drive permission failures."""
    error_text = str(exc)
    if "storageQuotaExceeded" in error_text or "Service Accounts do not have storage quota" in error_text:
        return CloudStoreError(
            "Google Drive rejected creating a new cache file because service accounts do not have "
            "storage quota in a regular My Drive folder. Use a Shared Drive for the cache folder, "
            "or manually create these files in the selected cache folder first so the app can update "
            "them instead of creating them: chunks.jsonl, standards_index.json, drive_manifest.json."
        )
    if exc.resp.status in {401, 403, 404}:
        return CloudStoreError(
            "Google Drive cache folder is not accessible by the service account. "
            f"Share the Drive folder `{folder_id}` with the service account email as Editor, "
            "or paste that shared folder link into the OCR/index cache folder field. "
            "If the folder is in a Shared Drive, make sure the service account is a member "
            "of that Shared Drive."
        )
    return CloudStoreError(str(exc))


def diagnose_index_cache_folder(folder_id: str | None = None, service_account_info: Any = None, write_test: bool = False) -> dict[str, Any]:
    """Return Drive API capabilities for the selected cache folder."""
    root_folder_id = ""
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        folder = (
            service.files()
            .get(
                fileId=root_folder_id,
                fields=(
                    "id,name,mimeType,driveId,capabilities(canAddChildren,canEdit,"
                    "canListChildren,canDeleteChildren,canShare)"
                ),
                supportsAllDrives=True,
            )
            .execute()
        )
        result: dict[str, Any] = {
            "folder_id": root_folder_id,
            "name": folder.get("name", ""),
            "mimeType": folder.get("mimeType", ""),
            "driveId": folder.get("driveId", ""),
            "capabilities": folder.get("capabilities", {}),
        }
        if write_test:
            test_name = ".standards_ai_write_test.txt"
            try:
                media = MediaIoBaseUpload(io.BytesIO(b"ok"), mimetype="text/plain", resumable=False)
                created = (
                    service.files()
                    .create(
                        body={"name": test_name, "parents": [root_folder_id], "mimeType": "text/plain"},
                        media_body=media,
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
                test_id = created["id"]
                result["write_test"] = "ok"
                result["write_test_file_id"] = test_id
                try:
                    service.files().delete(fileId=test_id, supportsAllDrives=True).execute()
                    result["delete_test"] = "ok"
                except HttpError as exc:
                    result["delete_test"] = f"failed: {exc}"
            except HttpError as exc:
                result["write_test"] = "failed"
                result["write_error_status"] = exc.resp.status
                result["write_error_reason"] = str(exc)
                existing_manifest = download_text_file(service, root_folder_id, "drive_manifest.json")
                if existing_manifest is None:
                    result["existing_file_update_test"] = "skipped: drive_manifest.json not found"
                else:
                    try:
                        upload_text_file(
                            service,
                            root_folder_id,
                            "drive_manifest.json",
                            existing_manifest,
                            mime_type="application/json",
                        )
                        result["existing_file_update_test"] = "ok"
                    except HttpError as update_exc:
                        result["existing_file_update_test"] = "failed"
                        result["existing_file_update_error_status"] = update_exc.resp.status
                        result["existing_file_update_error_reason"] = str(update_exc)
        return result
    except HttpError as exc:
        raise _drive_permission_help(exc, root_folder_id) from exc
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc


def save_user_settings(email: str, settings: dict[str, Any], folder_id: str | None = None, service_account_info: Any = None) -> None:
    """Encrypt and save per-user defaults in Google Drive."""
    if not email:
        raise CloudStoreError("User email is required.")
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        settings_folder = _settings_folder(service, root_folder_id)
        payload = json.dumps(settings, ensure_ascii=False)
        encrypted = _fernet().encrypt(payload.encode("utf-8")).decode("utf-8")
        upload_text_file(service, settings_folder, user_settings_filename(email), encrypted, mime_type="text/plain")
    except (GoogleDriveConfigError, MissingEncryptionKeyError):
        raise
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc


def load_user_settings(email: str, folder_id: str | None = None, service_account_info: Any = None) -> dict[str, Any] | None:
    """Load and decrypt per-user defaults from Google Drive."""
    if not email:
        raise CloudStoreError("User email is required.")
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        settings_folder = _settings_folder(service, root_folder_id)
        encrypted = download_text_file(service, settings_folder, user_settings_filename(email))
        if not encrypted:
            return None
        decrypted = _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
        return json.loads(decrypted)
    except InvalidToken as exc:
        raise CloudStoreError("Saved settings could not be decrypted with the current APP_ENCRYPTION_KEY.") from exc
    except (GoogleDriveConfigError, MissingEncryptionKeyError):
        raise
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc


def save_index_cache(folder_id: str | None = None, service_account_info: Any = None) -> dict[str, Any]:
    """Save local OCR/search index files to Google Drive as a lightweight cloud database."""
    root_folder_id = ""
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        index_folder, cache_location = _index_folder_for_save(service, root_folder_id)
        missing_files = _missing_cache_groups_for_folder(service, index_folder)
        if cache_location == "root" and missing_files:
            raise CloudStoreError(
                "The selected cache folder is a regular My Drive folder. Service accounts cannot "
                "create new files there. Create these files first, then retry: "
                + ", ".join(missing_files)
            )
        chunks_text = CHUNKS_PATH.read_text(encoding="utf-8") if CHUNKS_PATH.exists() else ""
        standards_text = STANDARDS_INDEX_PATH.read_text(encoding="utf-8") if STANDARDS_INDEX_PATH.exists() else "[]"
        drive_manifest_text = DRIVE_MANIFEST_PATH.read_text(encoding="utf-8") if DRIVE_MANIFEST_PATH.exists() else "[]"
        chunks_name = _target_cache_name(service, index_folder, CHUNKS_CACHE_NAMES)
        standards_name = _target_cache_name(service, index_folder, STANDARDS_CACHE_NAMES)
        manifest_name = _target_cache_name(service, index_folder, DRIVE_MANIFEST_CACHE_NAMES)
        upload_text_file(service, index_folder, chunks_name, chunks_text, mime_type="application/jsonl")
        upload_text_file(service, index_folder, standards_name, standards_text, mime_type="application/json")
        upload_text_file(service, index_folder, manifest_name, drive_manifest_text, mime_type="application/json")
        return {
            "chunks": len(read_jsonl(CHUNKS_PATH)),
            "standards": len(json.loads(standards_text)),
            "cache_location": cache_location,
            "cache_files": [chunks_name, standards_name, manifest_name],
        }
    except HttpError as exc:
        raise _drive_permission_help(exc, root_folder_id) from exc
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc


def load_index_cache(folder_id: str | None = None, service_account_info: Any = None) -> dict[str, Any]:
    """Load cached OCR/search index files from Google Drive into local JSONL/JSON."""
    root_folder_id = ""
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        index_folder, cache_location = _index_folder_for_load(service, root_folder_id)
        chunks_name, chunks_text = _download_first_existing_text_file(service, index_folder, CHUNKS_CACHE_NAMES)
        standards_name, standards_text = _download_first_existing_text_file(service, index_folder, STANDARDS_CACHE_NAMES)
        manifest_name, drive_manifest_text = _download_first_existing_text_file(service, index_folder, DRIVE_MANIFEST_CACHE_NAMES)
        if chunks_text is None or standards_text is None:
            discovered: list[str] = []
            for candidate_folder, candidate_location in _cache_folder_candidates(service, root_folder_id):
                names = _list_cache_file_names(service, candidate_folder)
                if names:
                    discovered.append(f"{candidate_location}: {', '.join(names)}")
            detail = f" Detected files: {' | '.join(discovered)}." if discovered else ""
            raise CloudStoreError(
                "No saved index cache found in Google Drive. Expected chunks.jsonl or chunk.jsonl, "
                "plus standards_index.json."
                + detail
            )
        rows = _parse_chunks_cache_file(chunks_name or "chunks.jsonl", chunks_text)
        standards = _parse_json_cache_file(standards_name or "standards_index.json", standards_text, [])
        drive_manifest = _parse_json_cache_file(manifest_name or "drive_manifest.json", drive_manifest_text or "[]", [])
        write_jsonl(CHUNKS_PATH, rows)
        write_json(STANDARDS_INDEX_PATH, standards)
        write_json(DRIVE_MANIFEST_PATH, drive_manifest)
        return {
            "chunks": len(rows),
            "standards": len(standards),
            "cache_location": cache_location,
            "cache_files": [name for name in (chunks_name, standards_name, manifest_name) if name],
        }
    except CloudStoreError:
        raise
    except HttpError as exc:
        raise _drive_permission_help(exc, root_folder_id) from exc
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc
