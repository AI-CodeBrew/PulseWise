"""
The box that opens when someone clicks a dashboard tile: the full story behind one number.

Two requests build the box, so the top of it can appear while the slower part is still loading:
  * get_detail()  the day-by-day trend and a few breakdowns ("where do these people come from?")
  * get_recent()  the latest visits / events behind the number, and which of them have a recording to watch

Everything is read-only and follows the same rules as the rest of the analytics:
  * the SQL text below is fixed; anything that varies (an event name, a page, a country) goes in as a {placeholder} value;
  * the plan decides what is shown: visits need the `sessions` feature, events need `live_events`, and the
    "Watch" buttons need `recordings` (the router passes in the lock messages, see routers/dashboard.py).

A visit's recording has the SAME id as the visit (PostHog calls it the session id), so a "Watch" button is just a link to
/recordings/<session id>. Whether that visit was recorded at all is checked in one extra query.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.posthog_client import AnalyticsError, PostHogClient
from app.services import tiles
from app.services.common import label, num

START = "toStartOfDay(now()) - toIntervalDay({days} - 1)"  # "the last N days" = today and the N-1 days before
PAGEVIEW = "AND event = '$pageview'"
ROWS = 8  # rows in a breakdown
RECENT_ROWS = 10  # rows in the "latest" list
RECORDING_LOOKBACK_DAYS = 45  # a visit from the last 30 days started well inside this window


# ------------------------------------------------------------------ the trend (one number per day)


@dataclass(frozen=True)
class SeriesSpec:
    label: str
    kind: str  # number | decimal | percent | duration
    query: str


def _events_series(expression: str, where: str = "") -> str:
    return f"""
SELECT toDate(timestamp) AS day, {expression} AS value, toDate(now()) AS today
FROM events
WHERE timestamp >= {START} {where}
GROUP BY day
ORDER BY day
"""


def _sessions_series(expression: str) -> str:
    return f"""
SELECT toDate($start_timestamp) AS day, {expression} AS value, toDate(now()) AS today
FROM sessions
WHERE $start_timestamp >= {START} AND $pageview_count > 0
GROUP BY day
ORDER BY day
"""


PHONE = "properties.$device_type IN ('Mobile', 'Tablet')"

SERIES: dict[str, SeriesSpec] = {
    "active_users_30d": SeriesSpec("Active users per day", "number", _events_series("uniq(person_id)")),
    "sessions_7d": SeriesSpec("Sessions per day", "number", _sessions_series("count()")),
    "pageviews_7d": SeriesSpec("Pageviews per day", "number", _events_series("count()", PAGEVIEW)),
    "visitors_7d": SeriesSpec("Visitors per day", "number", _events_series("uniq(person_id)", PAGEVIEW)),
    "events_7d": SeriesSpec("Events per day", "number", _events_series("count()")),
    "bounce_rate_7d": SeriesSpec("Left after 1 page, per day", "percent", _sessions_series("round(100 * avg($is_bounce), 1)")),
    "avg_visit_7d": SeriesSpec("Average visit length per day", "duration", _sessions_series("round(avg($session_duration))")),
    "pages_per_visit_7d": SeriesSpec("Pages per visit, per day", "decimal", _sessions_series("round(avg($pageview_count), 1)")),
    "top_page_7d": SeriesSpec("Views of this page per day", "number", _events_series("count()", PAGEVIEW + " AND properties.$pathname = {path}")),
    "top_country_7d": SeriesSpec("Visitors from this country per day", "number", _events_series("uniq(person_id)", PAGEVIEW + " AND properties.$geoip_country_name = {country}")),
    "mobile_share_7d": SeriesSpec("Share of visitors on a phone, per day", "percent", _events_series(f"round(100 * uniqIf(person_id, {PHONE}) / uniq(person_id), 1)", PAGEVIEW)),
}
EVENT_SERIES_QUERY = _events_series("count()", "AND event = {name}")


# ------------------------------------------------------------------ breakdowns (a short ranked list)


@dataclass(frozen=True)
class BreakdownSpec:
    title: str
    unit: str  # what the numbers count, for the hover text
    kind: str  # number | decimal | percent | duration
    query: str
    clean: str = "plain"  # plain | event: how names are tidied


def _by_events(name_expression: str, value_expression: str, where: str = "") -> str:
    return f"""
SELECT {name_expression} AS name, {value_expression} AS value
FROM events
WHERE timestamp >= {START} {where}
GROUP BY name
ORDER BY value DESC
LIMIT {ROWS}
"""


def _by_sessions(name_expression: str, value_expression: str, having: str = "") -> str:
    return f"""
SELECT {name_expression} AS name, {value_expression} AS value, count() AS visits
FROM sessions
WHERE $start_timestamp >= {START} AND $pageview_count > 0
GROUP BY name {having}
ORDER BY value DESC, visits DESC
LIMIT {ROWS}
"""


ENOUGH_VISITS = "HAVING count() >= 3"  # a landing page seen once would otherwise top every "average" ranking

BREAKDOWNS: dict[str, BreakdownSpec] = {
    "pages": BreakdownSpec("Most viewed pages", "views", "number", _by_events("properties.$pathname", "count()", PAGEVIEW)),
    "channels": BreakdownSpec("How visits arrived", "visits", "number", _by_sessions("$channel_type", "count()")),
    "countries": BreakdownSpec("Countries", "visitors", "number", _by_events("properties.$geoip_country_name", "uniq(person_id)", PAGEVIEW)),
    "devices": BreakdownSpec("Devices", "visitors", "number", _by_events("properties.$device_type", "uniq(person_id)", PAGEVIEW)),
    "browsers": BreakdownSpec("Browsers", "visitors", "number", _by_events("properties.$browser", "uniq(person_id)", PAGEVIEW)),
    "events_by_name": BreakdownSpec("What happened most", "times", "number", _by_events("event", "count()"), "event"),
    "entry_pages": BreakdownSpec("Pages people landed on", "visits", "number", _by_sessions("$entry_pathname", "count()")),
    "bounce_by_entry": BreakdownSpec("Landing pages people leave most", "left after 1 page", "percent", _by_sessions("$entry_pathname", "round(100 * avg($is_bounce), 1)", ENOUGH_VISITS)),
    "duration_by_entry": BreakdownSpec("Landing pages with the longest visits", "average visit", "duration", _by_sessions("$entry_pathname", "round(avg($session_duration))", ENOUGH_VISITS)),
    "pages_per_visit_by_entry": BreakdownSpec("Landing pages where people look at the most pages", "pages per visit", "decimal", _by_sessions("$entry_pathname", "round(avg($pageview_count), 1)", ENOUGH_VISITS)),
    "page_countries": BreakdownSpec("Where this page's visitors are", "visitors", "number", _by_events("properties.$geoip_country_name", "uniq(person_id)", PAGEVIEW + " AND properties.$pathname = {path}")),
    "country_pages": BreakdownSpec("Pages these visitors look at", "views", "number", _by_events("properties.$pathname", "count()", PAGEVIEW + " AND properties.$geoip_country_name = {country}")),
    "event_pages": BreakdownSpec("Where it happened", "times", "number", _by_events("properties.$pathname", "count()", "AND event = {name}")),
    "event_devices": BreakdownSpec("On which devices", "times", "number", _by_events("properties.$device_type", "count()", "AND event = {name}")),
}

# PostHog's own events have names like "$web_vitals": say what they are in plain words.
EVENT_NAMES = {
    "$pageview": "Page views",
    "$pageleave": "People leaving a page",
    "$autocapture": "Clicks and taps (recorded automatically)",
    "$web_vitals": "Page speed measurements",
    "$rageclick": "Rage clicks (repeated, frustrated clicks)",
    "$dead_click": "Dead clicks (nothing happened)",
    "$exception": "Errors on the page",
    "$identify": "People identified",
    "$set": "Visitor details saved",
}


def _tidy_name(value: Any, clean: str) -> str:
    text = label(value)
    if clean == "event":
        return EVENT_NAMES.get(text) or (text.lstrip("$").replace("_", " ").capitalize() if text.startswith("$") else text)
    return text


# ------------------------------------------------------------------ the latest rows (visits or events)


@dataclass(frozen=True)
class ListSpec:
    title: str
    kind: str  # "sessions" (visits) | "events"
    query: str


def _visits(order: str, where: str = "") -> str:
    """Visits straight from the sessions table (it already knows each visit's length, pages and whether it bounced)."""
    return f"""
SELECT session_id, $start_timestamp AS started_at, $session_duration AS duration, $entry_pathname AS entry_page,
       $pageview_count AS pageviews, distinct_id AS visitor
FROM sessions
WHERE $start_timestamp >= {START} AND $pageview_count > 0 {where}
ORDER BY {order}
LIMIT {RECENT_ROWS}
"""


def _visits_from_events(where: str) -> str:
    """Visits that had at least one event matching `where` (a page, a country, a device)."""
    return f"""
SELECT $session_id AS session_id, min(timestamp) AS started_at, dateDiff('second', min(timestamp), max(timestamp)) AS duration,
       argMin(properties.$pathname, timestamp) AS entry_page, countIf(event = '$pageview') AS pageviews, any(distinct_id) AS visitor
FROM events
WHERE timestamp >= {START} AND $session_id IS NOT NULL AND $session_id != '' {where}
GROUP BY session_id
ORDER BY started_at DESC
LIMIT {RECENT_ROWS}
"""


def _event_rows(where: str = "") -> str:
    return f"""
SELECT uuid, event, timestamp, properties.$pathname AS path, $session_id AS session_id, distinct_id AS visitor
FROM events
WHERE timestamp >= {START} {where}
ORDER BY timestamp DESC
LIMIT {RECENT_ROWS}
"""


LATEST_VISITS = _visits("$start_timestamp DESC")
LISTS: dict[str, ListSpec] = {
    "latest_visits": ListSpec("Latest visits", "sessions", LATEST_VISITS),
    "bounced_visits": ListSpec("Latest visits where the person left after one page", "sessions", _visits("$start_timestamp DESC", "AND $is_bounce = 1")),
    "longest_visits": ListSpec("Longest visits", "sessions", _visits("$session_duration DESC")),
    "deepest_visits": ListSpec("Visits with the most pages", "sessions", _visits("$pageview_count DESC, $start_timestamp DESC")),
    "mobile_visits": ListSpec("Latest visits on a phone", "sessions", _visits_from_events(f"AND {PHONE}")),
    "visits_to_page": ListSpec("Latest visits that viewed this page", "sessions", _visits_from_events("AND event = '$pageview' AND properties.$pathname = {path}")),
    "visits_from_country": ListSpec("Latest visits from this country", "sessions", _visits_from_events("AND properties.$geoip_country_name = {country}")),
    "latest_pageviews": ListSpec("Latest page views", "events", _event_rows(PAGEVIEW)),
    "latest_events": ListSpec("Latest events", "events", _event_rows()),
    "event_times": ListSpec("Latest times it happened", "events", _event_rows("AND event = {name}")),
}

# What each tile shows: (series spec key, breakdowns, the latest-rows list)
PLAN: dict[str, tuple[list[str], str]] = {
    "active_users_30d": (["countries", "devices"], "latest_visits"),
    "sessions_7d": (["channels", "entry_pages"], "latest_visits"),
    "pageviews_7d": (["pages", "channels"], "latest_pageviews"),
    "visitors_7d": (["countries", "devices"], "latest_visits"),
    "events_7d": (["events_by_name", "pages"], "latest_events"),
    "bounce_rate_7d": (["bounce_by_entry", "channels"], "bounced_visits"),
    "avg_visit_7d": (["duration_by_entry", "channels"], "longest_visits"),
    "pages_per_visit_7d": (["pages_per_visit_by_entry", "pages"], "deepest_visits"),
    "top_page_7d": (["pages", "page_countries"], "visits_to_page"),
    "top_country_7d": (["countries", "country_pages"], "visits_from_country"),
    "mobile_share_7d": (["devices", "browsers"], "mobile_visits"),
}
EVENT_PLAN = (["event_pages", "event_devices"], "event_times")


# ------------------------------------------------------------------ one tile's context


@dataclass
class Context:
    """What we need to know about the tile before asking anything: its days, and the thing it is about."""

    key: str
    tile: tiles.Tile
    days: int
    values: dict[str, Any] = field(default_factory=dict)  # {placeholder: value} for the queries that need one
    subject: str | None = None  # "/collections/kitchen", "Pakistan" or an event name: for the titles

    def for_query(self, query: str) -> dict[str, Any]:
        """Only the values this query mentions (PostHog may refuse values nobody uses)."""
        return {k: v for k, v in self.values.items() if "{" + k + "}" in query}


async def context_for(ph: PostHogClient, key: str) -> Context:
    tile = tiles.describe(key)
    ctx = Context(key=key, tile=tile, days=tile.days, values={"days": tile.days})
    event = tiles.parse_event_key(key)
    if event is not None:
        ctx.values["name"] = ctx.subject = event[0]
    elif key in ("top_page_7d", "top_country_7d"):
        # These two are about "the top page" / "the top country": ask the tile itself which one it is right now.
        current = (await tiles.get_values(ph, [key]))[0]["value"]
        ctx.values["path" if key == "top_page_7d" else "country"] = ctx.subject = str(current)
    return ctx


def _plan(ctx: Context) -> tuple[list[str], str]:
    return EVENT_PLAN if tiles.parse_event_key(ctx.key) else PLAN[ctx.key]


# ------------------------------------------------------------------ 1. the trend and the breakdowns


def _fill_days(rows: list[dict[str, Any]], days: int, kind: str) -> tuple[list[dict[str, Any]], date]:
    """One point for every day (a day without rows is a real zero), and what 'today' is for the website."""
    by_day = {str(r["day"]): r["value"] for r in rows}
    today = date.fromisoformat(str(rows[0]["today"])) if rows else date.today()
    points = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        points.append({"date": day, "value": _number(by_day.get(day), kind)})
    return points, today


def _number(value: Any, kind: str) -> int | float:
    if kind == "number" or kind == "duration":
        return int(round(num(value)))
    return round(num(value), 1)


async def get_detail(ph: PostHogClient, key: str) -> dict[str, Any]:
    ctx = await context_for(ph, key)
    breakdown_keys, _ = _plan(ctx)
    if tiles.parse_event_key(key):
        series = SeriesSpec(f"“{ctx.subject}” per day", "number", EVENT_SERIES_QUERY)
    else:
        series = SERIES[key]
    breakdowns = [BREAKDOWNS[k] for k in breakdown_keys]

    async def run(query: str, name: str) -> list[dict[str, Any]]:
        return await ph.hogql(query, ctx.for_query(query), name=name)

    series_rows, *breakdown_rows = await asyncio.gather(
        run(series.query, "tiles:detail:series"),
        *(run(b.query, f"tiles:detail:breakdown:{k}") for k, b in zip(breakdown_keys, breakdowns)),
    )
    points, today = _fill_days(series_rows, ctx.days, series.kind)
    title_subject = f" ({ctx.subject})" if ctx.subject and key in ("top_page_7d", "top_country_7d") else ""
    return {
        "key": key,
        "days": ctx.days,
        "period": {"start": (today - timedelta(days=ctx.days - 1)).isoformat(), "end": today.isoformat()},
        "subject": ctx.subject,
        "series": {"label": series.label + title_subject, "kind": series.kind, "points": points},
        "breakdowns": [
            {
                "key": k,
                "title": b.title,
                "unit": b.unit,
                "kind": b.kind,
                "rows": [{"name": _tidy_name(r["name"], b.clean), "value": _number(r["value"], b.kind)} for r in rows],
            }
            for k, b, rows in zip(breakdown_keys, breakdowns, breakdown_rows)
        ],
    }


# ------------------------------------------------------------------ 2. the latest rows, and which can be watched


def _visitor_label(distinct_id: Any) -> str:
    """Most visitors are anonymous: show a short, stable label. An identified person (an email) is shown as it is."""
    text = str(distinct_id or "")
    if not text:
        return "Unknown visitor"
    return text if "@" in text else f"Visitor {text[:8]}"


def _shape_row(kind: str, r: dict[str, Any]) -> dict[str, Any]:
    if kind == "sessions":
        return {
            "session_id": str(r["session_id"]),
            "started_at": r["started_at"],
            "duration": int(num(r.get("duration"))),
            "pageviews": int(num(r.get("pageviews"))),
            "entry_page": label(r.get("entry_page")),
            "visitor": _visitor_label(r.get("visitor")),
            "has_recording": None,
        }
    session_id = r.get("session_id")
    return {
        "id": str(r["uuid"]),
        "event": _tidy_name(r["event"], "event"),
        "timestamp": r["timestamp"],
        "page": label(r.get("path"), "-"),
        "visitor": _visitor_label(r.get("visitor")),
        "session_id": str(session_id) if session_id else None,
        "has_recording": None,
    }


RECORDED_QUERY = f"""
SELECT DISTINCT session_id
FROM raw_session_replay_events
WHERE session_id IN {{ids}} AND min_first_timestamp >= now() - toIntervalDay({RECORDING_LOOKBACK_DAYS})
"""


async def _mark_recordings(ph: PostHogClient, rows: list[dict[str, Any]]) -> bool:
    """Set `has_recording` on every row. Returns False when we couldn't find out (the flags then stay unknown)."""
    ids = sorted({r["session_id"] for r in rows if r.get("session_id")})
    if not ids:
        for r in rows:
            r["has_recording"] = False
        return True
    try:
        recorded = await ph.hogql(RECORDED_QUERY, {"ids": ids}, name="tiles:detail:recordings")
    except AnalyticsError:  # e.g. the website's key may not read recordings: the rest of the box still works
        return False
    have = {str(r["session_id"]) for r in recorded}
    for r in rows:
        r["has_recording"] = bool(r.get("session_id")) and r["session_id"] in have
    return True


async def get_recent(ph: PostHogClient, key: str, *, locks: dict[str, str | None]) -> dict[str, Any]:
    """`locks`: for "sessions", "events" and "recordings", the message to show when the plan doesn't include it (else None)."""
    ctx = await context_for(ph, key)
    _, list_key = _plan(ctx)
    spec = LISTS[list_key]
    title = spec.title
    if ctx.subject and list_key in ("visits_to_page", "visits_from_country", "event_times"):
        title = {"visits_to_page": f"Latest visits that viewed {ctx.subject}", "visits_from_country": f"Latest visits from {ctx.subject}", "event_times": f"Latest times “{ctx.subject}” happened"}[list_key]

    out: dict[str, Any] = {"key": key, "days": ctx.days, "title": title, "kind": spec.kind, "rows": [], "locked": locks.get(spec.kind),
                           "recordings": {"locked": locks.get("recordings"), "checked": False}}
    if out["locked"]:  # the plan doesn't include this part: no queries at all
        return out
    rows = [_shape_row(spec.kind, r) for r in await ph.hogql(spec.query, ctx.for_query(spec.query), name="tiles:detail:list")]
    # The "Watch" buttons: only when the plan has recordings, and only for visits that were really recorded.
    if not out["recordings"]["locked"]:
        out["recordings"]["checked"] = await _mark_recordings(ph, rows)
    out["rows"] = rows
    return out
