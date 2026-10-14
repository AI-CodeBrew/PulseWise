"""Collecting the numbers for one website's report: a fixed period (Monday to Sunday) and the week before it."""

import asyncio
from datetime import date, timedelta
from typing import Any

from app.posthog_client import PostHogClient
from app.services.common import change_pct, num

# All times are in the PostHog project's own time zone. {start} .. {end} is the report week (end is the day AFTER
# the last day), {pstart} .. {start} is the week before, for the "vs last week" comparisons.
WINDOW = "timestamp >= toDateTime({pstart}) AND timestamp < toDateTime({end})"

KPI_EVENTS = f"""
SELECT
    countIf(timestamp >= toDateTime({{start}}))                                              AS pageviews,
    uniqIf(person_id, timestamp >= toDateTime({{start}}))                                    AS visitors,
    countIf(timestamp < toDateTime({{start}}))                                               AS prev_pageviews,
    uniqIf(person_id, timestamp < toDateTime({{start}}))                                     AS prev_visitors
FROM events
WHERE event = '$pageview' AND {WINDOW}
"""

KPI_SESSIONS = """
SELECT
    countIf($start_timestamp >= toDateTime({start}))        AS sessions,
    countIf($start_timestamp <  toDateTime({start}))        AS prev_sessions,
    avgIf($session_duration, $start_timestamp >= toDateTime({start})) AS avg_duration,
    avgIf($session_duration, $start_timestamp <  toDateTime({start})) AS prev_avg_duration,
    avgIf($is_bounce,        $start_timestamp >= toDateTime({start})) AS bounce_rate,
    avgIf($is_bounce,        $start_timestamp <  toDateTime({start})) AS prev_bounce_rate
FROM sessions
WHERE $start_timestamp >= toDateTime({pstart}) AND $start_timestamp < toDateTime({end}) AND $pageview_count > 0
"""

DAILY = """
SELECT toDate(timestamp) AS day, count() AS pageviews, uniq(person_id) AS visitors
FROM events
WHERE event = '$pageview' AND timestamp >= toDateTime({start}) AND timestamp < toDateTime({end})
GROUP BY day ORDER BY day
"""

TOP_PAGES = """
SELECT properties.$pathname AS path, count() AS views, uniq(person_id) AS visitors
FROM events
WHERE event = '$pageview' AND timestamp >= toDateTime({start}) AND timestamp < toDateTime({end})
GROUP BY path ORDER BY views DESC LIMIT 5
"""

SOURCES = """
SELECT $entry_referring_domain AS name, count() AS sessions
FROM sessions
WHERE $start_timestamp >= toDateTime({start}) AND $start_timestamp < toDateTime({end}) AND $pageview_count > 0
GROUP BY name ORDER BY sessions DESC LIMIT 5
"""

CHANNELS = """
SELECT $channel_type AS name, count() AS sessions
FROM sessions
WHERE $start_timestamp >= toDateTime({start}) AND $start_timestamp < toDateTime({end}) AND $pageview_count > 0
GROUP BY name ORDER BY sessions DESC LIMIT 5
"""

COUNTRIES = """
SELECT properties.$geoip_country_name AS name, uniq(person_id) AS visitors
FROM events
WHERE event = '$pageview' AND timestamp >= toDateTime({start}) AND timestamp < toDateTime({end})
GROUP BY name ORDER BY visitors DESC LIMIT 5
"""

DEVICES = """
SELECT properties.$device_type AS name, uniq(person_id) AS visitors
FROM events
WHERE event = '$pageview' AND timestamp >= toDateTime({start}) AND timestamp < toDateTime({end})
GROUP BY name ORDER BY visitors DESC LIMIT 5
"""

CUSTOM_EVENTS = """
SELECT event, count() AS count
FROM events
WHERE event NOT LIKE '$%' AND timestamp >= toDateTime({start}) AND timestamp < toDateTime({end})
GROUP BY event ORDER BY count DESC LIMIT 5
"""


def _metric(current: Any, previous: Any, digits: int = 0) -> dict[str, Any]:
    cur, prev = num(current), num(previous)
    cur, prev = (int(round(cur)), int(round(prev))) if digits == 0 else (round(cur, digits), round(prev, digits))
    return {"current": cur, "previous": prev, "change_pct": change_pct(cur, prev)}


def _label(value: Any, empty: str) -> str:
    text = "" if value is None else str(value).strip()
    return empty if text in ("", "None") else ("Direct" if text == "$direct" else text)


async def collect_report_data(ph: PostHogClient, start: date, end: date) -> dict[str, Any]:
    """The numbers of the week start..end (both days included), compared with the 7 days before."""
    end_exclusive = end + timedelta(days=1)
    span = (end_exclusive - start).days
    values = {
        "start": f"{start:%Y-%m-%d} 00:00:00",
        "end": f"{end_exclusive:%Y-%m-%d} 00:00:00",
        "pstart": f"{start - timedelta(days=span):%Y-%m-%d} 00:00:00",
    }

    async def q(sql: str, name: str) -> list[dict[str, Any]]:
        return await ph.hogql(sql, values, name=f"report:{name}", ttl=0)

    events, sessions, daily, pages, sources, channels, countries, devices, custom = await asyncio.gather(
        q(KPI_EVENTS, "kpi_events"), q(KPI_SESSIONS, "kpi_sessions"), q(DAILY, "daily"), q(TOP_PAGES, "top_pages"),
        q(SOURCES, "sources"), q(CHANNELS, "channels"), q(COUNTRIES, "countries"), q(DEVICES, "devices"), q(CUSTOM_EVENTS, "custom_events"),
    )
    e, s = (events[0] if events else {}), (sessions[0] if sessions else {})

    by_day = {str(r["day"]): r for r in daily}
    series = []
    for i in range(span):
        day = start + timedelta(days=i)
        row = by_day.get(day.isoformat(), {})
        series.append({"date": day.isoformat(), "visitors": int(row.get("visitors") or 0), "pageviews": int(row.get("pageviews") or 0)})

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": span},
        "kpis": {
            "visitors": _metric(e.get("visitors"), e.get("prev_visitors")),
            "pageviews": _metric(e.get("pageviews"), e.get("prev_pageviews")),
            "sessions": _metric(s.get("sessions"), s.get("prev_sessions")),
            "avg_session_duration": _metric(s.get("avg_duration"), s.get("prev_avg_duration")),  # seconds
            "bounce_rate": _metric(num(s.get("bounce_rate")) * 100, num(s.get("prev_bounce_rate")) * 100, digits=1),  # percent
        },
        "daily": series,
        "top_pages": [{"path": _label(r["path"], "(unknown)"), "views": int(r["views"]), "visitors": int(r["visitors"])} for r in pages],
        "sources": [{"name": _label(r["name"], "Direct"), "sessions": int(r["sessions"])} for r in sources],
        "channels": [{"name": _label(r["name"], "(unknown)"), "sessions": int(r["sessions"])} for r in channels],
        "countries": [{"name": _label(r["name"], "(unknown)"), "visitors": int(r["visitors"])} for r in countries],
        "devices": [{"name": _label(r["name"], "(unknown)"), "visitors": int(r["visitors"])} for r in devices],
        "custom_events": [{"event": str(r["event"]), "count": int(r["count"])} for r in custom],
    }
