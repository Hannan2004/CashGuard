"""
scripts/drive_auth.py
=====================
Run this ONCE on your local machine to authorise CashGuard to read your
Google Drive. It opens a browser, asks you to approve access, then saves
a refresh token to `oauth_token.json` in the project root.

From that point on, drive_client.py silently refreshes the token as needed —
you never need to run this again unless you revoke access or the token file
is deleted.

Usage
-----
  python scripts/drive_auth.py

Prerequisites
-------------
  1. Go to Google Cloud Console → APIs & Services → Credentials
  2. Create an OAuth 2.0 Client ID (Desktop app type)
  3. Download the JSON and save it as  oauth_credentials.json  in the
     project root  (or set GDRIVE_OAUTH_CREDS_FILE env var to its path)
  4. Enable the Google Drive API in your project
"""

import os
import sys
from pathlib import Path

# Allow running from the project root or from the scripts/ subfolder
sys.path.insert(0, str(Path(__file__).parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

CREDS_FILE = os.environ.get("GDRIVE_OAUTH_CREDS_FILE", "oauth_credentials.json")
TOKEN_FILE  = os.environ.get("GDRIVE_OAUTH_TOKEN_FILE", "oauth_token.json")


def main():
    creds = None

    # If a token already exists and is still valid, we're done
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.valid:
            print(f"✅  Token is already valid — nothing to do ({TOKEN_FILE})")
            return

        # Expired but refreshable
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            Path(TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
            print(f"✅  Token refreshed and saved to {TOKEN_FILE}")
            return

    # No valid token — run the full browser flow
    if not Path(CREDS_FILE).exists():
        print(
            f"❌  Client secrets file not found: {CREDS_FILE}\n"
            "    Download it from Google Cloud Console:\n"
            "    APIs & Services → Credentials → your OAuth 2.0 Client ID → Download JSON\n"
            f"    Save it as  {CREDS_FILE}  in the project root."
        )
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    Path(TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
    print(f"\n✅  Authorisation complete! Token saved to  {TOKEN_FILE}")
    print(    "    Add this file to .gitignore — it contains your refresh token.")


if __name__ == "__main__":
    main()