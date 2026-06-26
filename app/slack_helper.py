from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_SLACK_API_URL = "https://slack.com/api/chat.postMessage"


def _get_config() -> tuple[str, str] | tuple[None, None]:
    """Return (bot_token, channel). Returns (None, None) if not configured."""
    token   = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    channel = os.environ.get("SLACK_APPROVALS_CHANNEL", "").strip()

    if not token or not channel:
        logger.warning(
            "Slack not configured: set SLACK_BOT_TOKEN and "
            "SLACK_APPROVALS_CHANNEL env vars to enable notifications."
        )
        return None, None

    return token, channel


def _get_base_url() -> str:
    """
    Resolve the public-facing base URL of this API.

    Priority:
      1. CASHGUARD_BASE_URL env var  — set this in Docker / UiPath deployment
      2. Fallback to localhost:8000  — works for local dev
    """
    return os.environ.get("CASHGUARD_BASE_URL", "http://localhost:8000").rstrip("/")


def _build_api_commands(base_url: str, order_id: str) -> str:
    """
    Build approve/reject API commands for the Slack message.

    Includes both PowerShell (Windows) and curl (Mac/Linux) versions
    so the message works for any reviewer regardless of OS.
    """
    approve_url = f"{base_url}/cases/{order_id}/approve"
    reject_url  = f"{base_url}/cases/{order_id}/reject"

    approve_body = '{"approved_by": "your.name@company.com", "comments": "Approved after review"}'
    reject_body  = '{"approved_by": "your.name@company.com", "comments": "Rejected — reason here"}'

    # PowerShell (works on Windows, also available on Mac/Linux)
    ps_approve = (
        f'Invoke-RestMethod -Method POST -Uri "{approve_url}" '
        f'-ContentType "application/json" '
        f"-Body '{approve_body}'"
    )
    ps_reject = (
        f'Invoke-RestMethod -Method POST -Uri "{reject_url}" '
        f'-ContentType "application/json" '
        f"-Body '{reject_body}'"
    )

    # curl (Mac / Linux / Git Bash on Windows)
    curl_approve = (
        f"curl -X POST {approve_url} \\\n"
        f'  -H "Content-Type: application/json" \\\n'
        f'  -d \'{approve_body}\''
    )
    curl_reject = (
        f"curl -X POST {reject_url} \\\n"
        f'  -H "Content-Type: application/json" \\\n'
        f'  -d \'{reject_body}\''
    )

    return (
        f"*Approve — PowerShell (Windows):*\n```{ps_approve}```\n"
        f"*Approve — curl (Mac/Linux/Git Bash):*\n```{curl_approve}```\n\n"
        f"*Reject — PowerShell (Windows):*\n```{ps_reject}```\n"
        f"*Reject — curl (Mac/Linux/Git Bash):*\n```{curl_reject}```"
    )


def post_human_review_alert(
    order_id: str,
    customer_name: str,
    order_total: float,
    risk_level: str | None,
    risk_summary: str,
) -> bool:
    """
    Post a human-review required alert to the configured Slack channel.

    Returns True if the message was sent successfully, False otherwise.
    Failures are logged as warnings — they never crash the pipeline.
    """
    token, channel = _get_config()
    if not token:
        return False

    base_url = _get_base_url()

    risk_emoji = {
        "high":   ":red_circle:",
        "medium": ":large_yellow_circle:",
        "low":    ":large_green_circle:",
    }.get((risk_level or "").lower(), ":white_circle:")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":rotating_light: CashGuard — Human Review Required",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Case ID:*\n`{order_id}`"},
                {"type": "mrkdwn", "text": f"*Customer:*\n{customer_name}"},
                {"type": "mrkdwn", "text": f"*Order Total:*\n${order_total:,.2f}"},
                {"type": "mrkdwn", "text": f"*Risk Level:*\n{risk_emoji} {(risk_level or 'unknown').upper()}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Risk Summary:*\n{risk_summary}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": _build_api_commands(base_url, order_id),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Full case state: `GET {base_url}/cases/{order_id}/state`"
                        f" · Audit trail: `GET {base_url}/audit?case_id={order_id}`"
                    ),
                }
            ],
        },
    ]

    payload = {
        "channel": channel,
        "text": f"[CashGuard] Human review required for {order_id} ({customer_name})",
        "blocks": blocks,
    }

    try:
        resp = requests.post(
            _SLACK_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=5,
        )
        data = resp.json()

        if not data.get("ok"):
            logger.warning("Slack API error for %s: %s", order_id, data.get("error"))
            return False

        logger.info("Slack alert sent for %s → ts=%s", order_id, data.get("ts"))
        return True

    except Exception as exc:
        logger.warning("Slack notification failed for %s: %s", order_id, exc)
        return False