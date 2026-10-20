"""
The "My dashboard" tiles on the Overview page: small cards with one big number (like PostHog's dashboard tiles).

Each person picks which tiles they want (saved per user and website, see routers/dashboard.py). A tile is one of:
  * a BUILT-IN tile (Active users, Sessions, Pageviews, ...), listed in BUILTIN below, or
  * a tracked EVENT tile: how many times one of the website's own events (whatsapp_click, add_to_cart...) happened.

ONE tile per thing, with its period as a filter: a tile can show the last 7 or the last 30 days and is switched on the card.
The saved key says which one it is showing now: built-in `sessions_7d` / `sessions_30d`, event `event:<name>:7` / `event:<name>:30`.
The part without the period is the tile's BASE (`sessions`, `event:<name>`): two keys with the same base are the same tile.

Besides its number, every tile says how that number compares with the period just before it ("previous") and carries one
number per day for a little graph ("series"), so a card tells the story at a glance.

To keep PostHog usage low, only the queries needed by the SELECTED tiles run, and one query serves several tiles.
"""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.posthog_client import AnalyticsError, PostHogClient
from app.services import events as events_service
from app.services.common import num

log = logging.getLogger(__name__)

PERIODS = (7, 30)  # the periods a tile can be switched between, in days
EVENT_DEFAULT_DAYS = 30  # a tracked event starts on 30 days (a small website often has nothing in 7)


@dataclass(frozen=True)
class Tile:
    key: str  # WITH the period it shows: "sessions_7d", "event:form_submit:30" (in the catalog: the default period)
    base: str  # without the period: "sessions", "event:form_submit"
    label: str  # the short name on the card: "Sessions"
    template: str  # the explanation; {days} is where the period goes
    kind: str  # number | decimal | percent | duration | text
    group: str
    days: int = 7  # how many days the number covers
    better: str = "up"  # which way is good news: "up", or "down" (for "left after 1 page")

    @property
    def title(self) -> str:
        """The full name with its period, for the chooser and the box: "Sessions (last 7 days)"."""
        return f"{self.label} (last {self.days} days)"

    @property
    def description(self) -> str:
        return self.template.replace("{days}", str(self.days))  # (not .format: an event name may contain braces)


def period_key(base: str, days: int) -> str:
    """The key of a tile for one period: ("sessions", 30) -> "sessions_30d", ("event:form_submit", 7) -> "event:form_submit:7"."""
    return f"{base}:{days}" if base.startswith("event:") else f"{base}_{days}d"


def _builtin(base: str, label: str, template: str, kind: str, group: str, days: int = 7, better: str = "up") -> Tile:
    return Tile(period_key(base, days), base, label, template, kind, group, days, better)


BUILTIN: list[Tile] = [
    _builtin("active_users", "Active users", "Unique people who used your website in the last {days} days. A quick pulse on your overall reach.", "number", "Traffic", 30),
    _builtin("sessions", "Sessions", "Distinct visits in the last {days} days. A session groups everything one person does in a single sitting.", "number", "Traffic"),
    _builtin("pageviews", "Pageviews", "Total pages viewed in the last {days} days, repeat views included. The classic traffic-volume number.", "number", "Traffic"),
    _builtin("visitors", "Visitors", "Unique people who viewed at least one page in the last {days} days.", "number", "Traffic"),
    _builtin("events", "All events", "Everything your website recorded in the last {days} days: page views, clicks and your own tracked actions.", "number", "Traffic"),
    _builtin("bounce_rate", "Left after 1 page", "The share of visits in the last {days} days where the person saw one page and left. Lower is better.", "percent", "Engagement", better="down"),
    _builtin("avg_visit", "Average visit length", "How long a visit lasts on average, over the last {days} days.", "duration", "Engagement"),
    _builtin("pages_per_visit", "Pages per visit", "How many pages people look at in one visit, on average, over the last {days} days.", "decimal", "Engagement"),
    _builtin("top_page", "Most viewed page", "The page people looked at the most in the last {days} days.", "text", "Content"),
    _builtin("top_country", "Top country", "The country most of your visitors came from in the last {days} days.", "text", "Audience"),
    _builtin("mobile_share", "Visitors on a phone", "The share of your visitors in the last {days} days who used a phone or tablet.", "percent", "Audience"),
]
BUILTIN_BY_BASE = {t.base: t for t in BUILTIN}
DEFAULT_TILES = ["active_users_30d", "sessions_7d", "pageviews_7d"]  # pre-ticked the first time someone chooses
MAX_TILES = 24
EVENT_KEY = re.compile(r"^event:(?P<name>.{1,100}):(?P<days>7|30)$", re.DOTALL)
BUILTIN_KEY = re.compile(r"^(?P<base>[a-z_]+)_(?P<days>7|30)d$")

# Which tiles are answered by which query.
EVENT_TILES = {"active_users", "events", "pageviews", "visitors"}
SESSION_TILES = {"sessions", "bounce_rate", "avg_visit", "pages_per_visit"}


class TileKeyError(ValueError):
    """A tile key we don't know (the message is safe to show)."""


def parse_event_key(key: str) -> tuple[str, int] | None:
    match = EVENT_KEY.match(key)
    if match is None:
        return None
    name = match["name"]
    if name != name.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):  # no control characters, no edge spaces
        return None
    return name, int(match["days"])


def parse_key(key: str) -> tuple[str, int] | None:
    """(base, days) of a tile key, or None when it is not one: "sessions_30d" -> ("sessions", 30); "event:x:7" -> ("event:x", 7)."""
    event = parse_event_key(key)
    if event is not None:
        return f"event:{event[0]}", event[1]
    match = BUILTIN_KEY.match(key)
    if match is not None and match["base"] in BUILTIN_BY_BASE:
        return match["base"], int(match["days"])
    return None


def validate_keys(keys: list[str]) -> list[str]:
    """The cleaned list (one tile per base, the first one wins, order kept), or TileKeyError. Used when saving someone's choice."""
    if len(keys) > MAX_TILES * 2:
        raise TileKeyError(f"Please choose at most {MAX_TILES} tiles.")
    clean: list[str] = []
    seen: set[str] = set()
    for key in keys:
        parsed = parse_key(key)
        if parsed is None:
            raise TileKeyError("One of the chosen tiles doesn't exist.")
        if parsed[0] not in seen:  # "sessions_7d" and "sessions_30d" are the same tile: two periods of it never become two tiles
            seen.add(parsed[0])
            clean.append(key)
    if len(clean) > MAX_TILES:
        raise TileKeyError(f"Please choose at most {MAX_TILES} tiles.")
    return clean


def usable_keys(keys: list[str]) -> list[str]:
    """What is shown from a SAVED list: keys that no longer make sense are skipped (a code change must not break the page),
    and a tile saved twice (older versions made one per period) is shown once."""
    clean: list[str] = []
    seen: set[str] = set()
    for key in keys:
        parsed = parse_key(key)
        if parsed is not None and parsed[0] not in seen:
            seen.add(parsed[0])
            clean.append(key)
    return clean


# ---- queries (all values that come from users go in as {placeholders}, never into the text) ----------------

# "the last N days" = today and the N-1 days before; "the N days before that" ends where those begin. {days} is a value.
START = "toStartOfDay(now()) - toIntervalDay({days} - 1)"
PREVIOUS_START = "toStartOfDay(now()) - toIntervalDay(2 * {days} - 1)"
# The same, fixed, for the queries that serve both periods at once.
SEVEN = "toStartOfDay(now()) - toIntervalDay(6)"
PREVIOUS_SEVEN = "toStartOfDay(now()) - toIntervalDay(13)"
THIRTY = "toStartOfDay(now()) - toIntervalDay(29)"
PREVIOUS_THIRTY = "toStartOfDay(now()) - toIntervalDay(59)"
PHONE = "properties.$device_type IN ('Mobile', 'Tablet')"

# Each total comes with the same number for the period before it ("prev_...").
EVENTS_QUERY = f"""
SELECT
    uniqIf(person_id, timestamp >= {START})                                                              AS active_users,
    uniqIf(person_id, timestamp >= {PREVIOUS_START} AND timestamp < {START})                             AS prev_active_users,
    countIf(timestamp >= {START})                                                                        AS events,
    countIf(timestamp >= {PREVIOUS_START} AND timestamp < {START})                                       AS prev_events,
    countIf(event = '$pageview' AND timestamp >= {START})                                                AS pageviews,
    countIf(event = '$pageview' AND timestamp >= {PREVIOUS_START} AND timestamp < {START})               AS prev_pageviews,
    uniqIf(person_id, event = '$pageview' AND timestamp >= {START})                                      AS visitors,
    uniqIf(person_id, event = '$pageview' AND timestamp >= {PREVIOUS_START} AND timestamp < {START})     AS prev_visitors
FROM events
WHERE timestamp >= {PREVIOUS_START}
"""

# One number per day for the little graphs (the last 30 days; a 7 day tile uses the last 7 of them).
EVENTS_DAILY_QUERY = f"""
SELECT
    toDate(timestamp) AS day, toDate(now()) AS today,
    count()                                              AS events,
    countIf(event = '$pageview')                         AS pageviews,
    uniq(person_id)                                      AS active,
    uniqIf(person_id, event = '$pageview')               AS visitors,
    uniqIf(person_id, event = '$pageview' AND {PHONE})   AS mobile
FROM events
WHERE timestamp >= {THIRTY}
GROUP BY day
ORDER BY day
"""

SESSIONS_QUERY = f"""
SELECT
    countIf($start_timestamp >= {START})                         AS sessions,
    avgIf($session_duration, $start_timestamp >= {START})        AS avg_duration,
    avgIf($is_bounce, $start_timestamp >= {START})               AS bounce_rate,
    avgIf($pageview_count, $start_timestamp >= {START})          AS pages_per_visit,
    countIf($start_timestamp < {START})                          AS prev_sessions,
    avgIf($session_duration, $start_timestamp < {START})         AS prev_avg_duration,
    avgIf($is_bounce, $start_timestamp < {START})                AS prev_bounce_rate,
    avgIf($pageview_count, $start_timestamp < {START})           AS prev_pages_per_visit
FROM sessions
WHERE $start_timestamp >= {PREVIOUS_START} AND $pageview_count > 0
"""

SESSIONS_DAILY_QUERY = f"""
SELECT
    toDate($start_timestamp) AS day, toDate(now()) AS today,
    count()                  AS sessions,
    avg($session_duration)   AS avg_duration,
    avg($is_bounce)          AS bounce_rate,
    avg($pageview_count)     AS pages_per_visit
FROM sessions
WHERE $start_timestamp >= {START} AND $pageview_count > 0
GROUP BY day
ORDER BY day
"""

TOP_PAGE_QUERY = f"""
SELECT properties.$pathname AS path, count() AS views
FROM events
WHERE event = '$pageview' AND timestamp >= {START}
GROUP BY path
ORDER BY views DESC
LIMIT 1
"""

TOP_COUNTRY_QUERY = f"""
SELECT properties.$geoip_country_name AS country, uniq(person_id) AS visitors
FROM events
WHERE event = '$pageview' AND timestamp >= {START} AND properties.$geoip_country_name IS NOT NULL
GROUP BY country
ORDER BY visitors DESC
LIMIT 1
"""

MOBILE_QUERY = f"""
SELECT
    uniqIf(person_id, {PHONE} AND timestamp >= {START})   AS mobile,
    uniqIf(person_id, timestamp >= {START})               AS total,
    uniqIf(person_id, {PHONE} AND timestamp < {START})    AS prev_mobile,
    uniqIf(person_id, timestamp < {START})                AS prev_total
FROM events
WHERE event = '$pageview' AND timestamp >= {PREVIOUS_START}
"""

# Tracked events: both periods (and the ones before them) for ALL chosen events in one query.
EVENT_COUNTS_QUERY = f"""
SELECT
    event,
    countIf(timestamp >= {SEVEN})                                          AS last_7,
    countIf(timestamp >= {THIRTY})                                         AS last_30,
    countIf(timestamp >= {PREVIOUS_SEVEN} AND timestamp < {SEVEN})         AS prev_7,
    countIf(timestamp >= {PREVIOUS_THIRTY} AND timestamp < {THIRTY})       AS prev_30
FROM events
WHERE event IN {{names}} AND timestamp >= {PREVIOUS_THIRTY}
GROUP BY event
"""

EVENT_DAILY_QUERY = f"""
SELECT event, toDate(timestamp) AS day, toDate(now()) AS today, count() AS times
FROM events
WHERE event IN {{names}} AND timestamp >= {THIRTY}
GROUP BY event, day
ORDER BY day
"""


def catalog_row(tile: Tile) -> dict[str, Any]:
    return {
        "key": tile.key, "base": tile.base, "label": tile.label, "title": tile.title, "description": tile.description,
        "kind": tile.kind, "group": tile.group, "days": tile.days, "period_keys": {d: period_key(tile.base, d) for d in PERIODS},
    }


async def get_catalog(ph: PostHogClient) -> dict[str, Any]:
    """Everything a person can choose from: the built-in tiles, plus one entry per tracked event of this website."""
    tracked = await events_service.get_custom_events(ph, 30)
    events = []
    for row in tracked["results"][:100]:
        key = f"event:{row['event']}:{EVENT_DEFAULT_DAYS}"
        if parse_event_key(key) is not None:  # (a name that is too long or has control characters can't be a tile)
            events.append({"event": row["event"], "count": row["count"], "key": key})
    return {"tiles": [catalog_row(t) for t in BUILTIN], "events": events}


def describe(key: str) -> Tile:
    """The title, description and kind of a tile (built-in or tracked event), for the period its key says."""
    parsed = parse_key(key)
    if parsed is None:
        raise TileKeyError("That tile doesn't exist.")
    base, days = parsed
    if base in BUILTIN_BY_BASE:
        return dataclasses.replace(BUILTIN_BY_BASE[base], key=key, days=days)
    name = base[len("event:"):]
    return Tile(key, base, name, "How many times “" + name + "” happened on your website in the last {days} days.", "number", "Events", days)


# ---- the little graphs --------------------------------------------------------------------------------------


def _today(*row_lists: list[dict[str, Any]] | None) -> date:
    """What 'today' is for the website (its own time zone), as the daily queries report it."""
    for rows in row_lists:
        if rows:
            return date.fromisoformat(str(rows[0]["today"])[:10])
    return date.today()


def _series(rows: list[dict[str, Any]] | None, today: date, days: int, value_of: Callable[[dict[str, Any]], float], digits: int = 0) -> list[float] | None:
    """One number for each of the last `days` days, oldest first. A day without rows is a real zero.

    None = the daily numbers could not be read: the tile then simply has no graph.
    """
    if rows is None:
        return None
    by_day = {str(r["day"])[:10]: value_of(r) for r in rows}
    points = [by_day.get((today - timedelta(days=offset)).isoformat(), 0.0) for offset in range(days - 1, -1, -1)]
    return [round(p, digits) if digits else int(round(p)) for p in points]


def _share(part: Any, whole: Any) -> float:
    return num(part) / num(whole) * 100 if num(whole) else 0.0


def _first(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    return (rows or [{}])[0]


# base -> (which daily query, how to read one day, decimals). Events and sessions have their own daily query.
DAILY: dict[str, tuple[str, Callable[[dict[str, Any]], float], int]] = {
    "active_users": ("events_daily", lambda r: num(r["active"]), 0),
    "events": ("events_daily", lambda r: num(r["events"]), 0),
    "pageviews": ("events_daily", lambda r: num(r["pageviews"]), 0),
    "visitors": ("events_daily", lambda r: num(r["visitors"]), 0),
    "mobile_share": ("events_daily", lambda r: _share(r["mobile"], r["visitors"]), 1),
    "sessions": ("sessions_daily", lambda r: num(r["sessions"]), 0),
    "bounce_rate": ("sessions_daily", lambda r: num(r["bounce_rate"]) * 100, 1),
    "avg_visit": ("sessions_daily", lambda r: num(r["avg_duration"]), 0),
    "pages_per_visit": ("sessions_daily", lambda r: num(r["pages_per_visit"]), 1),
}


def _builtin_numbers(base: str, results: dict[tuple[str, int], Any], days: int) -> tuple[Any, Any, bool]:
    """(the number, the same number for the period before (None = nothing to compare with), is there nothing to show yet?)"""
    agg, sess, mobile = _first(results.get(("agg", days))), _first(results.get(("sessions", days))), _first(results.get(("mobile", days)))
    visits = int(num(sess.get("sessions")))
    prev_visits = int(num(sess.get("prev_sessions")))  # (an average of no visits would be a meaningless 0)
    if base in EVENT_TILES:
        return int(num(agg.get(base))), int(num(agg.get(f"prev_{base}"))), False
    if base == "sessions":
        return visits, prev_visits, False
    # An average or a share of NOTHING is not 0: with no visits in the period the card says so instead of showing "0%".
    if base == "bounce_rate":
        return round(num(sess.get("bounce_rate")) * 100, 1), round(num(sess.get("prev_bounce_rate")) * 100, 1) if prev_visits else None, not visits
    if base == "avg_visit":
        return round(num(sess.get("avg_duration"))), round(num(sess.get("prev_avg_duration"))) if prev_visits else None, not visits
    if base == "pages_per_visit":
        return round(num(sess.get("pages_per_visit")), 1), round(num(sess.get("prev_pages_per_visit")), 1) if prev_visits else None, not visits
    if base == "mobile_share":
        previous = round(_share(mobile.get("prev_mobile"), mobile.get("prev_total")), 1) if num(mobile.get("prev_total")) else None
        return round(_share(mobile.get("mobile"), mobile.get("total")), 1), previous, not num(mobile.get("total"))
    if base == "top_page":
        rows = results.get(("page", days)) or []
        return (rows[0]["path"] if rows else None) or "No data yet", None, not rows
    rows = results.get(("country", days)) or []  # top_country
    return (rows[0]["country"] if rows else None) or "No data yet", None, not rows


async def get_values(ph: PostHogClient, keys: list[str]) -> list[dict[str, Any]]:
    """The tile values for `keys`, in the same order. Only the queries these tiles need are run."""
    chosen = [describe(k) for k in keys]
    names = sorted({t.base[len("event:"):] for t in chosen if t.base.startswith("event:")})
    wanted: dict[int, set[str]] = {}  # period -> the built-in tiles shown for it
    for tile in chosen:
        if tile.base in BUILTIN_BY_BASE:
            wanted.setdefault(tile.days, set()).add(tile.base)

    async def run(query: str, values: dict[str, Any] | None, name: str, *, optional: bool = False) -> list[dict[str, Any]] | None:
        """`optional` ones are only for the little graphs: if they fail, the numbers still show (None = could not be read)."""
        try:
            return await ph.hogql(query, values, name=name)
        except AnalyticsError:
            if not optional:
                raise
            log.info("The daily numbers for the dashboard graphs could not be read (%s)", name)
            return None

    jobs: dict[tuple[str, int], Awaitable[list[dict[str, Any]] | None]] = {}
    for days, bases in wanted.items():
        values = {"days": days}
        if bases & EVENT_TILES:
            jobs[("agg", days)] = run(EVENTS_QUERY, values, "tiles:events_agg")
        if bases & SESSION_TILES:
            jobs[("sessions", days)] = run(SESSIONS_QUERY, values, "tiles:sessions")
        if "top_page" in bases:
            jobs[("page", days)] = run(TOP_PAGE_QUERY, values, "tiles:top_page")
        if "top_country" in bases:
            jobs[("country", days)] = run(TOP_COUNTRY_QUERY, values, "tiles:top_country")
        if "mobile_share" in bases:
            jobs[("mobile", days)] = run(MOBILE_QUERY, values, "tiles:mobile")
    all_bases = set().union(*wanted.values()) if wanted else set()
    if all_bases & (EVENT_TILES | {"mobile_share"}):
        jobs[("events_daily", 0)] = run(EVENTS_DAILY_QUERY, None, "tiles:events_daily", optional=True)
    session_days = max((d for d, bases in wanted.items() if bases & SESSION_TILES), default=None)
    if session_days is not None:  # (one daily query for all session tiles: as many days as the longest of them needs)
        jobs[("sessions_daily", 0)] = run(SESSIONS_DAILY_QUERY, {"days": session_days}, "tiles:sessions_daily", optional=True)
    if names:
        jobs[("counts", 0)] = run(EVENT_COUNTS_QUERY, {"names": names}, "tiles:events")
        jobs[("by_day", 0)] = run(EVENT_DAILY_QUERY, {"names": names}, "tiles:events_by_day", optional=True)
    results: dict[tuple[str, int], Any] = dict(zip(jobs, await asyncio.gather(*jobs.values())))

    today = _today(results.get(("events_daily", 0)), results.get(("sessions_daily", 0)), results.get(("by_day", 0)))
    counts = {r["event"]: r for r in results.get(("counts", 0)) or []}
    rows_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in results.get(("by_day", 0)) or []:
        rows_by_event.setdefault(row["event"], []).append(row)

    out = []
    for tile in chosen:
        if tile.base in BUILTIN_BY_BASE:
            value, before, empty = _builtin_numbers(tile.base, results, tile.days)
            if tile.base in DAILY:
                daily_key, value_of, digits = DAILY[tile.base]
                line = _series(results.get((daily_key, 0)), today, tile.days, value_of, digits)
            else:
                line = None  # (the two text tiles have neither a comparison nor a graph)
        else:
            name = tile.base[len("event:"):]
            row = counts.get(name)
            value = int(num(row.get("last_7" if tile.days == 7 else "last_30"))) if row else 0
            before = int(num(row.get("prev_7" if tile.days == 7 else "prev_30"))) if row else 0
            empty = False
            daily = results.get(("by_day", 0))
            line = _series(None if daily is None else rows_by_event.get(name, []), today, tile.days, lambda r: num(r["times"]))
        out.append({
            "key": tile.key, "base": tile.base, "period_keys": {d: period_key(tile.base, d) for d in PERIODS},
            "title": tile.title, "label": tile.label, "description": tile.description, "kind": tile.kind, "days": tile.days,
            "better": tile.better, "value": value, "previous": before, "series": line, "empty": empty,
        })
    return out
