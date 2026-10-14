"""Where visitors come from: referring domains, UTM sources and channel types.

All three are read from the `sessions` table. PostHog works out each session's
entry referrer, UTM tags and channel (Direct, Organic Search, Paid Social, ...)
for us, so we only group and count.
"""

import asyncio

from app.posthog_client import PostHogClient
from app.services.common import label

# {column} can't be a placeholder (placeholders are values, not column names), so the
# three queries are written out. They are fixed text; no user input is in them.
_WINDOW = """
FROM sessions
WHERE $start_timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
  AND $pageview_count > 0
"""

REFERRERS_QUERY = (
    """
SELECT $entry_referring_domain AS name, count() AS sessions, uniq(distinct_id) AS visitors
"""
    + _WINDOW
    + "GROUP BY name ORDER BY sessions DESC LIMIT 50"
)

UTM_QUERY = (
    """
SELECT $entry_utm_source AS name, count() AS sessions, uniq(distinct_id) AS visitors
"""
    + _WINDOW
    + "AND $entry_utm_source IS NOT NULL AND $entry_utm_source != '' "
    + "GROUP BY name ORDER BY sessions DESC LIMIT 50"
)

CHANNELS_QUERY = (
    """
SELECT $channel_type AS name, count() AS sessions, uniq(distinct_id) AS visitors
"""
    + _WINDOW
    + "GROUP BY name ORDER BY sessions DESC LIMIT 50"
)


def _shape(rows: list[dict], empty: str) -> list[dict]:
    out = []
    for r in rows:
        name = label(r["name"], empty)
        # PostHog stores "no referrer" as "$direct".
        out.append(
            {
                "name": "Direct" if name == "$direct" else name,
                "sessions": r["sessions"],
                "visitors": r["visitors"],
            }
        )
    return out


async def get_sources(ph: PostHogClient, days: int) -> dict:
    values = {"days": days}
    referrers, utm, channels = await asyncio.gather(
        ph.hogql(REFERRERS_QUERY, values, name="sources:referrers"),
        ph.hogql(UTM_QUERY, values, name="sources:utm"),
        ph.hogql(CHANNELS_QUERY, values, name="sources:channels"),
    )
    return {
        "days": days,
        "referrers": _shape(referrers, "Direct"),
        "utm_sources": _shape(utm, "(none)"),
        "channels": _shape(channels, "(unknown)"),
    }
