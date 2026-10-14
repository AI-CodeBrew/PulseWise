"""KPI cards: pageviews, visitors, sessions, average session duration and bounce rate.

Each number comes with the previous period for comparison. For "last 30 days",
the previous period is the 30 days before that.
"""

import asyncio

from app.posthog_client import PostHogClient
from app.services.common import metric

# One pass over the pageview events covers BOTH periods (current and previous).
# countIf/uniqIf count only the rows where the condition is true.
# Visitors = unique persons (PostHog merges a person's devices once they are identified).
PAGEVIEWS_QUERY = """
SELECT
    countIf(timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1))           AS pageviews,
    countIf(timestamp <  toStartOfDay(now()) - toIntervalDay({days} - 1))           AS prev_pageviews,
    uniqIf(person_id, timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)) AS visitors,
    uniqIf(person_id, timestamp <  toStartOfDay(now()) - toIntervalDay({days} - 1)) AS prev_visitors
FROM events
WHERE event = '$pageview'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay(2 * {days} - 1)
"""

# The `sessions` table has one row per session, with ready-made columns:
#   $session_duration (seconds), $is_bounce (1 or 0), $pageview_count, ...
# We only count sessions with at least one pageview (real website visits).
SESSIONS_QUERY = """
SELECT
    countIf($start_timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)) AS sessions,
    countIf($start_timestamp <  toStartOfDay(now()) - toIntervalDay({days} - 1)) AS prev_sessions,
    avgIf($session_duration, $start_timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)) AS avg_duration,
    avgIf($session_duration, $start_timestamp <  toStartOfDay(now()) - toIntervalDay({days} - 1)) AS prev_avg_duration,
    avgIf($is_bounce, $start_timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)) AS bounce_rate,
    avgIf($is_bounce, $start_timestamp <  toStartOfDay(now()) - toIntervalDay({days} - 1)) AS prev_bounce_rate
FROM sessions
WHERE $start_timestamp >= toStartOfDay(now()) - toIntervalDay(2 * {days} - 1)
  AND $pageview_count > 0
"""


async def get_overview(ph: PostHogClient, days: int) -> dict:
    values = {"days": days}
    # Run both queries at the same time.
    pv_rows, s_rows = await asyncio.gather(
        ph.hogql(PAGEVIEWS_QUERY, values, name="overview:pageviews"),
        ph.hogql(SESSIONS_QUERY, values, name="overview:sessions"),
    )
    pv = pv_rows[0] if pv_rows else {}
    s = s_rows[0] if s_rows else {}

    bounce = s.get("bounce_rate") or 0
    prev_bounce = s.get("prev_bounce_rate") or 0

    return {
        "days": days,
        "pageviews": metric(pv.get("pageviews"), pv.get("prev_pageviews")),
        "visitors": metric(pv.get("visitors"), pv.get("prev_visitors")),
        "sessions": metric(s.get("sessions"), s.get("prev_sessions")),
        # In seconds.
        "avg_session_duration": metric(s.get("avg_duration"), s.get("prev_avg_duration")),
        # As a percentage (0-100). Lower is better.
        "bounce_rate": metric(bounce * 100, prev_bounce * 100, digits=1),
    }
