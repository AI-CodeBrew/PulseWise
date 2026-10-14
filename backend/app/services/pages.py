"""Top pages by views and unique visitors."""

from app.posthog_client import PostHogClient
from app.services.common import label

TOP_PAGES_QUERY = """
SELECT
    properties.$pathname  AS path,
    count()               AS views,
    uniq(person_id)       AS visitors
FROM events
WHERE event = '$pageview'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
GROUP BY path
ORDER BY views DESC
LIMIT {limit}
"""


async def get_top_pages(ph: PostHogClient, days: int, limit: int) -> dict:
    rows = await ph.hogql(
        TOP_PAGES_QUERY, {"days": days, "limit": limit}, name="pages:top"
    )
    return {
        "days": days,
        "results": [
            {"path": label(r["path"]), "views": r["views"], "visitors": r["visitors"]}
            for r in rows
        ],
    }
