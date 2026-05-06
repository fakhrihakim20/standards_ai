from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from googleapiclient.errors import HttpError

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


def _index_folder_for_save(service, root_folder_id: str) -> tuple[str, str]:
    """Return a folder id for saving index cache, falling back to the selected root."""
    try:
        return _index_folder(service, root_folder_id), "nested"
    except HttpError as exc:
        if exc.resp.status in {403, 404}:
            return root_folder_id, "root"
        raise


def _index_folder_for_load(service, root_folder_id: str) -> tuple[str, str]:
    """Return a folder id for loading index cache without requiring create permission."""
    try:
        index_folder = _find_index_folder(service, root_folder_id)
    except HttpError as exc:
        if exc.resp.status not in {403, 404}:
            raise
        index_folder = None
    return (index_folder, "nested") if index_folder else (root_folder_id, "root")


def _drive_permission_help(exc: HttpError, folder_id: str) -> CloudStoreError:
    """Return a user-actionable error for common Drive permission failures."""
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
            test_id = upload_text_file(service, root_folder_id, test_name, "ok", mime_type="text/plain")
            result["write_test"] = "ok"
            result["write_test_file_id"] = test_id
            try:
                service.files().delete(fileId=test_id, supportsAllDrives=True).execute()
                result["delete_test"] = "ok"
            except HttpError as exc:
                result["delete_test"] = f"failed: {exc}"
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


def save_index_cache(folder_id: str | None = None, service_account_info: Any = None) -> dict[str, int]:
    """Save local OCR/search index files to Google Drive as a lightweight cloud database."""
    root_folder_id = ""
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        index_folder, cache_location = _index_folder_for_save(service, root_folder_id)
        chunks_text = CHUNKS_PATH.read_text(encoding="utf-8") if CHUNKS_PATH.exists() else ""
        standards_text = STANDARDS_INDEX_PATH.read_text(encoding="utf-8") if STANDARDS_INDEX_PATH.exists() else "[]"
        drive_manifest_text = DRIVE_MANIFEST_PATH.read_text(encoding="utf-8") if DRIVE_MANIFEST_PATH.exists() else "[]"
        upload_text_file(service, index_folder, "chunks.jsonl", chunks_text, mime_type="application/jsonl")
        upload_text_file(service, index_folder, "standards_index.json", standards_text, mime_type="application/json")
        upload_text_file(service, index_folder, "drive_manifest.json", drive_manifest_text, mime_type="application/json")
        return {"chunks": len(read_jsonl(CHUNKS_PATH)), "standards": len(json.loads(standards_text)), "cache_location": cache_location}
    except HttpError as exc:
        raise _drive_permission_help(exc, root_folder_id) from exc
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc


def load_index_cache(folder_id: str | None = None, service_account_info: Any = None) -> dict[str, int]:
    """Load cached OCR/search index files from Google Drive into local JSONL/JSON."""
    root_folder_id = ""
    try:
        service = get_drive_service(service_account_info)
        root_folder_id = get_drive_folder_id(folder_id)
        index_folder, cache_location = _index_folder_for_load(service, root_folder_id)
        chunks_text = download_text_file(service, index_folder, "chunks.jsonl")
        standards_text = download_text_file(service, index_folder, "standards_index.json")
        drive_manifest_text = download_text_file(service, index_folder, "drive_manifest.json")
        if chunks_text is None or standards_text is None:
            raise CloudStoreError("No saved index cache found in Google Drive.")
        rows = [json.loads(line) for line in chunks_text.splitlines() if line.strip()]
        standards = json.loads(standards_text)
        write_jsonl(CHUNKS_PATH, rows)
        write_json(STANDARDS_INDEX_PATH, standards)
        write_json(DRIVE_MANIFEST_PATH, json.loads(drive_manifest_text or "[]"))
        return {"chunks": len(rows), "standards": len(standards), "cache_location": cache_location}
    except CloudStoreError:
        raise
    except HttpError as exc:
        raise _drive_permission_help(exc, root_folder_id) from exc
    except Exception as exc:
        raise CloudStoreError(str(exc)) from exc
