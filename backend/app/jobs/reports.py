"""Job: make and email the weekly reports that are due (every Monday morning in each client's time zone)."""

import asyncio
import logging
from typing import Any

from app.db import get_sessionmaker
from app.jobs.registry import job
from app.posthog_client import AnalyticsError
from app.reports import service

log = logging.getLogger(__name__)


def _due() -> list:
    with get_sessionmaker()() as db:
        return service.due_websites(db)


@job(
    "weekly_reports",
    title="Weekly reports",
    description="On Monday morning (08:00 in each client's time zone) writes the previous week's report for every website whose plan includes it, and emails it to the account owners. Safe to run any time: a week is only reported once.",
    schedule="Every hour, at quarter past (each client gets theirs once, on Monday morning)",
    cron={"minute": 15},
)
async def weekly_reports() -> dict[str, Any]:
    due = await asyncio.to_thread(_due)
    made, emailed, whatsapped, failed = 0, 0, 0, []
    for website_id, start, end in due:  # one at a time: each report runs several PostHog queries (and one AI call)
        try:
            report_id = await service.generate_report(website_id, start, end, generated_by="schedule")
            made += 1
            emailed += 1 if await asyncio.to_thread(service.send_report, report_id) else 0
            whatsapped += 1 if await asyncio.to_thread(service.send_report_whatsapp, report_id) else 0
        except AnalyticsError as exc:  # already raised as an alert by the PostHog client
            failed.append(f"{website_id}: {exc.upstream_detail or exc.message}")
    message = f"{made} report{'s' if made != 1 else ''} made, {emailed} emailed" + (f", {whatsapped} on WhatsApp" if whatsapped else "") + (f", {len(failed)} failed" if failed else "") + "."
    if due and made == 0 and failed:
        raise RuntimeError(message + " " + "; ".join(failed[:3]))
    return {"message": message, "made": made, "emailed": emailed, "whatsapp": whatsapped, "failed": failed}
