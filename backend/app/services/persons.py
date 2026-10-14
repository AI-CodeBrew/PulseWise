"""People: a paginated list, and one person's profile with their recent events."""

import asyncio
import json

from fastapi import HTTPException

from app.params import decode_time_cursor, encode_time_cursor
from app.posthog_client import PostHogClient

# One row per person, built from their events in the selected period.
# `first_seen` / `last_seen` / `events` therefore describe activity IN THIS PERIOD.
# HAVING filters AFTER grouping, which is what the keyset cursor needs.
PERSONS_QUERY = """
SELECT
    person_id,
    min(timestamp)                AS first_seen,
    max(timestamp)                AS last_seen,
    count()                       AS events,
    countIf(event = '$pageview')  AS pageviews,
    any(person.properties.email)  AS email,
    any(person.properties.name)   AS name,
    argMax(distinct_id, timestamp) AS distinct_id
FROM events
WHERE timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
GROUP BY person_id
{cursor_filter}
ORDER BY last_seen DESC
LIMIT {limit}
"""

PERSON_QUERY = """
SELECT id, created_at, properties, is_identified
FROM persons
WHERE id = {person_id}
LIMIT 1
"""

# `person_id = toUUID({...})` because person_id is a UUID column and our value is text.
PERSON_EVENTS_QUERY = """
SELECT
    uuid,
    event,
    timestamp,
    properties.$pathname AS path,
    properties.$current_url AS url,
    $session_id AS session_id,
    distinct_id
FROM events
WHERE person_id = toUUID({person_id})
  AND timestamp >= now() - toIntervalDay(120)
ORDER BY timestamp DESC
LIMIT 100
"""


def display_name(email, name, distinct_id) -> str:
    """The best human-readable label we have for a person."""
    return email or name or (str(distinct_id) if distinct_id else "Anonymous visitor")


async def list_persons(
    ph: PostHogClient, days: int, limit: int, cursor: str | None
) -> dict:
    before = decode_time_cursor(cursor)
    values: dict = {"days": days, "limit": limit + 1}
    cursor_filter = ""
    if before:
        cursor_filter = "HAVING max(timestamp) < toDateTime64({before}, 6, 'UTC')"
        values["before"] = before

    query = PERSONS_QUERY.replace("{cursor_filter}", cursor_filter)
    rows = await ph.hogql(query, values, name="persons:list")

    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "days": days,
        "results": [
            {
                "id": str(r["person_id"]),
                "name": display_name(r["email"], r["name"], r["distinct_id"]),
                "email": r["email"],
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "events": r["events"],
                "pageviews": r["pageviews"],
            }
            for r in rows
        ],
        "next_cursor": encode_time_cursor(rows[-1]["last_seen"]) if has_more else None,
    }


async def get_person(ph: PostHogClient, person_id: str) -> dict:
    values = {"person_id": person_id}
    person_rows, events = await asyncio.gather(
        ph.hogql(PERSON_QUERY, values, name="persons:detail"),
        ph.hogql(PERSON_EVENTS_QUERY, values, name="persons:events"),
    )
    if not person_rows:
        raise HTTPException(status_code=404, detail="Person not found")
    person = person_rows[0]

    # `properties` comes back as a JSON string. Parse it and drop the empty values
    # (PostHog stores lots of null ad-click ids like gclid/fbclid).
    try:
        raw = json.loads(person["properties"] or "{}")
    except ValueError:
        raw = {}
    properties = {k: v for k, v in raw.items() if v not in (None, "")}

    # The persons table has no distinct_id; take it from their latest event,
    # so the name falls back to the same ID the People list shows.
    distinct_id = events[0]["distinct_id"] if events else None

    return {
        "id": str(person["id"]),
        "name": display_name(properties.get("email"), properties.get("name"), distinct_id),
        "created_at": person["created_at"],
        "is_identified": bool(person["is_identified"]),
        "properties": properties,
        "events": [
            {
                "id": str(e["uuid"]),
                "event": e["event"],
                "timestamp": e["timestamp"],
                "path": e["path"],
                "url": e["url"],
                "session_id": e["session_id"],
            }
            for e in events
        ],
    }
