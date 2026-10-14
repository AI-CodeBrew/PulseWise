"""Job: every day, issue the month's invoices, send reminders, and suspend clients who haven't paid."""

import asyncio
from typing import Any

from app.billing import notifications
from app.billing.service import apply_overdue_rules, generate_due_invoices
from app.db import get_sessionmaker
from app.jobs.registry import job
from app.models import Client
from app.settings_store import get_setting


def _run() -> dict[str, Any]:
    with get_sessionmaker()() as db:
        created = generate_due_invoices(db)
        emailed = 0
        if get_setting(db, "billing.email_invoices"):
            for invoice in created:
                client = db.get(Client, invoice.client_id)
                if client is not None and notifications.send_invoice_email(db, invoice, client):
                    emailed += 1
        overdue = apply_overdue_rules(db)
    parts = [f"Issued {len(created)} invoice{'s' if len(created) != 1 else ''}" + (f" ({emailed} emailed)" if created else "")]
    parts.append(f"{overdue['overdue']} overdue")
    if overdue["reminded"]:
        parts.append(f"{overdue['reminded']} reminder{'s' if overdue['reminded'] != 1 else ''} sent")
    if overdue["suspended"]:
        parts.append("suspended: " + ", ".join(overdue["suspended"]))
    if overdue["reactivated"]:
        parts.append("re-activated: " + ", ".join(overdue["reactivated"]))
    return {"message": "; ".join(parts) + ".", "issued": [i.number for i in created], **overdue}


@job(
    "billing_daily",
    title="Invoices and overdue payments",
    description="Issues each client's invoice on their billing day, emails it, sends reminders, and suspends access when an invoice stays unpaid past the grace period. Paying lifts the suspension.",
    schedule="Every day at 05:00 UTC (10:00 in Pakistan)",
    cron={"hour": 5, "minute": 0},
)
async def billing_daily() -> dict[str, Any]:
    return await asyncio.to_thread(_run)
