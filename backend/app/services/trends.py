"""Daily pageviews and unique visitors, for the line chart."""

from datetime import date, timedelta

from app.posthog_client import PostHogClient

# toDate() returns the day in the project's timezone, e.g. "2026-10-10".
# `today` is the same in every row. It tells us "today" in the project timezone, so
# we can fill in the days that had no data.
TRENDS_QUERY = """
SELECT
    toDate(timestamp)  AS day,
    count()            AS pageviews,
    uniq(person_id)    AS visitors,
    toDate(now())      AS today
FROM events
WHERE event = '$pageview'
  AND timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
GROUP BY day
ORDER BY day
"""


async def get_trends(ph: PostHogClient, days: int) -> dict:
    rows = await ph.hogql(TRENDS_QUERY, {"days": days}, name="trends:daily")
    by_day = {str(r["day"]): r for r in rows}

    # A day with no pageviews has no row, but the chart needs every day (with 0).
    today = date.fromisoformat(str(rows[0]["today"])) if rows else date.today()
    series = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        row = by_day.get(day, {})
        series.append(
            {
                "date": day,
                "pageviews": int(row.get("pageviews", 0)),
                "visitors": int(row.get("visitors", 0)),
            }
        )
    return {"days": days, "series": series}
