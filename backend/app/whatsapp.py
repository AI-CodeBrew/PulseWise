"""
Sending a WhatsApp message through Meta's WhatsApp Business Cloud API.

We only ever send TEMPLATE messages: WhatsApp only allows a business to start a conversation with an approved
template. You create the template once in Meta's WhatsApp Manager (the exact text is in docs/ROADMAP.md, Phase 10).

Needs two secrets in backend/.env (from your Meta developer app, WhatsApp > API setup):
    WHATSAPP_ACCESS_TOKEN       a permanent (system user) access token
    WHATSAPP_PHONE_NUMBER_ID    the id of the sending phone number (NOT the phone number itself)

IMPORTANT: written from Meta's documentation but NOT run against a real WhatsApp account (we have none to test with).
The tests use a pretend Meta. Send yourself a test report first (Admin -> website -> "Weekly report").
"""

import logging
import re
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class WhatsAppError(Exception):
    """Sending failed. The message is for admins / logs, never for clients."""


def whatsapp_configured() -> bool:
    return bool(settings.whatsapp_access_token and settings.whatsapp_phone_number_id)


def normalize_number(raw: str) -> str | None:
    """"+92 300-1234567" -> "923001234567". Must be in international form (a country code, 8 to 15 digits). None = not usable."""
    text = raw.strip()
    digits = re.sub(r"[\s\-().]", "", text)
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):  # a local number like 0300...: we can't know the country, so it is refused
        return None
    if not re.fullmatch(r"[1-9]\d{7,14}", digits):
        return None
    return digits


def clean_param(text: str, limit: int = 400) -> str:
    """Template variables may not contain new lines, tabs or runs of spaces (WhatsApp rejects them)."""
    return re.sub(r"\s+", " ", text).strip()[:limit] or "-"


def _send(url: str, headers: dict[str, str], payload: dict[str, Any]) -> httpx.Response:
    """The one place that really sends HTTP (tests replace it with a pretend Meta)."""
    return httpx.post(url, headers=headers, json=payload, timeout=TIMEOUT, follow_redirects=False)


def send_template(to: str, template: str, language: str, params: list[str], *, api_version: str) -> str:
    """Send an approved template with its {{1}}, {{2}}... filled in. Returns WhatsApp's message id."""
    if not whatsapp_configured():
        raise WhatsAppError("WhatsApp isn't set up (WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID are missing).")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", api_version):
        raise WhatsAppError("The WhatsApp API version setting looks wrong.")
    url = f"https://graph.facebook.com/{api_version}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": clean_param(p)} for p in params]}],
        },
    }
    try:
        response = _send(url, {"Authorization": f"Bearer {settings.whatsapp_access_token}", "Content-Type": "application/json"}, payload)
    except httpx.HTTPError as exc:
        raise WhatsAppError(f"Couldn't reach WhatsApp ({type(exc).__name__}).") from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200:
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}  # (an unexpected shape must not crash the report job)
        raise WhatsAppError(f"WhatsApp refused the message (HTTP {response.status_code}, code {error.get('code', '?')}): {str(error.get('message', 'no details'))[:300]}")
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict) or not messages[0].get("id"):
        raise WhatsAppError("WhatsApp answered without a message id, so we can't be sure it was sent.")
    return str(messages[0]["id"])
