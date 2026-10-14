"""
Runs the background jobs on a timer, inside the API process (APScheduler).

- Turn it off with SCHEDULER_ENABLED=false (for example when running several API workers, run it in ONE of them).
- Every job also takes a database lock, so even if several servers run the scheduler a job runs once per tick.
- Jobs can always be started by hand: admin panel -> Jobs -> "Run now", or `python -m app.cli run-job <name>`.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.jobs import JOBS, run_job

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start() -> None:
    global _scheduler
    if not settings.scheduler_enabled:
        log.info("Background scheduler is OFF (SCHEDULER_ENABLED=false).")
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    for spec in JOBS.values():
        _scheduler.add_job(
            run_job,
            CronTrigger(**spec.cron, timezone="UTC"),
            args=[spec.name],
            id=spec.name,
            max_instances=1,  # never overlap with itself
            coalesce=True,  # if the server was down, run once, not once per missed tick
            misfire_grace_time=3600,
            replace_existing=True,
        )
    _scheduler.start()
    log.info("Background scheduler started with %d jobs: %s", len(JOBS), ", ".join(JOBS))


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
