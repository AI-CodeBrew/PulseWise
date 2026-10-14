"""Job: count each website's events per day (PostHog bills by events, so this is what each client costs us)."""

import asyncio
import calendar
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.config import WebsiteConfig
from app.db import get_sessionmaker
from app.deps import config_from_website
from app.jobs.registry import job
from app.models import UsageDaily, Website
from app.posthog_client import AnalyticsError, PostHogClient

log = logging.getLogger(__name__)

# `toDate(...)` is the day in the PostHog project's own time zone. {days} = how many days back to read.
EVENTS_QUERY = """
SELECT toDate(timestamp) AS day, count() AS events, countIf(event = '$pageview') AS pageviews
FROM events
WHERE timestamp >= toStartOfDay(now()) - toIntervalDay({days})
GROUP BY day
ORDER BY day
"""

# Recordings = distinct sessions that have replay data. (Needs the key to have the "Session recording: Read" scope.)
RECORDINGS_QUERY = """
SELECT toDate(min_first_timestamp) AS day, uniq(session_id) AS recordings
FROM raw_session_replay_events
WHERE min_first_timestamp >= toStartOfDay(now()) - toIntervalDay({days})
GROUP BY day
ORDER BY day
"""

NORMAL_LOOKBACK_DAYS = 3  # late events and time zones: re-read the last few days every time
MAX_BACKFILL_DAYS = 45


def month_start(today: date | None = None) -> date:
    today = today or datetime.now(timezone.utc).date()
    return today.replace(day=1)


def _load_sites() -> list[tuple[WebsiteConfig, int]]:
    """Every active website with how many days back to read (a new website gets the whole month so far)."""
    today = datetime.now(timezone.utc).date()
    first_of_month = month_start(today)
    sites = []
    with get_sessionmaker()() as db:
        for website in db.scalars(select(Website).where(Website.is_active.is_(True)).order_by(Website.name)):
            has_rows = db.scalar(
                select(func.count()).select_from(UsageDaily).where(UsageDaily.website_id == website.id, UsageDaily.day >= first_of_month)
            )
            days_back = NORMAL_LOOKBACK_DAYS if has_rows else min((today - first_of_month).days + 1, MAX_BACKFILL_DAYS)
            try:
                sites.append((config_from_website(website), max(days_back, NORMAL_LOOKBACK_DAYS)))
            except RuntimeError:
                log.error("Skipping website %s: its API key can't be decrypted", website.id)
    return sites


def upsert_usage(db: Session, website_id: uuid.UUID, rows: dict[date, dict[str, int]]) -> None:
    """Insert or update one row per day (works on PostgreSQL and SQLite)."""
    if not rows:
        return
    dialect = db.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    values = [{"website_id": website_id, "day": day, **numbers} for day, numbers in rows.items()]
    statement = insert(UsageDaily).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["website_id", "day"],
        set_={name: getattr(statement.excluded, name) for name in ("events", "pageviews", "recordings")}
        | {"updated_at": datetime.now(timezone.utc)},
    )
    db.execute(statement)
    db.commit()


def _save(website_id: str, events: list[dict[str, Any]], recordings: list[dict[str, Any]]) -> int:
    by_day: dict[date, dict[str, int]] = {}
    for row in events:
        by_day.setdefault(date.fromisoformat(str(row["day"])), {"events": 0, "pageviews": 0, "recordings": 0}).update(
            events=int(row["events"] or 0), pageviews=int(row["pageviews"] or 0)
        )
    for row in recordings:
        by_day.setdefault(date.fromisoformat(str(row["day"])), {"events": 0, "pageviews": 0, "recordings": 0})["recordings"] = int(row["recordings"] or 0)
    with get_sessionmaker()() as db:
        upsert_usage(db, uuid.UUID(website_id), by_day)
    return len(by_day)


async def sync_website(config: WebsiteConfig, days_back: int) -> int:
    ph = PostHogClient(config)
    events = await ph.hogql(EVENTS_QUERY, {"days": days_back}, name="usage:events", ttl=0)
    try:
        recordings = await ph.hogql(RECORDINGS_QUERY, {"days": days_back}, name="usage:recordings", ttl=0)
    except AnalyticsError as exc:  # most often: the key may not read recordings. Events still count.
        log.info("Recording counts unavailable for %s: %s", config.name, exc.upstream_detail or exc.message)
        recordings = []
    return await asyncio.to_thread(_save, config.website_id, events, recordings)


@job(
    "usage_sync",
    title="Count events per website",
    description="Reads each website's event counts from PostHog and saves them per day. Used for usage limits and your PostHog cost estimate.",
    schedule="Every hour, at 5 past",
    cron={"minute": 5},
)
async def usage_sync() -> dict[str, Any]:
    sites = await asyncio.to_thread(_load_sites)
    semaphore = asyncio.Semaphore(2)  # be gentle with PostHog's limits

    async def one(config: WebsiteConfig, days_back: int) -> tuple[str, str | None]:
        async with semaphore:
            try:
                await sync_website(config, days_back)
                return config.name, None
            except AnalyticsError as exc:
                return config.name, exc.upstream_detail or exc.message

    results = await asyncio.gather(*(one(c, d) for c, d in sites))
    failed = {name: reason for name, reason in results if reason}
    limits = await asyncio.to_thread(_check_limits)
    message = f"Synced {len(results) - len(failed)} of {len(results)} websites."
    if limits["over"] or limits["warning"]:
        message += f" Plan limits: {len(limits['over'])} over, {len(limits['warning'])} close."
    if failed:
        message += " Failed: " + "; ".join(f"{n} ({r})" for n, r in list(failed.items())[:5])
    if results and len(failed) == len(results):
        raise RuntimeError(message)  # nothing worked at all: that is a job failure
    return {"message": message, "websites": len(results), "failed": failed}


def _check_limits() -> dict[str, list[str]]:
    from app.billing.limits import evaluate_usage_limits

    with get_sessionmaker()() as db:
        return evaluate_usage_limits(db)


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]
