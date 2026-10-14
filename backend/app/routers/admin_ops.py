"""
Admin API, part 2 ("operations"): usage and cost, alerts, background jobs and settings.
Same rule as routers/admin.py: the WHOLE router requires an admin.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select

from app import pricing
from app.audit import audit
from app.alerts import resolve_alerts
from app.deps import AdminUser, DbSession, client_ip, require_admin
from app.jobs import JOBS, run_job
from app.jobs.usage import days_in_month, month_start
from app.models import Alert, Client, JobRun, UsageDaily, Website
from app.params import DaysParam, LimitParam
from app.settings_store import SETTINGS, SettingError, all_settings, set_settings

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

MonthParam = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM (default: this month)")]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ------------------------------------------------------------------ usage and PostHog cost


def month_range(month: str | None) -> tuple[date, date]:
    first = date.fromisoformat(f"{month}-01") if month else month_start()
    return first, first.replace(day=days_in_month(first))


def usage_by_website(db, first: date, last: date) -> list[dict[str, Any]]:
    """Month totals per active website (websites with no data yet show 0)."""
    rows = db.execute(
        select(
            Website.id, Website.name, Client.id, Client.name,
            func.coalesce(func.sum(UsageDaily.events), 0),
            func.coalesce(func.sum(UsageDaily.pageviews), 0),
            func.coalesce(func.sum(UsageDaily.recordings), 0),
        )
        .select_from(Website)
        .join(Client, Client.id == Website.client_id)
        .outerjoin(UsageDaily, and_(UsageDaily.website_id == Website.id, UsageDaily.day >= first, UsageDaily.day <= last))
        .where(Website.is_active.is_(True))
        .group_by(Website.id, Website.name, Client.id, Client.name)
        .order_by(func.coalesce(func.sum(UsageDaily.events), 0).desc(), Website.name)
    ).all()
    return [
        {"website_id": str(w_id), "website_name": w_name, "client_id": str(c_id), "client_name": c_name,
         "events": int(events), "pageviews": int(pageviews), "recordings": int(recordings)}
        for w_id, w_name, c_id, c_name, events, pageviews, recordings in rows
    ]


@router.get("/usage", summary="Events per website this month, and an estimate of what PostHog charges you")
def usage(db: DbSession, month: MonthParam = None):
    first, last = month_range(month)
    today = datetime.now(timezone.utc).date()
    total_days = days_in_month(first)
    elapsed = 0 if today < first else min((today - first).days + 1, total_days)
    in_progress = first <= today <= last

    websites = usage_by_website(db, first, last)
    total_events = sum(w["events"] for w in websites)
    total_recordings = sum(w["recordings"] for w in websites)
    factor = (total_days / elapsed) if in_progress and elapsed else 1.0  # simple straight-line projection
    projected_events = round(total_events * factor)
    projected_recordings = round(total_recordings * factor)

    events_cost = pricing.event_cost(total_events)
    recordings_cost = pricing.recording_cost(total_recordings)
    projected_cost = pricing.event_cost(projected_events) + pricing.recording_cost(projected_recordings)

    for w in websites:  # each website pays its share of the (organization-wide) bill, by events and recordings
        share_e = w["events"] / total_events if total_events else 0
        share_r = w["recordings"] / total_recordings if total_recordings else 0
        w["projected_events"] = round(w["events"] * factor)
        w["share_of_events"] = round(share_e, 4)
        w["estimated_cost_usd"] = round(events_cost * share_e + recordings_cost * share_r, 2)

    clients: dict[str, dict[str, Any]] = {}
    for w in websites:
        c = clients.setdefault(w["client_id"], {"client_id": w["client_id"], "client_name": w["client_name"], "events": 0, "recordings": 0, "estimated_cost_usd": 0.0, "websites": 0})
        c["events"] += w["events"]
        c["recordings"] += w["recordings"]
        c["estimated_cost_usd"] = round(c["estimated_cost_usd"] + w["estimated_cost_usd"], 2)
        c["websites"] += 1

    last_sync = db.scalar(select(func.max(UsageDaily.updated_at)))
    return {
        "month": first.strftime("%Y-%m"),
        "days_elapsed": elapsed,
        "days_in_month": total_days,
        "in_progress": in_progress,
        "last_synced_at": _iso(last_sync),
        "websites": websites,
        "clients": sorted(clients.values(), key=lambda c: -c["events"]),
        "totals": {"events": total_events, "recordings": total_recordings, "projected_events": projected_events, "projected_recordings": projected_recordings},
        "cost": {
            "events_usd": round(events_cost, 2),
            "recordings_usd": round(recordings_cost, 2),
            "total_usd": round(events_cost + recordings_cost, 2),
            "projected_total_usd": round(projected_cost, 2),
            "free_events": int(pricing.FREE_EVENTS),
            "free_recordings": int(pricing.FREE_RECORDINGS),
            "note": "An estimate from posthog.com/pricing (events + session recordings). PostHog's free allowance is shared by ALL your clients together. Add-ons and credits are not included.",
        },
    }


@router.get("/usage/websites/{website_id}", summary="One website's events per day")
def website_usage(website_id: uuid.UUID, db: DbSession, days: DaysParam = 30):
    if db.get(Website, website_id) is None:
        raise HTTPException(status_code=404, detail="Website not found.")
    since = datetime.now(timezone.utc).date() - timedelta(days=int(days) - 1)
    rows = {r.day: r for r in db.scalars(select(UsageDaily).where(UsageDaily.website_id == website_id, UsageDaily.day >= since))}
    series = []
    for offset in range(int(days)):  # a day without data is a real zero
        day = since + timedelta(days=offset)
        r = rows.get(day)
        series.append({"date": day.isoformat(), "events": int(r.events) if r else 0, "pageviews": int(r.pageviews) if r else 0, "recordings": int(r.recordings) if r else 0})
    return {"days": int(days), "series": series}


# ------------------------------------------------------------------ alerts


def alert_dict(alert: Alert, website_name: str | None, client_name: str | None) -> dict[str, Any]:
    return {
        "id": str(alert.id), "kind": alert.kind, "severity": alert.severity, "message": alert.message, "status": alert.status,
        "occurrences": alert.occurrences, "website_id": str(alert.website_id) if alert.website_id else None, "website_name": website_name,
        "client_id": str(alert.client_id) if alert.client_id else None, "client_name": client_name,
        "created_at": _iso(alert.created_at), "last_seen_at": _iso(alert.last_seen_at), "resolved_at": _iso(alert.resolved_at),
    }


@router.get("/alerts", summary="Things that need your attention")
def list_alerts(db: DbSession, status: Annotated[str, Query(pattern="^(open|resolved|all)$")] = "open", limit: LimitParam = 50):
    query = (
        select(Alert, Website.name, Client.name)
        .outerjoin(Website, Website.id == Alert.website_id)
        .outerjoin(Client, Client.id == Alert.client_id)
        .order_by(Alert.last_seen_at.desc())
        .limit(limit)
    )
    if status != "all":
        query = query.where(Alert.status == status)
    open_count = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open")) or 0
    return {"open_count": open_count, "results": [alert_dict(a, w, c) for a, w, c in db.execute(query)]}


@router.post("/alerts/{alert_id}/resolve", summary="Mark an alert as dealt with")
def resolve_alert(alert_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if alert.status == "open":
        resolve_alerts(db, dedupe_key=alert.dedupe_key)
        audit(db, "admin.alert_resolved", actor_id=admin.id, target_type="alert", target_id=alert.id, ip=client_ip(request), details={"kind": alert.kind})
        db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ background jobs

_running_tasks: set[asyncio.Task] = set()  # keeps a reference so a "Run now" task isn't garbage-collected


@router.get("/jobs", summary="Background jobs and their last runs")
def list_jobs(db: DbSession):
    out = []
    for spec in JOBS.values():
        last = db.scalar(select(JobRun).where(JobRun.job == spec.name).order_by(JobRun.started_at.desc()).limit(1))
        out.append({
            "name": spec.name, "title": spec.title, "description": spec.description, "schedule": spec.schedule,
            "last_run": None if last is None else {
                "status": last.status, "triggered_by": last.triggered_by, "started_at": _iso(last.started_at),
                "finished_at": _iso(last.finished_at), "message": last.message,
            },
        })
    return {"results": out}


@router.post("/jobs/{name}/run", status_code=202, summary="Run a background job now")
async def run_job_now(name: str, request: Request, admin: AdminUser, db: DbSession):
    if name not in JOBS:
        raise HTTPException(status_code=404, detail="Unknown job.")
    recent = datetime.now(timezone.utc) - timedelta(minutes=30)
    running = db.scalar(select(JobRun.id).where(JobRun.job == name, JobRun.status == "running", JobRun.started_at >= recent).limit(1))
    if running is not None:
        raise HTTPException(status_code=409, detail="That job is already running. Give it a minute.")
    audit(db, "admin.job_run", actor_id=admin.id, target_type="job", target_id=name, ip=client_ip(request))
    db.commit()
    task = asyncio.create_task(run_job(name, "admin"))
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
    return {"started": True}


# ------------------------------------------------------------------ settings


class SettingsIn(BaseModel):
    values: dict[str, Any]


@router.get("/settings", summary="Settings you can change here")
def get_settings_api(db: DbSession):
    current = all_settings(db)
    return {
        "results": [
            {"key": d.key, "label": d.label, "help": d.help, "group": d.group, "kind": d.kind, "default": d.default,
             "value": current[d.key], "minimum": d.minimum, "maximum": d.maximum}
            for d in SETTINGS.values()
        ]
    }


@router.patch("/settings", summary="Change settings")
def update_settings(body: SettingsIn, request: Request, admin: AdminUser, db: DbSession):
    try:
        changed = set_settings(db, body.values)
    except SettingError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if changed:
        audit(db, "admin.settings_changed", actor_id=admin.id, ip=client_ip(request), details={"settings": sorted(changed)})
    db.commit()
    return {"changed": sorted(changed)}


# ------------------------------------------------------------------ reports


class GenerateReportIn(BaseModel):
    send: bool = False  # also email it to the client's owners now
    language: str | None = None  # "en" | "roman_ur" | "ur" (default: the client's setting)


@router.post("/websites/{website_id}/reports", status_code=201, summary="Make this website's latest weekly report now (and optionally email it)")
async def generate_report_now(website_id: uuid.UUID, body: GenerateReportIn, request: Request, admin: AdminUser, db: DbSession):
    from datetime import datetime as _dt

    from app import emailer
    from app.reports import service
    from app.reports.summary import LANGUAGES

    website = db.get(Website, website_id)
    if website is None:
        raise HTTPException(status_code=404, detail="Website not found.")
    if body.language is not None and body.language not in LANGUAGES:
        raise HTTPException(status_code=400, detail="Language must be en, roman_ur or ur.")
    from app.whatsapp import whatsapp_configured

    if body.send and not (emailer.email_configured() or whatsapp_configured()):
        raise HTTPException(status_code=409, detail="Neither email nor WhatsApp sending is set up yet (add the SMTP_* or WHATSAPP_* settings to backend/.env).")
    client = db.get(Client, website.client_id)
    start, end = service.last_full_week(_dt.now(timezone.utc).astimezone(service.client_zone(client)).date())
    audit(db, "admin.report_generated", actor_id=admin.id, target_type="website", target_id=website.id, ip=client_ip(request), details={"week_end": end.isoformat(), "send": body.send})
    db.commit()
    report_id = await service.generate_report(website_id, start, end, generated_by="admin", language=body.language)
    sent = await asyncio.to_thread(service.send_report, report_id) if body.send else 0
    on_whatsapp = await asyncio.to_thread(service.send_report_whatsapp, report_id, force=True) if body.send else False
    return {"report_id": str(report_id), "period_start": start.isoformat(), "period_end": end.isoformat(), "emailed_to": sent, "whatsapp_sent": on_whatsapp}
