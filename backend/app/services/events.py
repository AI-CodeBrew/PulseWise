"""Live event feed and the list of custom (non-$) events."""

from app.config import settings
from app.posthog_client import PostHogClient
from app.services.persons import display_name

# Newest 50 events. Looks back 7 days so a quiet site still shows something.
LIVE_QUERY = """
SELECT
    uuid,
    event,
    timestamp,
    properties.$pathname           AS path,
    properties.$current_url        AS url,
    properties.$geoip_country_name AS country,
    properties.$geoip_city_name    AS city,
    properties.$device_type        AS device,
    properties.$browser            AS browser,
    distinct_id,
    person.properties.email        AS email,
    person.properties.name         AS name
FROM events
WHERE timestamp >= now() - toIntervalDay(7)
ORDER BY timestamp DESC
LIMIT 50
"""

# Custom events are the ones YOU send (nav_click, cta_click, ...). PostHog's own
# events all start with "$" ($pageview, $autocapture, ...).
CUSTOM_EVENTS_QUERY = """
SELECT
    event,
    count()         AS count,
    uniq(person_id) AS visitors,
    max(timestamp)  AS last_seen
FROM events
WHERE event NOT LIKE '$%'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
GROUP BY event
ORDER BY count DESC
LIMIT 200
"""


async def get_live_events(ph: PostHogClient) -> dict:
    # Short cache (10s) so the feed feels live but ten open tabs don't mean ten queries.
    rows = await ph.hogql(
        LIVE_QUERY, name="events:live", ttl=settings.live_cache_ttl_seconds
    )
    return {
        "results": [
            {
                "id": str(r["uuid"]),
                "event": r["event"],
                "timestamp": r["timestamp"],
                "path": r["path"],
                "url": r["url"],
                "country": r["country"],
                "city": r["city"],
                "device": r["device"],
                "browser": r["browser"],
                "person": display_name(r["email"], r["name"], r["distinct_id"]),
            }
            for r in rows
        ]
    }


async def get_custom_events(ph: PostHogClient, days: int) -> dict:
    rows = await ph.hogql(CUSTOM_EVENTS_QUERY, {"days": days}, name="events:custom")
    return {
        "days": days,
        "results": [
            {
                "event": r["event"],
                "count": r["count"],
                "visitors": r["visitors"],
                "last_seen": r["last_seen"],
            }
            for r in rows
        ],
    }
