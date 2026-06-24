"""
drive_client.py
===============
Thin wrapper around the Google Drive REST API.

Authentication strategy (checked in order):
  1. Service Account — if GDRIVE_SERVICE_ACCOUNT_JSON env var points to a
     valid service account key file, we use that. This is the recommended
     approach for server-side automation.

  2. OAuth2 (installed-app flow) — if oauth_credentials.json exists in the
     project root (generated once via `python scripts/drive_auth.py`), we
     use the stored token. Useful for local development.

  3. Application Default Credentials — fallback for Cloud Run / GCP VMs.

Environment variables
---------------------
GDRIVE_SERVICE_ACCOUNT_JSON  Path to the service account key JSON file.
                              e.g.  /secrets/cashguard-sa.json
GDRIVE_CONTRACTS_FOLDER_ID   Google Drive folder ID that contains contract PDFs.
                              Find it in the folder URL after /folders/
GDRIVE_OAUTH_TOKEN_FILE      Path to the stored OAuth2 token (default: oauth_token.json)
GDRIVE_OAUTH_CREDS_FILE      Path to the OAuth2 client secrets file
                              (default: oauth_credentials.json)
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Optional

# Google API client libraries
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def _get_credentials():
    """
    Return Google API credentials using the best available method.
    Raises RuntimeError if no credentials can be found.
    """
    # ── Strategy 1: Service Account key file ──────────────────────────────
    sa_key_path = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
    if sa_key_path and Path(sa_key_path).exists():
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            sa_key_path, scopes=SCOPES
        )
        return creds

    # ── Strategy 2: OAuth2 stored token ───────────────────────────────────
    token_file = os.environ.get("GDRIVE_OAUTH_TOKEN_FILE", "oauth_token.json")
    creds_file = os.environ.get("GDRIVE_OAUTH_CREDS_FILE", "oauth_credentials.json")

    if Path(token_file).exists():
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Persist the refreshed token
            Path(token_file).write_text(creds.to_json(), encoding="utf-8")

        if creds and creds.valid:
            return creds

    # ── Strategy 3: Application Default Credentials (GCP) ─────────────────
    try:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES)
        return creds
    except Exception:
        pass

    raise RuntimeError(
        "No Google credentials found.\n"
        "Set one of:\n"
        "  • GDRIVE_SERVICE_ACCOUNT_JSON pointing to a service account key file\n"
        "  • Run `python scripts/drive_auth.py` to create oauth_token.json\n"
        "  • Set up Application Default Credentials (gcloud auth application-default login)"
    )


def _build_drive_service():
    """Build and return an authenticated Google Drive API service object."""
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def list_contract_files(folder_id: str) -> list[dict]:
    """
    List all PDF files in the given Drive folder.
    Returns a list of dicts: [{"id": ..., "name": ...}, ...]
    """
    service = _build_drive_service()
    query   = (
        f"'{folder_id}' in parents "
        f"and mimeType = 'application/pdf' "
        f"and trashed = false"
    )

    results = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=100)
        .execute()
    )
    return results.get("files", [])


def fetch_contract_pdf_bytes(filename: str) -> Optional[bytes]:
    """
    Search for `filename` inside GDRIVE_CONTRACTS_FOLDER_ID and return
    its raw bytes, or None if not found.

    Args:
        filename: e.g. "CUST-2002-SKU-MONITOR-27.pdf"

    Returns:
        PDF content as bytes, or None if the file does not exist.
    """
    folder_id = os.environ.get("GDRIVE_CONTRACTS_FOLDER_ID")
    if not folder_id:
        raise RuntimeError(
            "GDRIVE_CONTRACTS_FOLDER_ID is not set. "
            "Add it to your .env file — it's the ID from the Drive folder URL."
        )

    service = _build_drive_service()

    # Search for the exact filename within the folder
    query = (
        f"'{folder_id}' in parents "
        f"and name = '{filename}' "
        f"and mimeType = 'application/pdf' "
        f"and trashed = false"
    )

    results = (
        service.files()
        .list(q=query, fields="files(id, name)", pageSize=5)
        .execute()
    )
    files = results.get("files", [])

    if not files:
        return None  # File not found — caller handles the None case

    file_id = files[0]["id"]

    # Download the file content into memory
    buffer   = io.BytesIO()
    request  = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue()


def upload_pdf_to_folder(local_path: str, folder_id: str) -> dict:
    """
    Upload a local PDF file into a Drive folder.
    Returns the Drive file metadata dict.

    Utility function used by `scripts/upload_contracts.py`.
    """
    from googleapiclient.http import MediaFileUpload

    service  = _build_drive_service()
    filename = Path(local_path).name

    file_metadata = {
        "name":    filename,
        "parents": [folder_id],
    }
    media = MediaFileUpload(local_path, mimetype="application/pdf", resumable=True)

    created = (
        service.files()
        .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
        .execute()
    )
    return created