"""Device type, browser and operating system breakdowns."""

import asyncio

from app.posthog_client import PostHogClient
from app.services.common import label

# Same query three times, only the property differs. The property name is part of the
# query text (it can't be a placeholder), so it is chosen from this fixed list and
# never from user input.
_TEMPLATE = """
SELECT
    properties.{prop}  AS name,
    count()            AS views,
    uniq(person_id)    AS visitors
FROM events
WHERE event = '$pageview'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay({{days}} - 1)
GROUP BY name
ORDER BY views DESC
LIMIT 20
"""

QUERIES = {
    "device_types": _TEMPLATE.format(prop="$device_type"),
    "browsers": _TEMPLATE.format(prop="$browser"),
    "operating_systems": _TEMPLATE.format(prop="$os"),
}


async def get_devices(ph: PostHogClient, days: int) -> dict:
    values = {"days": days}
    results = await asyncio.gather(
        *(ph.hogql(q, values, name=f"devices:{key}") for key, q in QUERIES.items())
    )
    out: dict = {"days": days}
    for key, rows in zip(QUERIES, results):
        out[key] = [
            {"name": label(r["name"]), "views": r["views"], "visitors": r["visitors"]}
            for r in rows
        ]
    return out
