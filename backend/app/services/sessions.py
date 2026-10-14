"""Sessions: a paginated list, and the event timeline of one session."""

import asyncio

from fastapi import HTTPException

from app.params import decode_time_cursor, encode_time_cursor
from app.posthog_client import PostHogClient
from app.services.common import label

# The part of the query that changes when there is a cursor is fixed text (no user input);
# the cursor VALUE itself still goes through a {before} placeholder.
SESSIONS_QUERY = """
SELECT
    session_id,
    $start_timestamp        AS started_at,
    $end_timestamp          AS ended_at,
    $session_duration       AS duration,
    $entry_pathname         AS entry_page,
    $end_pathname           AS exit_page,
    $pageview_count         AS pageviews,
    $channel_type           AS channel,
    $is_bounce              AS is_bounce,
    $entry_referring_domain AS referrer,
    distinct_id
FROM sessions
WHERE $start_timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
  AND $pageview_count > 0
  {cursor_filter}
ORDER BY $start_timestamp DESC
LIMIT {limit}
"""

# One session's summary (shown at the top of the timeline page).
SESSION_QUERY = """
SELECT
    session_id,
    $start_timestamp        AS started_at,
    $end_timestamp          AS ended_at,
    $session_duration       AS duration,
    $entry_pathname         AS entry_page,
    $end_pathname           AS exit_page,
    $pageview_count         AS pageviews,
    $channel_type           AS channel,
    $is_bounce              AS is_bounce,
    $entry_referring_domain AS referrer,
    distinct_id
FROM sessions
WHERE session_id = {session_id}
  AND $start_timestamp >= now() - toIntervalDay(120)
LIMIT 1
"""

# Every event of the session, oldest first. The time bound makes the query cheaper.
SESSION_EVENTS_QUERY = """
SELECT
    uuid,
    event,
    timestamp,
    properties.$pathname    AS path,
    properties.$current_url AS url,
    properties.$event_type  AS event_type
FROM events
WHERE $session_id = {session_id}
  AND timestamp >= now() - toIntervalDay(120)
ORDER BY timestamp ASC
LIMIT 1000
"""


async def list_sessions(
    ph: PostHogClient, days: int, limit: int, cursor: str | None
) -> dict:
    before = decode_time_cursor(cursor)
    values: dict = {"days": days, "limit": limit + 1}  # +1 row tells us if there is a next page
    cursor_filter = ""
    if before:
        # Keyset pagination: "sessions that started before the last one you saw".
        # (PostHog rejects OFFSET for personal API keys.)
        cursor_filter = "AND $start_timestamp < toDateTime64({before}, 6, 'UTC')"
        values["before"] = before

    # str.replace (not .format) because the query is full of other {placeholders}.
    query = SESSIONS_QUERY.replace("{cursor_filter}", cursor_filter)
    rows = await ph.hogql(query, values, name="sessions:list")

    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "days": days,
        "results": [_shape_session(r) for r in rows],
        "next_cursor": encode_time_cursor(rows[-1]["started_at"]) if has_more else None,
    }


def _shape_session(r: dict) -> dict:
    referrer = label(r.get("referrer"), "Direct")
    return {
        "session_id": r["session_id"],
        "started_at": r["started_at"],
        "ended_at": r.get("ended_at"),
        "duration": int(r["duration"] or 0),  # seconds
        "entry_page": label(r["entry_page"]),
        "exit_page": label(r["exit_page"]),
        "pageviews": r["pageviews"],
        "channel": label(r["channel"]),
        "referrer": "Direct" if referrer == "$direct" else referrer,
        "is_bounce": bool(r["is_bounce"]),
        "visitor": r.get("distinct_id"),
    }


async def get_session(ph: PostHogClient, session_id: str) -> dict:
    values = {"session_id": session_id}
    summary_rows, events = await asyncio.gather(
        ph.hogql(SESSION_QUERY, values, name="sessions:detail"),
        ph.hogql(SESSION_EVENTS_QUERY, values, name="sessions:events"),
    )
    if not summary_rows and not events:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session": _shape_session(summary_rows[0]) if summary_rows else None,
        "events": [
            {
                "id": str(e["uuid"]),
                "event": e["event"],
                "timestamp": e["timestamp"],
                "path": e["path"],
                "url": e["url"],
                "event_type": e["event_type"],
            }
            for e in events
        ],
    }
