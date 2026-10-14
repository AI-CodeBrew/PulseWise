"""
Phase 1 - PostHog connection test.

Run:  python test_connection.py

What it does:
  1. Reads POSTHOG_HOST, POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY from backend/.env
  2. Sends ONE HogQL query to the PostHog Query API:
        POST {host}/api/projects/{project_id}/query/
  3. Prints the number of $pageview events per day for the last 7 days,
     or a plain-English explanation of what went wrong.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load backend/.env no matter which folder you run the script from.
load_dotenv(Path(__file__).parent / ".env")


def fail(message: str) -> None:
    """Print an error message and stop the script with exit code 1."""
    print(f"\n[FAILED] {message}\n")
    sys.exit(1)


def read_settings() -> tuple[str, str, str]:
    """Read and sanity-check the three settings from .env."""
    host = os.getenv("POSTHOG_HOST", "").strip().rstrip("/")
    project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
    api_key = os.getenv("POSTHOG_PERSONAL_API_KEY", "").strip()

    missing = [
        name
        for name, value in [
            ("POSTHOG_HOST", host),
            ("POSTHOG_PROJECT_ID", project_id),
            ("POSTHOG_PERSONAL_API_KEY", api_key),
        ]
        if not value
    ]
    if missing:
        fail(
            f"Missing in backend/.env: {', '.join(missing)}\n"
            "         Copy .env.example to .env and fill in the values."
        )
    if not host.startswith("https://"):
        fail(f"POSTHOG_HOST must start with https:// (got '{host}').")
    if not project_id.isdigit():
        fail(
            f"POSTHOG_PROJECT_ID must be a number (got '{project_id}').\n"
            "         Look in the PostHog URL: /project/<number>/..."
        )
    if not api_key.startswith("phx_"):
        # Project API keys start with "phc_" - those can only SEND data, not read it.
        print(
            "[WARNING] Personal API keys usually start with 'phx_'. If yours starts with\n"
            "          'phc_', that is the PROJECT key (write-only) - it cannot read data.\n"
        )
    return host, project_id, api_key


def mask(key: str) -> str:
    """Show only the start and end of the key, so it is never printed in full."""
    return f"{key[:6]}...{key[-4:]}" if len(key) > 12 else "***"


# HogQL query. {event} is a *placeholder*: PostHog fills it in from the "values"
# dict as a safe constant, so values are never glued into the SQL text by us.
# toStartOfDay(now()) - 6 days  =>  exactly the last 7 calendar days, including today.
QUERY = """
SELECT
    toDate(timestamp) AS day,
    count() AS pageviews
FROM events
WHERE event = {event}
  AND timestamp >= toStartOfDay(now()) - INTERVAL 6 DAY
GROUP BY day
ORDER BY day
"""


def explain_http_error(response: httpx.Response, host: str, project_id: str) -> str:
    """Turn a PostHog error response into a human-friendly message."""
    try:
        detail = response.json().get("detail", "")
    except ValueError:
        detail = response.text[:300]

    other_region = (
        "https://eu.posthog.com" if "us." in host else "https://us.posthog.com"
    )
    status = response.status_code

    if status == 401:
        return (
            "401 Unauthorized - PostHog did not accept the API key.\n"
            "         Possible causes:\n"
            "         - The key is mistyped, deleted or expired.\n"
            f"         - Wrong region: your account may live on {other_region}.\n"
            "           (US and EU are separate clouds - a US key does not work on EU.)\n"
            f"         PostHog said: {detail}"
        )
    if status == 403:
        return (
            "403 Forbidden - the key is valid but is not allowed to do this.\n"
            "         Possible causes:\n"
            "         - The key is missing the 'Query: Read' scope.\n"
            f"         - The key is restricted to other projects/orgs (not project {project_id}).\n"
            f"         PostHog said: {detail}"
        )
    if status == 404:
        return (
            f"404 Not Found - project {project_id} was not found on {host}.\n"
            "         Possible causes:\n"
            "         - POSTHOG_PROJECT_ID is wrong.\n"
            f"         - Wrong region: the project may live on {other_region}.\n"
            f"         PostHog said: {detail}"
        )
    if status == 400:
        return f"400 Bad Request - PostHog rejected the query.\n         PostHog said: {detail}"
    if status == 429:
        retry = response.headers.get("Retry-After", "?")
        return (
            "429 Too Many Requests - rate limit or hourly query budget reached.\n"
            f"         Try again in {retry} seconds.\n"
            f"         PostHog said: {detail}"
        )
    return f"HTTP {status} - unexpected error.\n         PostHog said: {detail}"


def print_table(rows: list[list]) -> None:
    """Print a 7-day table, filling in days that had zero pageviews."""
    counts = {str(day): int(n) for day, n in rows}

    # Use the latest day PostHog returned (in the project's timezone) or today,
    # then walk back 7 days so days with no data still appear as 0.
    returned_days = [date.fromisoformat(d) for d in counts]
    end = max(returned_days + [date.today()])
    days = [end - timedelta(days=i) for i in range(6, -1, -1)]

    print(f"{'Day':<14}{'Weekday':<10}{'Pageviews':>10}")
    print("-" * 34)
    total = 0
    for d in days:
        n = counts.get(d.isoformat(), 0)
        total += n
        print(f"{d.isoformat():<14}{d.strftime('%a'):<10}{n:>10,}")
    print("-" * 34)
    print(f"{'Total':<24}{total:>10,}")

    if total == 0:
        print(
            "\n[NOTE] Connected fine, but there were no $pageview events in the last 7 days.\n"
            "       Check that the PostHog snippet on your site uses THIS project's key."
        )


def main() -> None:
    host, project_id, api_key = read_settings()
    url = f"{host}/api/projects/{project_id}/query/"

    print(f"Host:       {host}")
    print(f"Project ID: {project_id}")
    print(f"API key:    {mask(api_key)}")
    print("Querying PostHog...\n")

    body = {
        "query": {
            "kind": "HogQLQuery",
            "query": QUERY,
            "values": {"event": "$pageview"},
        },
        "name": "connection test - pageviews per day",  # shows up in PostHog's query log
    }

    try:
        response = httpx.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except httpx.ConnectError:
        fail(
            f"Could not connect to {host}.\n"
            "         Check POSTHOG_HOST (https://us.posthog.com or https://eu.posthog.com)\n"
            "         and your internet connection."
        )
    except httpx.TimeoutException:
        fail("PostHog did not answer within 30 seconds. Try again in a minute.")

    if response.status_code != 200:
        fail(explain_http_error(response, host, project_id))

    data = response.json()
    rows = data.get("results")
    if rows is None:
        fail(f"Unexpected response shape (no 'results'): {str(data)[:300]}")

    print("[OK] Connected to PostHog. $pageview events per day, last 7 days:\n")
    print_table(rows)
    print("\nColumns returned by PostHog:", data.get("columns"))


if __name__ == "__main__":
    main()
