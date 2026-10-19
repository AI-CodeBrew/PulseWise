"""
The "My dashboard" tiles on the Overview page: small cards with one big number (like PostHog's dashboard tiles).

Each person picks which tiles they want (saved per user and website, see routers/dashboard.py). A tile is one of:
  * a BUILT-IN tile (Active users, Sessions, Pageviews, ...), listed in BUILTIN below, or
  * a tracked EVENT tile: how many times one of the website's own events (whatsapp_click, add_to_cart...) happened
    in the last 7 or 30 days. Its key is  event:<event name>:<7 or 30>.

To keep PostHog usage low, only the queries needed by the SELECTED tiles run, and one query serves several tiles.
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from app.posthog_client import PostHogClient
from app.services import events as events_service
from app.services.common import num


@dataclass(frozen=True)
class Tile:
    key: str
    title: str
    description: str
    kind: str  # number | decimal | percent | duration | text
    group: str


BUILTIN: list[Tile] = [
    Tile("active_users_30d", "Active users (last 30 days)", "Unique people who used your website in the last 30 days. A quick pulse on your overall reach.", "number", "Traffic"),
    Tile("sessions_7d", "Sessions (last 7 days)", "Distinct visits in the last 7 days. A session groups everything one person does in a single sitting.", "number", "Traffic"),
    Tile("pageviews_7d", "Pageviews (last 7 days)", "Total pages viewed in the last 7 days, repeat views included. The classic traffic-volume number.", "number", "Traffic"),
    Tile("visitors_7d", "Visitors (last 7 days)", "Unique people who viewed at least one page in the last 7 days.", "number", "Traffic"),
    Tile("events_7d", "All events (last 7 days)", "Everything your website recorded in the last 7 days: page views, clicks and your own tracked actions.", "number", "Traffic"),
    Tile("bounce_rate_7d", "Left after 1 page (last 7 days)", "The share of visits in the last 7 days where the person saw one page and left. Lower is better.", "percent", "Engagement"),
    Tile("avg_visit_7d", "Average visit length (last 7 days)", "How long a visit lasts on average, over the last 7 days.", "duration", "Engagement"),
    Tile("pages_per_visit_7d", "Pages per visit (last 7 days)", "How many pages people look at in one visit, on average, over the last 7 days.", "decimal", "Engagement"),
    Tile("top_page_7d", "Most viewed page (last 7 days)", "The page people looked at the most in the last 7 days.", "text", "Content"),
    Tile("top_country_7d", "Top country (last 7 days)", "The country most of your visitors came from in the last 7 days.", "text", "Audience"),
    Tile("mobile_share_7d", "Visitors on a phone (last 7 days)", "The share of your visitors in the last 7 days who used a phone or tablet.", "percent", "Audience"),
]
BUILTIN_BY_KEY = {t.key: t for t in BUILTIN}
DEFAULT_TILES = ["active_users_30d", "sessions_7d", "pageviews_7d"]  # pre-ticked the first time someone chooses
MAX_TILES = 24
EVENT_KEY = re.compile(r"^event:(?P<name>.{1,100}):(?P<days>7|30)$", re.DOTALL)


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

SEVEN = "toStartOfDay(now()) - toIntervalDay(6)"  # "last 7 days" = today and the 6 days before
THIRTY = "toStartOfDay(now()) - toIntervalDay(29)"

EVENTS_QUERY = f"""
SELECT
    uniq(person_id)                                                          AS active_users_30d,
    countIf(timestamp >= {SEVEN})                                            AS events_7d,
    countIf(event = '$pageview' AND timestamp >= {SEVEN})                    AS pageviews_7d,
    uniqIf(person_id, event = '$pageview' AND timestamp >= {SEVEN})          AS visitors_7d
FROM events
WHERE timestamp >= {THIRTY}
"""

SESSIONS_QUERY = f"""
SELECT
    count()                 AS sessions,
    avg($session_duration)  AS avg_duration,
    avg($is_bounce)         AS bounce_rate,
    avg($pageview_count)    AS pages_per_visit
FROM sessions
WHERE $start_timestamp >= {SEVEN} AND $pageview_count > 0
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
SELECT uniqIf(person_id, properties.$device_type IN ('Mobile', 'Tablet')) AS mobile, uniq(person_id) AS total
FROM events
WHERE event = '$pageview' AND timestamp >= {SEVEN}
"""

EVENT_COUNTS_QUERY = f"""
SELECT event, countIf(timestamp >= {SEVEN}) AS last_7, count() AS last_30
FROM events
WHERE event IN {{names}} AND timestamp >= {THIRTY}
GROUP BY event
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
    return Tile(key, f"{name} (last {days} days)", f"How many times “{name}” happened on your website in the last {days} days.", "number", "Events")


async def get_values(ph: PostHogClient, keys: list[str]) -> list[dict[str, Any]]:
    """The tile values for `keys`, in the same order. Only the queries these tiles need are run."""
    wanted = set(keys)
    event_keys = {k: parse_event_key(k) for k in keys if k not in BUILTIN_BY_KEY}
    names = sorted({parsed[0] for parsed in event_keys.values() if parsed})

    async def maybe(needed: set[str], query: str, name: str, values: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not wanted & needed:  # none of the chosen tiles needs this query
            return []
        return await ph.hogql(query, values, name=name)

    events_rows, sessions_rows, page_rows, country_rows, mobile_rows, event_rows = await asyncio.gather(
        maybe({"active_users_30d", "events_7d", "pageviews_7d", "visitors_7d"}, EVENTS_QUERY, "tiles:events_agg"),
        maybe({"sessions_7d", "bounce_rate_7d", "avg_visit_7d", "pages_per_visit_7d"}, SESSIONS_QUERY, "tiles:sessions"),
        maybe({"top_page_7d"}, TOP_PAGE_QUERY, "tiles:top_page"),
        maybe({"top_country_7d"}, TOP_COUNTRY_QUERY, "tiles:top_country"),
        maybe({"mobile_share_7d"}, MOBILE_QUERY, "tiles:mobile"),
        ph.hogql(EVENT_COUNTS_QUERY, {"names": names}, name="tiles:events") if names else _nothing(),
    )
    agg, sess = (events_rows or [{}])[0], (sessions_rows or [{}])[0]
    mobile = (mobile_rows or [{}])[0]
    counts = {r["event"]: r for r in event_rows}

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
        "mobile_share_7d": round(num(mobile.get("mobile")) / num(mobile.get("total")) * 100, 1) if num(mobile.get("total")) else 0.0,
    }

    out = []
    for key in keys:
        tile = describe(key)
        if key in BUILTIN_BY_KEY:
            value = values[key]
        else:
            parsed = event_keys.get(key)
            row = counts.get(parsed[0]) if parsed else None
            value = int(num(row["last_7" if parsed and parsed[1] == 7 else "last_30"])) if row else 0
        out.append({"key": key, "title": tile.title, "description": tile.description, "kind": tile.kind, "value": value})
    return out


async def _nothing() -> list[dict[str, Any]]:
    return []
