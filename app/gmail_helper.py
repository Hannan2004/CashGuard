import json
import os

from langchain_google_community import GmailToolKit
from langchain_google_community.gmail.utils import build_resource_service

def _build_toolkit() -> GmailToolKit:
    credentials_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
    token_path = os.environ.get("GMAIL_TOKEN_PATH", "token.json")

    api_resource = build_resource_service(
        credentials_path=credentials_path,
        token_path=token_path,
    )

    return GmailToolKit(api_resource=api_resource)

def get_latest_unread_email(label: str) -> str | None:
    toolkit = _build_toolkit()
    tools = toolkit.get_tools()

    search_tool = next(
        (t for t in tools if "search" in t.name.lower()),
        None,
    )

    if search_tool is None:
        raise RuntimeError(
            "GmailSearch tool not found in toolkit. "
            "Check your langchain-google-community installation."
        )
    
    query = f"label:{label} is:unread"
    raw_results = search_tool.run(query)

    messages = json.loads(raw_results)

    if not messages:
        return None
    
    latest = messages[0]
    return latest.get("body") or latest.get("snippet")