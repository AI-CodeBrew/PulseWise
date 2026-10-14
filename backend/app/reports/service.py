"""Making and sending weekly reports."""

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import emailer
from app.alerts import raise_alert, resolve_alerts
from app.billing.notifications import recipients
from app.billing.service import has_feature
from app.config import settings
from app.db import get_sessionmaker
from app.deps import config_from_website
from app.models import Client, Report, Website
from app.posthog_client import PostHogClient
from app.reports import render
from app.reports.collect import collect_report_data
from app.reports.summary import write_summary
from app.settings_store import get_setting

log = logging.getLogger(__name__)

SEND_HOUR_LOCAL = 8  # reports go out on Monday morning, from 08:00 in the client's time zone


def client_zone(client: Client) -> ZoneInfo:
    try:
        return ZoneInfo(client.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Karachi")


def last_full_week(local_today: date) -> tuple[date, date]:
    """The most recent complete Monday-to-Sunday week before `local_today`."""
    end = local_today - timedelta(days=local_today.weekday() + 1)  # last Sunday
    return end - timedelta(days=6), end


def is_ready(client: Client, now_utc: datetime | None = None) -> tuple[bool, date, date]:
    """Has this client's Monday 08:00 arrived? Returns (ready, week_start, week_end)."""
    now_local = (now_utc or datetime.now(timezone.utc)).astimezone(client_zone(client))
    start, end = last_full_week(now_local.date())
    monday = now_local.date() - timedelta(days=now_local.weekday())
    ready_at = datetime.combine(monday, datetime.min.time(), tzinfo=now_local.tzinfo).replace(hour=SEND_HOUR_LOCAL)
    return now_local >= ready_at, start, end


def report_dict(report: Report, *, website_name: str = "", client_name: str = "", with_data: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(report.id), "website_id": str(report.website_id),
        "period_start": report.period_start.isoformat(), "period_end": report.period_end.isoformat(),
        "language": report.language, "summary": report.summary, "summary_source": report.summary_source,
        "generated_by": report.generated_by, "emailed_at": report.emailed_at.isoformat() if report.emailed_at else None,
        "emailed_to": report.emailed_to, "created_at": report.created_at.isoformat() if report.created_at else None,
        "website_name": website_name, "client_name": client_name,
    }
    if with_data:
        out["data"] = report.data
    return out


# ------------------------------------------------------------------ generating


def _load(website_id: uuid.UUID) -> tuple[Any, str, bool, str]:
    with get_sessionmaker()() as db:
        website = db.get(Website, website_id)
        client = db.get(Client, website.client_id)
        return config_from_website(website), client.report_language, bool(get_setting(db, "ai.enabled")), str(get_setting(db, "ai.model"))


def _store(website_id: uuid.UUID, start: date, end: date, language: str, data: dict, summary, generated_by: str) -> uuid.UUID:
    """Insert the report, or replace the content if this week was already reported."""
    with get_sessionmaker()() as db:
        website = db.get(Website, website_id)
        report = db.scalar(select(Report).where(Report.website_id == website_id, Report.period_start == start, Report.period_end == end))
        if report is None:
            report = Report(website_id=website_id, client_id=website.client_id, period_start=start, period_end=end)
            db.add(report)
        report.language = language
        report.data = data
        report.summary = summary.as_dict()
        report.summary_source = summary.source
        report.generated_by = generated_by
        db.commit()
        return report.id


def _sales_block(website_id: uuid.UUID, start: date, end: date) -> dict | None:
    """The week's Shopify numbers, if the client has a connected store and a plan with Shopify sales."""
    from app.billing.service import has_feature  # (imported here: these modules import each other)
    from app.shopify.sales import week_sales

    with get_sessionmaker()() as db:
        website = db.get(Website, website_id)
        client = db.get(Client, website.client_id)
        if not has_feature(db, client.id, "shopify"):
            return None
        return week_sales(db, website_id, client, start, end)


async def generate_report(website_id: uuid.UUID, start: date, end: date, *, generated_by: str = "schedule", language: str | None = None) -> uuid.UUID:
    """Collect the numbers, write the summary, save the report. Returns the report id."""
    config, client_language, ai_enabled, model = await asyncio.to_thread(_load, website_id)
    language = language or client_language
    data = await collect_report_data(PostHogClient(config), start, end)
    sales = await asyncio.to_thread(_sales_block, website_id, start, end)
    if sales:
        data["sales"] = sales
    summary = await write_summary(data, language, ai_enabled=ai_enabled, model=model)
    return await asyncio.to_thread(_store, website_id, start, end, language, data, summary, generated_by)


# ------------------------------------------------------------------ emailing


def _load_logo(client: Client) -> bytes | None:
    return client.logo_data if client.logo_data and client.logo_mime in ("image/png", "image/jpeg") else None  # (fpdf can't draw WebP)


def send_report(report_id: uuid.UUID) -> int:
    """Email a stored report (HTML + PDF) to the client's owners. Returns how many people it went to."""
    if not emailer.email_configured():
        return 0
    with get_sessionmaker()() as db:
        report = db.get(Report, report_id)
        website = db.get(Website, report.website_id)
        client = db.get(Client, report.client_id)
        to = recipients(db, client)
        if not to:
            return 0
        brand = get_setting(db, "billing.business_name") or settings.brand_name
        payload = report_dict(report, website_name=website.name, client_name=client.name)
        dashboard_url = f"{settings.frontend_url}/sites/{website.id}/reports/{report.id}"
        subject = f"Your weekly website report: {website.name} ({render.period_label(report.data['period'])})"
        text = render.render_text(payload, website.name, dashboard_url)
        body = render.render_html(payload, website.name, client.name, dashboard_url, brand)
        pdf = render.report_pdf(payload, website.name, client.name, brand, _load_logo(client))
        filename = f"weekly-report-{report.period_end.isoformat()}.pdf"
        sent = sum(emailer.send_email(address, subject, text, html=body, attachments=[(filename, pdf, "application/pdf")]) for address in to)
        if sent:
            report.emailed_at = datetime.now(timezone.utc)
            report.emailed_to = sent
            db.commit()
        return sent


def send_report_whatsapp(report_id: uuid.UUID, *, force: bool = False) -> bool:
    """Send the report's headline and a link by WhatsApp to the client's opted-in number. True if sent.

    Without `force` a report is only ever sent once. Failures never raise: they become an alert for the admins.
    """
    from app import whatsapp

    if not whatsapp.whatsapp_configured():
        return False
    with get_sessionmaker()() as db:
        report = db.get(Report, report_id)
        client = db.get(Client, report.client_id)
        if not (client.whatsapp_reports_enabled and client.whatsapp_number) or (report.whatsapp_sent_at and not force):
            return False
        website = db.get(Website, report.website_id)
        params = [website.name, render.period_label(report.data["period"]), report.summary["headline"], f"{settings.frontend_url}/sites/{website.id}/reports/{report.id}"]
        key = f"whatsapp:{client.id}"
        try:
            whatsapp.send_template(client.whatsapp_number, str(get_setting(db, "whatsapp.template_name")), str(get_setting(db, "whatsapp.template_language")),
                                   params, api_version=str(get_setting(db, "whatsapp.api_version")))
        except whatsapp.WhatsAppError as exc:
            log.warning("WhatsApp report for %s not sent: %s", client.name, exc)
            raise_alert(db, kind="whatsapp_send", dedupe_key=key, severity="warning", client_id=client.id, website_id=website.id,
                        message=f"A WhatsApp weekly report for {client.name} could not be sent: {exc}")
            return False
        report.whatsapp_sent_at = datetime.now(timezone.utc)
        db.commit()
        resolve_alerts(db, dedupe_key=key)
        return True


def render_report_pdf(db: Session, report: Report) -> bytes:
    website = db.get(Website, report.website_id)
    client = db.get(Client, report.client_id)
    brand = get_setting(db, "billing.business_name") or settings.brand_name
    return render.report_pdf(report_dict(report, website_name=website.name, client_name=client.name), website.name, client.name, brand, _load_logo(client))


# ------------------------------------------------------------------ which reports are due


def due_websites(db: Session, now_utc: datetime | None = None) -> list[tuple[uuid.UUID, date, date]]:
    """Websites whose weekly report should be made now: client switched on, plan includes it, Monday 08:00 passed, not made yet."""
    due = []
    for website in db.scalars(select(Website).where(Website.is_active.is_(True))):
        client = db.get(Client, website.client_id)
        if client is None or client.status != "active" or not client.weekly_report_enabled:
            continue
        if not has_feature(db, client.id, "weekly_reports"):
            continue
        ready, start, end = is_ready(client, now_utc)
        if not ready:
            continue
        if db.scalar(select(Report.id).where(Report.website_id == website.id, Report.period_start == start, Report.period_end == end)):
            continue
        due.append((website.id, start, end))
    return due
