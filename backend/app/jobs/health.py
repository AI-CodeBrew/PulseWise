"""Job: once a day, check that every website is still sending data, and raise or clear alerts."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.alerts import notify_admins, raise_alert, resolve_alerts
from app.config import WebsiteConfig
from app.db import get_sessionmaker
from app.deps import config_from_website
from app.jobs.registry import job
from app.models import Client, Website
from app.posthog_client import AnalyticsError, PostHogClient
from app.services.health import website_health
from app.settings_store import get_setting

log = logging.getLogger(__name__)


def _load() -> tuple[list[tuple[WebsiteConfig, uuid.UUID, uuid.UUID, str, datetime]], int, str]:
    with get_sessionmaker()() as db:
        threshold = get_setting(db, "alerts.no_events_hours")
        extra = get_setting(db, "alerts.extra_recipients")
        sites = []
        for website in db.scalars(select(Website).join(Client).where(Website.is_active.is_(True)).order_by(Website.name)):
            try:
                created = website.created_at if website.created_at.tzinfo else website.created_at.replace(tzinfo=timezone.utc)
                sites.append((config_from_website(website), website.id, website.client_id, website.name, created))
            except RuntimeError:
                log.error("Skipping website %s: its API key can't be decrypted", website.id)
        return sites, threshold, extra


def _apply(website_id: uuid.UUID, client_id: uuid.UUID, name: str, health: dict[str, Any], threshold: int, extra: str, created: datetime) -> str:
    """Open or close alerts for one website. Returns 'ok', 'quiet' or 'alert'."""
    with get_sessionmaker()() as db:
        # The connection worked, so any earlier "PostHog refused the key / project / rate limit..." alert is stale.
        resolve_alerts(db, website_id=website_id, kind="posthog_error")

        hours = health["hours_since_last_event"]
        quiet_for_long = health["events_24h"] == 0 and (hours is None or hours >= threshold)
        old_enough = datetime.now(timezone.utc) - created >= timedelta(hours=threshold)  # don't alarm while a site is still being set up
        key = f"no_events:{website_id}"
        if quiet_for_long and old_enough:
            when = "has never sent an event" if hours is None else f"has sent no events for {int(hours)} hours"
            alert, is_new = raise_alert(
                db, kind="no_events", dedupe_key=key, severity="warning", website_id=website_id, client_id=client_id,
                message=f"“{name}” {when}. The tracking code may have been removed or broken.",
                details={"hours_since_last_event": hours, "last_event_at": health["last_event_at"]},
            )
            if is_new:
                notify_admins(alert, extra)
            return "alert"
        resolve_alerts(db, dedupe_key=key)
        return "quiet" if health["events_24h"] == 0 else "ok"


@job(
    "daily_health",
    title="Check that data is still arriving",
    description="For every website: is it still sending events? Raises an alert (and emails the admins) when a website has been silent too long, and clears it when data returns.",
    schedule="Every day at 06:00 UTC (11:00 in Pakistan)",
    cron={"hour": 6, "minute": 0},
)
async def daily_health() -> dict[str, Any]:
    sites, threshold, extra = await asyncio.to_thread(_load)
    outcomes: dict[str, str] = {}
    unreachable: list[str] = []
    semaphore = asyncio.Semaphore(2)

    async def one(config: WebsiteConfig, website_id: uuid.UUID, client_id: uuid.UUID, name: str, created: datetime) -> None:
        async with semaphore:
            try:
                health = await website_health(PostHogClient(config))
            except AnalyticsError:  # the PostHog client has already raised a "posthog_error" alert for it
                unreachable.append(name)
                return
        outcomes[name] = await asyncio.to_thread(_apply, website_id, client_id, name, health, threshold, extra, created)

    await asyncio.gather(*(one(cfg, wid, cid, name, created) for cfg, wid, cid, name, created in sites))
    alerting = [n for n, o in outcomes.items() if o == "alert"]
    message = f"Checked {len(sites)} websites: {len(alerting)} silent, {len(unreachable)} unreachable."
    if alerting:
        message += " Silent: " + ", ".join(alerting[:5])
    return {"message": message, "silent": alerting, "unreachable": unreachable}
