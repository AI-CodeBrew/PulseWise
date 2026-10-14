"""Is data arriving from a website? (the green/red signal in the admin panel and the daily alert check)"""

from datetime import datetime, timezone
from typing import Any

from app.posthog_client import PostHogClient

LAST_24H_QUERY = """
SELECT
    count()                       AS events,
    countIf(event = '$pageview')  AS pageviews,
    max(timestamp)                AS last_event_at
FROM events
WHERE timestamp >= now() - toIntervalHour(24)
"""

# Only asked when nothing arrived in the last 24h (so it scans a longer period rarely).
LAST_EVENT_EVER_QUERY = """
SELECT max(timestamp) AS last_event_at
FROM events
WHERE timestamp >= now() - toIntervalDay(90)
"""

# How long without events counts as "red" (the roadmap says: alert after 48 hours).
RED_AFTER_HOURS = 48


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    # PostHog returns a "zero" date for max() of nothing.
    if parsed.year < 2000:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def website_health(ph: PostHogClient) -> dict[str, Any]:
    """Returns {status, events_24h, pageviews_24h, last_event_at, hours_since_last_event}.

    status: "green" = events in the last 24h; "amber" = none in 24h but some within 48h;
            "red" = nothing for 48h or more (or never).
    """
    rows = await ph.hogql(LAST_24H_QUERY, name="health:24h", ttl=60)
    row = rows[0] if rows else {}
    events = int(row.get("events") or 0)
    pageviews = int(row.get("pageviews") or 0)
    last = _parse_time(row.get("last_event_at")) if events else None

    if not events:
        ever = await ph.hogql(LAST_EVENT_EVER_QUERY, name="health:last", ttl=300)
        last = _parse_time(ever[0].get("last_event_at")) if ever else None

    hours = None
    if last is not None:
        hours = round((datetime.now(timezone.utc) - last).total_seconds() / 3600, 1)

    if events > 0:
        status = "green"
    elif hours is not None and hours < RED_AFTER_HOURS:
        status = "amber"
    else:
        status = "red"

    return {
        "status": status,
        "events_24h": events,
        "pageviews_24h": pageviews,
        "last_event_at": last.isoformat() if last else None,
        "hours_since_last_event": hours,
    }
