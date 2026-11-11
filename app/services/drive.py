"""Upload/update scrape artifacts on Google Drive (service account)."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from app.config import (
    DRIVE_FOLDER_ID,
    DRIVE_SYNC_ENABLED,
    GOOGLE_DRIVE_CREDENTIALS,
    MAIN_SHEET,
    OPTIONS_FILE,
    OUTPUT_FILE,
)

_SCOPES = ("https://www.googleapis.com/auth/drive",)
_service: Any | None = None
_file_id_cache: dict[str, str] = {}


def drive_configured() -> bool:
    return bool(
        DRIVE_SYNC_ENABLED
        and DRIVE_FOLDER_ID
        and GOOGLE_DRIVE_CREDENTIALS
        and Path(GOOGLE_DRIVE_CREDENTIALS).is_file()
    )


def _build_service():
    global _service
    if _service is not None:
        return _service

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(GOOGLE_DRIVE_CREDENTIALS),
        scopes=_SCOPES,
    )
    _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    if path.suffix.lower() == ".json":
        return "application/json"
    if path.suffix.lower() == ".csv":
        return "text/csv"
    return "application/octet-stream"


def _find_file_id(service, name: str, folder_id: str) -> str | None:
    cached = _file_id_cache.get(name)
    if cached:
        return cached

    safe_name = name.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' and '{folder_id}' in parents "
        f"and trashed = false"
    )
    response = (
        service.files()
        .list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=5,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = response.get("files") or []
    if not files:
        return None
    file_id = files[0]["id"]
    _file_id_cache[name] = file_id
    return file_id


def upload_or_update_file(
    local_path: Path,
    *,
    remote_name: str | None = None,
    folder_id: str | None = None,
) -> str | None:
    """
    Create or overwrite a file in the Drive folder.
    Returns the Drive file id, or None if sync is disabled / failed softly.
    """
    if not drive_configured():
        return None

    path = Path(local_path)
    if not path.is_file():
        print(f"[drive] skip missing file: {path}")
        return None

    name = remote_name or path.name
    target_folder = folder_id or DRIVE_FOLDER_ID
    mime = _mime_for(path)

    try:
        from googleapiclient.http import MediaFileUpload

        service = _build_service()
        media = MediaFileUpload(str(path), mimetype=mime, resumable=True)
        existing_id = _find_file_id(service, name, target_folder)

        if existing_id:
            updated = (
                service.files()
                .update(
                    fileId=existing_id,
                    media_body=media,
                    fields="id, name",
                    supportsAllDrives=True,
                )
                .execute()
            )
            file_id = updated["id"]
            print(f"[drive] updated {name} ({file_id})")
        else:
            created = (
                service.files()
                .create(
                    body={"name": name, "parents": [target_folder]},
                    media_body=media,
                    fields="id, name",
                    supportsAllDrives=True,
                )
                .execute()
            )
            file_id = created["id"]
            _file_id_cache[name] = file_id
            print(f"[drive] created {name} ({file_id})")
        return file_id
    except Exception as e:
        # Never break scraping because Drive upload failed.
        print(f"[drive] failed to sync {name}: {type(e).__name__}: {e}")
        return None


def sync_scrape_artifacts(
    *,
    output: Path | None = None,
    sheet: Path | None = None,
    options: Path | None = None,
) -> None:
    """Push the three main artifacts after a local save."""
    if not DRIVE_SYNC_ENABLED:
        return
    if not drive_configured():
        print(
            "[drive] sync enabled but not configured. Set "
            "GOOGLE_DRIVE_CREDENTIALS and GOOGLE_DRIVE_FOLDER_ID in .env, "
            "and share the Drive folder with the service account."
        )
        return

    upload_or_update_file(Path(output or OUTPUT_FILE), remote_name="output.json")
    upload_or_update_file(Path(sheet or MAIN_SHEET), remote_name="zehitomo_main.csv")
    upload_or_update_file(
        Path(options or OPTIONS_FILE),
        remote_name="options.json",
    )
