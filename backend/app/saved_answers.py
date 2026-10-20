"""
Saved answers: the analytics service's answers, kept in our own database (table analytics_cache).

Why: asking the analytics service takes seconds per question, and a dashboard page asks several. With the answers
saved, a page opens at once: posthog_client.py shows the saved answer and, when it is a few minutes old, fetches a
fresh one in the background. The job in app/jobs/refresh.py keeps the most-used pages fresh even when nobody looks.

These functions are plain (blocking) database calls: the async code runs them with asyncio.to_thread().
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects import postgresql, sqlite

from app.db import get_sessionmaker
from app.models import AnalyticsCache

log = logging.getLogger(__name__)

FRESH_SECONDS = 5 * 60  # younger than this: used as it is
MAX_AGE_SECONDS = 7 * 24 * 3600  # older than this: not shown any more (asked again, the visitor waits)


def load(key: str) -> tuple[Any, float] | None:
    """The saved answer and its age in seconds, or None (also when the database can't be read: then we just ask again)."""
    try:
        with get_sessionmaker()() as db:
            row = db.get(AnalyticsCache, key)
            if row is None:
                return None
            refreshed_at = row.refreshed_at if row.refreshed_at.tzinfo else row.refreshed_at.replace(tzinfo=timezone.utc)  # (SQLite drops the zone)
            return row.payload, (datetime.now(timezone.utc) - refreshed_at).total_seconds()
    except Exception:  # noqa: BLE001
        log.warning("Could not read a saved analytics answer", exc_info=True)
        return None


def save(key: str, website_id: str, name: str, payload: Any) -> None:
    """Insert or replace the answer (works on PostgreSQL and SQLite). A failure is logged, never raised:
    the visitor already has the answer, only the saving went wrong."""
    try:
        with get_sessionmaker()() as db:
            insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
            now = datetime.now(timezone.utc)
            statement = insert(AnalyticsCache).values(key=key, website_id=uuid.UUID(website_id), name=name[:100], payload=payload, refreshed_at=now)
            statement = statement.on_conflict_do_update(index_elements=["key"], set_={"payload": statement.excluded.payload, "refreshed_at": now})
            db.execute(statement)
            db.commit()
    except Exception:  # noqa: BLE001
        log.warning("Could not save an analytics answer (website %s, %s)", website_id, name, exc_info=True)
