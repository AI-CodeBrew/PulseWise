"""Where visitors are: countries and cities.

PostHog adds $geoip_* properties to each event from the visitor's IP address.
"""

import asyncio

from app.posthog_client import PostHogClient
from app.services.common import label

COUNTRIES_QUERY = """
SELECT
    properties.$geoip_country_code AS code,
    properties.$geoip_country_name AS country,
    count()                        AS views,
    uniq(person_id)                AS visitors
FROM events
WHERE event = '$pageview'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
GROUP BY code, country
ORDER BY views DESC
LIMIT 50
"""

CITIES_QUERY = """
SELECT
    properties.$geoip_city_name    AS city,
    properties.$geoip_country_name AS country,
    count()                        AS views,
    uniq(person_id)                AS visitors
FROM events
WHERE event = '$pageview'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
GROUP BY city, country
ORDER BY views DESC
LIMIT 50
"""


async def get_geo(ph: PostHogClient, days: int) -> dict:
    values = {"days": days}
    countries, cities = await asyncio.gather(
        ph.hogql(COUNTRIES_QUERY, values, name="geo:countries"),
        ph.hogql(CITIES_QUERY, values, name="geo:cities"),
    )
    return {
        "days": days,
        "countries": [
            {
                "code": r["code"],
                "country": label(r["country"]),
                "views": r["views"],
                "visitors": r["visitors"],
            }
            for r in countries
        ],
        "cities": [
            {
                "city": label(r["city"]),
                "country": label(r["country"]),
                "views": r["views"],
                "visitors": r["visitors"],
            }
            for r in cities
        ],
    }
