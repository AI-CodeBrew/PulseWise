"""
Background jobs: a registry, a runner that records every run, and a lock so only ONE server runs a job at a time.

Add a job in three steps:
    @job("name", title="...", description="...", schedule="Every hour", cron={"minute": 5})
    async def name() -> dict:
        ...
        return {"message": "what happened, in one line", ...anything else worth keeping...}
and import its module in app/jobs/__init__.py. It shows up in the admin panel (Jobs page), with a "Run now" button.

APScheduler runs them on a timer (see app/scheduler.py). Moving to Celery/Redis later means replacing only the scheduler.
"""

import asyncio
import logging
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.alerts import notify_admins, raise_alert, resolve_alerts
from app.db import get_engine, get_sessionmaker
from app.models import JobRun, utcnow
from app.settings_store import get_setting

log = logging.getLogger(__name__)


@dataclass
class JobSpec:
    name: str
    title: str
    description: str
    schedule: str  # in words, for the admin panel
    cron: dict[str, Any]  # APScheduler CronTrigger arguments (UTC)
    func: Callable[[], Awaitable[dict[str, Any]]] = field(repr=False)


JOBS: dict[str, JobSpec] = {}


def job(name: str, *, title: str, description: str, schedule: str, cron: dict[str, Any]):
    def decorator(func: Callable[[], Awaitable[dict[str, Any]]]):
        JOBS[name] = JobSpec(name, title, description, schedule, cron, func)
        return func

    return decorator


class JobLock:
    """A cross-server lock (PostgreSQL advisory lock). Without it, two servers would run the same job twice.

    SQLite (tests, one process) needs no lock. NOTE: advisory locks need a "session" connection; Supabase's
    session pooler (port 5432) is one, its transaction pooler (port 6543) is not.
    """

    def __init__(self, name: str):
        self.key = zlib.crc32(f"portal-job:{name}".encode())
        self.conn = None

    def acquire(self) -> bool:
        engine = get_engine()
        if engine.dialect.name != "postgresql":
            return True
        conn = engine.connect()
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar())
        conn.commit()
        if got:
            self.conn = conn
        else:
            conn.close()
        return got

    def release(self) -> None:
        if self.conn is not None:
            try:
                self.conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
                self.conn.commit()
            finally:
                self.conn.close()
                self.conn = None


def _start_run(name: str, triggered_by: str) -> str:
    with get_sessionmaker()() as db:
        run = JobRun(job=name, triggered_by=triggered_by)
        db.add(run)
        db.commit()
        return str(run.id)


def _finish_run(run_id: str, status: str, message: str, details: dict[str, Any] | None) -> None:
    import uuid

    with get_sessionmaker()() as db:
        run = db.get(JobRun, uuid.UUID(run_id))
        if run is not None:
            run.status = status
            run.message = message[:2000]
            run.details = details
            run.finished_at = utcnow()
            db.commit()


def _job_alert(name: str, ok: bool, message: str) -> None:
    key = f"job_failed:{name}"
    with get_sessionmaker()() as db:
        if ok:
            resolve_alerts(db, dedupe_key=key)
            return
        alert, created = raise_alert(db, kind="job_failed", dedupe_key=key, severity="critical", message=message)
        if created:
            notify_admins(alert, get_setting(db, "alerts.extra_recipients"))


async def run_job(name: str, triggered_by: str = "schedule") -> dict[str, Any]:
    """Run one job now: take the lock, record the run, catch errors (an error becomes an alert, never a crash)."""
    spec = JOBS[name]
    lock = JobLock(name)
    if not await asyncio.to_thread(lock.acquire):
        run_id = await asyncio.to_thread(_start_run, name, triggered_by)
        await asyncio.to_thread(_finish_run, run_id, "skipped", "Another server is already running this job.", None)
        return {"run_id": run_id, "status": "skipped"}

    run_id = await asyncio.to_thread(_start_run, name, triggered_by)
    try:
        details = await spec.func() or {}
        message = str(details.pop("message", "Done."))
        await asyncio.to_thread(_finish_run, run_id, "ok", message, details)
        await asyncio.to_thread(_job_alert, name, True, "")
        log.info("Job %s finished: %s", name, message)
        return {"run_id": run_id, "status": "ok", "message": message}
    except Exception as exc:  # noqa: BLE001 - one failing job must not stop the others
        log.exception("Job %s failed", name)
        message = f"{type(exc).__name__}: {exc}"
        await asyncio.to_thread(_finish_run, run_id, "error", message, None)
        await asyncio.to_thread(_job_alert, name, False, f"The background job “{spec.title}” failed: {message[:300]}")
        return {"run_id": run_id, "status": "error", "message": message}
    finally:
        await asyncio.to_thread(lock.release)
