"""
The "My dashboard" tiles on the Overview page: small cards with one big number (like PostHog's dashboard tiles).

Each person picks which tiles they want (saved per user and website, see routers/dashboard.py). A tile is one of:
  * a BUILT-IN tile (Active users, Sessions, Pageviews, ...), listed in BUILTIN below, or
  * a tracked EVENT tile: how many times one of the website's own events (whatsapp_click, add_to_cart...) happened
    in the last 7 or 30 days. Its key is  event:<event name>:<7 or 30>.

Besides its number, every tile says how that number compares with the period just before it ("previous") and carries one
number per day for a little graph ("series"), so a card tells the story at a glance.

To keep PostHog usage low, only the queries needed by the SELECTED tiles run, and one query serves several tiles.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.posthog_client import AnalyticsError, PostHogClient
from app.services import events as events_service
from app.services.common import num

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tile:
    key: str
    label: str  # the short name on the card: "Sessions"
    description: str
    kind: str  # number | decimal | percent | duration | text
    group: str
    days: int = 7  # how many days the number covers
    better: str = "up"  # which way is good news: "up", or "down" (for "left after 1 page")

    @property
    def title(self) -> str:
        """The full name with its period, for the chooser and the box: "Sessions (last 7 days)"."""
        return f"{self.label} (last {self.days} days)"


BUILTIN: list[Tile] = [
    Tile("active_users_30d", "Active users", "Unique people who used your website in the last 30 days. A quick pulse on your overall reach.", "number", "Traffic", 30),
    Tile("sessions_7d", "Sessions", "Distinct visits in the last 7 days. A session groups everything one person does in a single sitting.", "number", "Traffic"),
    Tile("pageviews_7d", "Pageviews", "Total pages viewed in the last 7 days, repeat views included. The classic traffic-volume number.", "number", "Traffic"),
    Tile("visitors_7d", "Visitors", "Unique people who viewed at least one page in the last 7 days.", "number", "Traffic"),
    Tile("events_7d", "All events", "Everything your website recorded in the last 7 days: page views, clicks and your own tracked actions.", "number", "Traffic"),
    Tile("bounce_rate_7d", "Left after 1 page", "The share of visits in the last 7 days where the person saw one page and left. Lower is better.", "percent", "Engagement", better="down"),
    Tile("avg_visit_7d", "Average visit length", "How long a visit lasts on average, over the last 7 days.", "duration", "Engagement"),
    Tile("pages_per_visit_7d", "Pages per visit", "How many pages people look at in one visit, on average, over the last 7 days.", "decimal", "Engagement"),
    Tile("top_page_7d", "Most viewed page", "The page people looked at the most in the last 7 days.", "text", "Content"),
    Tile("top_country_7d", "Top country", "The country most of your visitors came from in the last 7 days.", "text", "Audience"),
    Tile("mobile_share_7d", "Visitors on a phone", "The share of your visitors in the last 7 days who used a phone or tablet.", "percent", "Audience"),
]
BUILTIN_BY_KEY = {t.key: t for t in BUILTIN}
DEFAULT_TILES = ["active_users_30d", "sessions_7d", "pageviews_7d"]  # pre-ticked the first time someone chooses
MAX_TILES = 24
EVENT_KEY = re.compile(r"^event:(?P<name>.{1,100}):(?P<days>7|30)$", re.DOTALL)

# Which tiles are answered by which query.
EVENT_TILES = {"active_users_30d", "events_7d", "pageviews_7d", "visitors_7d"}
SESSION_TILES = {"sessions_7d", "bounce_rate_7d", "avg_visit_7d", "pages_per_visit_7d"}


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


def validate_keys(keys: list[str]) -> list[str]:
    """The cleaned list (duplicates removed, order kept), or TileKeyError. Used when saving someone's choice."""
    if len(keys) > MAX_TILES * 2:
        raise TileKeyError(f"Please choose at most {MAX_TILES} tiles.")
    clean: list[str] = []
    for key in keys:
        if key not in BUILTIN_BY_KEY and parse_event_key(key) is None:
            raise TileKeyError("One of the chosen tiles doesn't exist.")
        if key not in clean:
            clean.append(key)
    if len(clean) > MAX_TILES:
        raise TileKeyError(f"Please choose at most {MAX_TILES} tiles.")
    return clean


# ---- queries (all values that come from users go in as {placeholders}, never into the text) ----------------

# "last 7 days" = today and the 6 days before; "the 7 days before that" ends where those begin.
SEVEN = "toStartOfDay(now()) - toIntervalDay(6)"
PREVIOUS_SEVEN = "toStartOfDay(now()) - toIntervalDay(13)"
THIRTY = "toStartOfDay(now()) - toIntervalDay(29)"
PREVIOUS_THIRTY = "toStartOfDay(now()) - toIntervalDay(59)"
PHONE = "properties.$device_type IN ('Mobile', 'Tablet')"

# Each total comes with the same number for the period before it ("prev_...").
EVENTS_QUERY = f"""
SELECT
    uniqIf(person_id, timestamp >= {THIRTY})                                                             AS active_users_30d,
    uniqIf(person_id, timestamp >= {PREVIOUS_THIRTY} AND timestamp < {THIRTY})                           AS prev_active_users_30d,
    countIf(timestamp >= {SEVEN})                                                                        AS events_7d,
    countIf(timestamp >= {PREVIOUS_SEVEN} AND timestamp < {SEVEN})                                       AS prev_events_7d,
    countIf(event = '$pageview' AND timestamp >= {SEVEN})                                                AS pageviews_7d,
    countIf(event = '$pageview' AND timestamp >= {PREVIOUS_SEVEN} AND timestamp < {SEVEN})               AS prev_pageviews_7d,
    uniqIf(person_id, event = '$pageview' AND timestamp >= {SEVEN})                                      AS visitors_7d,
    uniqIf(person_id, event = '$pageview' AND timestamp >= {PREVIOUS_SEVEN} AND timestamp < {SEVEN})     AS prev_visitors_7d
FROM events
WHERE timestamp >= {PREVIOUS_THIRTY}
"""

# One number per day for the little graphs (the last 30 days; the 7-day tiles use the last 7 of them).
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
    countIf($start_timestamp >= {SEVEN})                         AS sessions,
    avgIf($session_duration, $start_timestamp >= {SEVEN})        AS avg_duration,
    avgIf($is_bounce, $start_timestamp >= {SEVEN})               AS bounce_rate,
    avgIf($pageview_count, $start_timestamp >= {SEVEN})          AS pages_per_visit,
    countIf($start_timestamp < {SEVEN})                          AS prev_sessions,
    avgIf($session_duration, $start_timestamp < {SEVEN})         AS prev_avg_duration,
    avgIf($is_bounce, $start_timestamp < {SEVEN})                AS prev_bounce_rate,
    avgIf($pageview_count, $start_timestamp < {SEVEN})           AS prev_pages_per_visit
FROM sessions
WHERE $start_timestamp >= {PREVIOUS_SEVEN} AND $pageview_count > 0
"""

SESSIONS_DAILY_QUERY = f"""
SELECT
    toDate($start_timestamp) AS day, toDate(now()) AS today,
    count()                  AS sessions,
    avg($session_duration)   AS avg_duration,
    avg($is_bounce)          AS bounce_rate,
    avg($pageview_count)     AS pages_per_visit
FROM sessions
WHERE $start_timestamp >= {SEVEN} AND $pageview_count > 0
GROUP BY day
ORDER BY day
"""

TOP_PAGE_QUERY = f"""
SELECT properties.$pathname AS path, count() AS views
FROM events
WHERE event = '$pageview' AND timestamp >= {SEVEN}
GROUP BY path
ORDER BY views DESC
LIMIT 1
"""

TOP_COUNTRY_QUERY = f"""
SELECT properties.$geoip_country_name AS country, uniq(person_id) AS visitors
FROM events
WHERE event = '$pageview' AND timestamp >= {SEVEN} AND properties.$geoip_country_name IS NOT NULL
GROUP BY country
ORDER BY visitors DESC
LIMIT 1
"""

MOBILE_QUERY = f"""
SELECT
    uniqIf(person_id, {PHONE} AND timestamp >= {SEVEN})   AS mobile,
    uniqIf(person_id, timestamp >= {SEVEN})               AS total,
    uniqIf(person_id, {PHONE} AND timestamp < {SEVEN})    AS prev_mobile,
    uniqIf(person_id, timestamp < {SEVEN})                AS prev_total
FROM events
WHERE event = '$pageview' AND timestamp >= {PREVIOUS_SEVEN}
"""

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


async def get_catalog(ph: PostHogClient) -> dict[str, Any]:
    """Everything a person can choose from: the built-in tiles, plus one entry per tracked event of this website."""
    tracked = await events_service.get_custom_events(ph, 30)
    return {
        "tiles": [{"key": t.key, "title": t.title, "description": t.description, "kind": t.kind, "group": t.group} for t in BUILTIN],
        "events": [{"event": r["event"], "count": r["count"]} for r in tracked["results"][:100]],
    }


def describe(key: str) -> Tile:
    """The title, description and kind of a tile (built-in or tracked event)."""
    if key in BUILTIN_BY_KEY:
        return BUILTIN_BY_KEY[key]
    name, days = parse_event_key(key) or ("?", 7)
    return Tile(key, name, f"How many times “{name}” happened on your website in the last {days} days.", "number", "Events", days)


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


async def get_values(ph: PostHogClient, keys: list[str]) -> list[dict[str, Any]]:
    """The tile values for `keys`, in the same order. Only the queries these tiles need are run."""
    wanted = set(keys)
    event_keys = {k: parse_event_key(k) for k in keys if k not in BUILTIN_BY_KEY}
    names = sorted({parsed[0] for parsed in event_keys.values() if parsed})

    async def maybe(needed: set[str], query: str, name: str, *, optional: bool = False) -> list[dict[str, Any]] | None:
        """Run `query` if one of the chosen tiles needs it. `optional` ones are only for the little graphs: if they fail,
        the numbers still show (None = could not be read)."""
        if not wanted & needed:
            return []
        try:
            return await ph.hogql(query, None, name=name)
        except AnalyticsError:
            if not optional:
                raise
            log.info("The daily numbers for the dashboard graphs could not be read (%s)", name)
            return None

    async def by_name(query: str, name: str, *, optional: bool = False) -> list[dict[str, Any]] | None:
        if not names:
            return []
        try:
            return await ph.hogql(query, {"names": names}, name=name)
        except AnalyticsError:
            if not optional:
                raise
            return None

    events_rows, events_daily, sessions_rows, sessions_daily, page_rows, country_rows, mobile_rows, event_rows, event_daily = await asyncio.gather(
        maybe(EVENT_TILES, EVENTS_QUERY, "tiles:events_agg"),
        maybe(EVENT_TILES | {"mobile_share_7d"}, EVENTS_DAILY_QUERY, "tiles:events_daily", optional=True),
        maybe(SESSION_TILES, SESSIONS_QUERY, "tiles:sessions"),
        maybe(SESSION_TILES, SESSIONS_DAILY_QUERY, "tiles:sessions_daily", optional=True),
        maybe({"top_page_7d"}, TOP_PAGE_QUERY, "tiles:top_page"),
        maybe({"top_country_7d"}, TOP_COUNTRY_QUERY, "tiles:top_country"),
        maybe({"mobile_share_7d"}, MOBILE_QUERY, "tiles:mobile"),
        by_name(EVENT_COUNTS_QUERY, "tiles:events"),
        by_name(EVENT_DAILY_QUERY, "tiles:events_by_day", optional=True),
    )
    agg, sess, mobile = (events_rows or [{}])[0], (sessions_rows or [{}])[0], (mobile_rows or [{}])[0]
    counts = {r["event"]: r for r in event_rows or []}
    today = _today(events_daily, sessions_daily, event_daily)

    # Each number, the same number for the period before it (None = nothing to compare with) and one number per day.
    prev_sessions = int(num(sess.get("prev_sessions")))  # (an average of no visits would be a meaningless 0)
    values: dict[str, Any] = {
        "active_users_30d": int(num(agg.get("active_users_30d"))),
        "events_7d": int(num(agg.get("events_7d"))),
        "pageviews_7d": int(num(agg.get("pageviews_7d"))),
        "visitors_7d": int(num(agg.get("visitors_7d"))),
        "sessions_7d": int(num(sess.get("sessions"))),
        "bounce_rate_7d": round(num(sess.get("bounce_rate")) * 100, 1),
        "avg_visit_7d": round(num(sess.get("avg_duration"))),
        "pages_per_visit_7d": round(num(sess.get("pages_per_visit")), 1),
        "top_page_7d": (page_rows[0]["path"] if page_rows else None) or "No data yet",
        "top_country_7d": (country_rows[0]["country"] if country_rows else None) or "No data yet",
        "mobile_share_7d": round(_share(mobile.get("mobile"), mobile.get("total")), 1),
    }
    previous: dict[str, Any] = {
        "active_users_30d": int(num(agg.get("prev_active_users_30d"))),
        "events_7d": int(num(agg.get("prev_events_7d"))),
        "pageviews_7d": int(num(agg.get("prev_pageviews_7d"))),
        "visitors_7d": int(num(agg.get("prev_visitors_7d"))),
        "sessions_7d": prev_sessions,
        "bounce_rate_7d": round(num(sess.get("prev_bounce_rate")) * 100, 1) if prev_sessions else None,
        "avg_visit_7d": round(num(sess.get("prev_avg_duration"))) if prev_sessions else None,
        "pages_per_visit_7d": round(num(sess.get("prev_pages_per_visit")), 1) if prev_sessions else None,
        "mobile_share_7d": round(_share(mobile.get("prev_mobile"), mobile.get("prev_total")), 1) if num(mobile.get("prev_total")) else None,
    }
    series: dict[str, list[float] | None] = {
        "active_users_30d": _series(events_daily, today, 30, lambda r: num(r["active"])),
        "events_7d": _series(events_daily, today, 7, lambda r: num(r["events"])),
        "pageviews_7d": _series(events_daily, today, 7, lambda r: num(r["pageviews"])),
        "visitors_7d": _series(events_daily, today, 7, lambda r: num(r["visitors"])),
        "mobile_share_7d": _series(events_daily, today, 7, lambda r: _share(r["mobile"], r["visitors"]), 1),
        "sessions_7d": _series(sessions_daily, today, 7, lambda r: num(r["sessions"])),
        "bounce_rate_7d": _series(sessions_daily, today, 7, lambda r: num(r["bounce_rate"]) * 100, 1),
        "avg_visit_7d": _series(sessions_daily, today, 7, lambda r: num(r["avg_duration"])),
        "pages_per_visit_7d": _series(sessions_daily, today, 7, lambda r: num(r["pages_per_visit"]), 1),
    }  # (the two "text" tiles, top page and top country, have neither a comparison nor a graph)
    # An average or a share of NOTHING is not 0: with no visits in the period the card says so instead of showing "0%".
    no_visits, no_visitors = not int(num(sess.get("sessions"))), not num(mobile.get("total"))
    empty = {
        "bounce_rate_7d": no_visits, "avg_visit_7d": no_visits, "pages_per_visit_7d": no_visits, "mobile_share_7d": no_visitors,
        "top_page_7d": not page_rows, "top_country_7d": not country_rows,
    }
    rows_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in event_daily or []:
        rows_by_event.setdefault(row["event"], []).append(row)

    out = []
    for key in keys:
        tile = describe(key)
        if key in BUILTIN_BY_KEY:
            value, before, line = values[key], previous.get(key), series.get(key)
        else:
            parsed = event_keys.get(key)
            days = parsed[1] if parsed else 7
            row = counts.get(parsed[0]) if parsed else None
            value = int(num(row.get("last_7" if days == 7 else "last_30"))) if row else 0
            before = int(num(row.get("prev_7" if days == 7 else "prev_30"))) if row else 0
            line = _series(None if event_daily is None else rows_by_event.get(parsed[0] if parsed else "", []), today, days, lambda r: num(r["times"]))
        out.append({
            "key": key, "title": tile.title, "label": tile.label, "description": tile.description, "kind": tile.kind, "days": tile.days,
            "better": tile.better, "value": value, "previous": before, "series": line, "empty": empty.get(key, False),
        })
    return out
