"""
Validation for everything a user can send us.

Rule: nothing from the request is ever pasted into HogQL text. Values are first
validated here (strict types and patterns), then passed to PostHog as `values`
placeholders. That gives two layers of protection against SQL injection.
"""

import base64
import json
from datetime import datetime, timezone
from enum import IntEnum
from typing import Annotated

from fastapi import HTTPException, Path, Query


class Days(IntEnum):
    """The only date ranges we allow. Anything else is rejected with a 422 error."""

    LAST_7 = 7
    LAST_30 = 30
    LAST_90 = 90


DaysParam = Annotated[
    Days, Query(description="Date range: last 7, 30 or 90 days (including today)")
]
LimitParam = Annotated[int, Query(ge=1, le=100, description="Rows per page (1-100)")]

# PostHog session ids and person ids are UUIDs, e.g. 01a125cf-d633-793d-bbf9-c8e737c3d94d
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
SessionIdPath = Annotated[str, Path(pattern=UUID_PATTERN, description="Session id (UUID)")]
PersonIdPath = Annotated[str, Path(pattern=UUID_PATTERN, description="Person id (UUID)")]
RecordingIdPath = Annotated[str, Path(pattern=UUID_PATTERN, description="Recording id (UUID)")]

# Pagination cursor: an opaque string the frontend gets as `next_cursor` and sends back
# to load the next page. (PostHog does not allow OFFSET with personal API keys, so we
# page by "rows older than the last one I saw" instead.)
CursorParam = Annotated[
    str | None,
    Query(
        max_length=2000,
        pattern=r"^[A-Za-z0-9+/=_-]+$",
        description="`next_cursor` from the previous page",
    ),
]


def encode_time_cursor(value: str) -> str:
    """Wrap a timestamp from a result row into an opaque cursor string."""
    return base64.urlsafe_b64encode(json.dumps({"t": value}).encode()).decode()


def decode_time_cursor(cursor: str | None) -> str | None:
    """Turn a cursor back into a UTC time string HogQL understands, or None.

    Returns e.g. "2026-10-10 12:35:40.749000". Raises a 422 error for a bad cursor.
    """
    if cursor is None:
        return None
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode()))["t"]
        moment = datetime.fromisoformat(raw)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def encode_cursor(**fields: str) -> str:
    """An opaque cursor holding several fields (e.g. time AND id, so rows with equal times can't be skipped)."""
    return base64.urlsafe_b64encode(json.dumps(fields).encode()).decode()


def decode_cursor(cursor: str | None) -> dict[str, str] | None:
    if cursor is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
            raise ValueError("bad cursor shape")
        return data
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc
