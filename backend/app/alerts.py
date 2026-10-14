"""
Alerts: things an admin should look at (tracking stopped, PostHog errors, failed jobs, ...).

There is at most one OPEN alert per `dedupe_key`; if the same problem happens again the existing alert just
counts up. New alerts are emailed to the admins (once email sending is configured).
"""

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import parse_uuid
from app.config import WebsiteConfig, settings
from app.db import get_sessionmaker
from app.emailer import send_email
from app.models import Alert, User, Website, utcnow
from app.settings_store import get_setting

log = logging.getLogger(__name__)


def raise_alert(
    db: Session,
    *,
    kind: str,
    dedupe_key: str,
    message: str,
    severity: str = "warning",
    website_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> tuple[Alert, bool]:
    """Open an alert, or bump the existing open one. Returns (alert, created). Commits."""
    for _attempt in range(2):
        existing = db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.status == "open"))
        if existing is not None:
            existing.occurrences += 1
            existing.last_seen_at = utcnow()
            existing.message = message  # keep the latest wording
            existing.severity = severity  # ...and the latest severity (a problem can get worse)
            if details:
                existing.details = details
            db.commit()
            return existing, False
        alert = Alert(
            kind=kind, dedupe_key=dedupe_key, message=message, severity=severity,
            website_id=website_id, client_id=client_id, details=details,
        )
        db.add(alert)
        try:
            db.commit()
            return alert, True
        except IntegrityError:  # two workers opened the same alert at the same moment: use the other one
            db.rollback()
    raise RuntimeError(f"could not open alert {dedupe_key}")


def resolve_alerts(db: Session, *, dedupe_key: str | None = None, dedupe_prefix: str | None = None, website_id: uuid.UUID | None = None, kind: str | None = None) -> int:
    """Close matching open alerts. Returns how many. Commits."""
    query = update(Alert).where(Alert.status == "open")
    if dedupe_key is not None:
        query = query.where(Alert.dedupe_key == dedupe_key)
    if dedupe_prefix is not None:
        query = query.where(Alert.dedupe_key.startswith(dedupe_prefix, autoescape=True))
    if website_id is not None:
        query = query.where(Alert.website_id == website_id)
    if kind is not None:
        query = query.where(Alert.kind == kind)
    result = db.execute(query.values(status="resolved", resolved_at=utcnow()))
    db.commit()
    return result.rowcount or 0


def notify_admins(alert: Alert, recipients_extra: str = "") -> None:
    """Email a NEW alert to the admins. Never raises (email problems must not break anything)."""
    try:
        with get_sessionmaker()() as db:
            emails = [u.email for u in db.scalars(select(User).where(User.is_admin.is_(True), User.is_active.is_(True)))]
        emails += [e.strip() for e in recipients_extra.split(",") if e.strip()]
        for email in dict.fromkeys(emails):  # no duplicates, keep order
            send_email(
                email,
                f"[{alert.severity.upper()}] {alert.message[:90]}",
                f"{alert.message}\n\nOpen the alerts page: {settings.frontend_url}/admin/alerts\n",
            )
    except Exception:  # noqa: BLE001 - see docstring
        log.exception("Could not send the alert email")


# ---------------------------------------------------------------- errors from PostHog while serving requests


def _describe(website_name: str, upstream_status: int | None, detail: str | None) -> tuple[str, str]:
    """(severity, message) for an admin, in plain words."""
    said = f" PostHog said: {detail}" if detail else ""
    if upstream_status in (401, 403):
        return "critical", f"PostHog refused the API key of “{website_name}” ({upstream_status}). Replace the key in the website's PostHog connection.{said}"
    if upstream_status == 404:
        return "critical", f"PostHog could not find the project of “{website_name}” (404). Check the project ID and region.{said}"
    if upstream_status == 429:
        return "warning", f"PostHog is rate-limiting “{website_name}” (429): too many queries.{said}"
    if upstream_status == 400:
        return "warning", f"PostHog rejected one of our queries for “{website_name}” (400): this is a bug in the portal.{said}"
    return "warning", f"PostHog is having trouble answering for “{website_name}” ({upstream_status or 'no answer'}).{said}"


def _record_posthog_error_sync(website_id: uuid.UUID, upstream_status: int | None, detail: str | None) -> None:
    with get_sessionmaker()() as db:
        website = db.get(Website, website_id)
        if website is None:
            return
        severity, message = _describe(website.name, upstream_status, detail)
        alert, created = raise_alert(
            db,
            kind="posthog_error",
            dedupe_key=f"posthog_error:{website.id}:{upstream_status or 'none'}",
            message=message,
            severity=severity,
            website_id=website.id,
            client_id=website.client_id,
            details={"upstream_status": upstream_status, "detail": (detail or "")[:300]},
        )
        if created:
            notify_admins(alert, get_setting(db, "alerts.extra_recipients"))


async def record_posthog_error(website: WebsiteConfig, upstream_status: int | None, detail: str | None) -> None:
    """Called by PostHogClient whenever a request to PostHog fails for good (after retries)."""
    website_id = parse_uuid(website.website_id)  # connection checks use ids that are not real websites: ignore them
    if website_id is None:
        return
    try:
        await asyncio.to_thread(_record_posthog_error_sync, website_id, upstream_status, detail)
    except Exception:  # noqa: BLE001 - recording an alert must never break the request that triggered it
        log.exception("Could not record a PostHog error as an alert")
