"""What the billing screens show (shared by the client's Billing page and the admin's client page)."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.service import (
    FEATURES,
    active_subscription,
    balance,
    client_features,
    invoice_price_for,
    is_overdue,
    month_usage,
    next_invoice_start,
    paid_amount,
    price_for,
    today_utc,
)
from app.billing import providers
from app.models import Client, ClientMember, Invoice, Plan, UsageDaily, Website
from app.settings_store import get_setting


def num(value: Decimal | int | float | None) -> float | None:
    return None if value is None else float(value)


def invoice_dict(invoice: Invoice, today: date | None = None, *, with_payments: bool = False) -> dict[str, Any]:
    today = today or today_utc()
    out: dict[str, Any] = {
        "id": str(invoice.id),
        "number": invoice.number,
        "issue_date": invoice.issue_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "period_start": invoice.period_start.isoformat() if invoice.period_start else None,
        "period_end": invoice.period_end.isoformat() if invoice.period_end else None,
        "amount": num(invoice.amount),
        "currency": invoice.currency,
        "status": invoice.status,
        "overdue": is_overdue(invoice, today),
        "paid_amount": num(paid_amount(invoice)),
        "balance": num(balance(invoice)),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "emailed_at": invoice.emailed_at.isoformat() if invoice.emailed_at else None,
        "source": invoice.source,
        "line_items": invoice.line_items or [],
        "notes": invoice.notes,
    }
    if with_payments:
        out["payments"] = [
            {"id": str(p.id), "amount": num(p.amount), "method": p.method, "reference": p.reference, "note": p.note,
             "paid_at": p.paid_at.isoformat(), "provider": p.provider}
            for p in invoice.payments
        ]
    return out


def plan_dict(plan, currency: str = "PKR") -> dict[str, Any]:
    return {
        "id": str(plan.id), "name": plan.name, "slug": plan.slug, "description": plan.description,
        "price_pkr": num(plan.price_pkr), "price_usd": num(plan.price_usd),
        "price": num(plan.price_usd if currency == "USD" else plan.price_pkr),
        "intro_price_pkr": num(plan.intro_price_pkr), "intro_price_usd": num(plan.intro_price_usd),
        "intro_price": num(plan.intro_price_usd if currency == "USD" else plan.intro_price_pkr), "intro_months": plan.intro_months,
        "monthly_event_limit": plan.monthly_event_limit, "monthly_recording_limit": plan.monthly_recording_limit,
        "max_websites": plan.max_websites, "max_team_members": plan.max_team_members,
        "features": {name: bool((plan.features or {}).get(name, False)) for name in FEATURES},
        "is_active": plan.is_active, "sort_order": plan.sort_order,
    }


def _client_description(plan: Plan) -> str | None:
    """The description a client may read: the admin's own words, but never the note that marks an example plan."""
    text = (plan.description or "").strip()
    return None if not text or text.startswith("EXAMPLE plan") else text


def client_plans(db: Session, client: Client) -> list[dict[str, Any]]:
    """The plans this client can choose from: the ones that are for sale, in the client's currency.

    Only what a client should see. Never the provider's price, our commission or the price guide.
    """
    plans = db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order, Plan.name))
    usd = client.currency == "USD"
    return [
        {
            "id": str(plan.id), "name": plan.name, "description": _client_description(plan),
            "price": num(plan.price_usd if usd else plan.price_pkr),
            "intro_price": num(plan.intro_price_usd if usd else plan.intro_price_pkr), "intro_months": plan.intro_months,
            "monthly_event_limit": plan.monthly_event_limit, "monthly_recording_limit": plan.monthly_recording_limit,
            "max_websites": plan.max_websites, "max_team_members": plan.max_team_members,
            "features": {name: bool((plan.features or {}).get(name, False)) for name in FEATURES},
        }
        for plan in plans
    ]


def meter(used: int, limit: int | None) -> dict[str, Any]:
    """One counter against its limit: total, used, what is left and by how much it is exceeded. A limit of None = unlimited."""
    return {
        "used": used, "limit": limit,
        "remaining": None if not limit else max(limit - used, 0),
        "over": 0 if not limit else max(used - limit, 0),
        "percent": round(used / limit * 100, 1) if limit else None,
    }


def billing_summary(db: Session, client: Client) -> dict[str, Any]:
    """Plan, usage against the plan's limits, and the invoices of one client."""
    today = today_utc()
    sub = active_subscription(db, client.id)
    plan = sub.plan if sub else None

    websites = db.scalar(select(func.count()).select_from(Website).where(Website.client_id == client.id, Website.is_active.is_(True))) or 0
    members = db.scalar(select(func.count()).select_from(ClientMember).where(ClientMember.client_id == client.id)) or 0
    events, recordings = month_usage(db, client.id, today)
    event_meter = meter(events, plan.monthly_event_limit if plan else None)
    recording_meter = meter(recordings, plan.monthly_recording_limit if plan else None)
    last_synced = db.scalar(select(func.max(UsageDaily.updated_at)).join(Website, Website.id == UsageDaily.website_id).where(Website.client_id == client.id))

    invoices = db.scalars(select(Invoice).where(Invoice.client_id == client.id).order_by(Invoice.issue_date.desc(), Invoice.number.desc())).all()
    open_invoices = [i for i in invoices if i.status == "open"]

    return {
        "client": {"id": str(client.id), "name": client.name, "currency": client.currency, "status": client.status, "suspended_reason": client.suspended_reason},
        # (a client with a special price pays that, so the plan's introductory price doesn't apply to them)
        "plan": None if plan is None else {**plan_dict(plan, client.currency), "price": num(price_for(client, sub)),
                                           **({"intro_price": None} if sub.price_override is not None else {})},
        "subscription": None if sub is None else _subscription_dict(db, client, sub, today),
        "features": client_features(db, client.id),
        "usage": {
            # events and recordings ("videos"): used, the plan's total, what is left, and how far over (all for THIS calendar month)
            "events": events, "event_limit": event_meter["limit"], "event_remaining": event_meter["remaining"], "event_over": event_meter["over"], "percent": event_meter["percent"],
            "recordings": recordings, "recording_limit": recording_meter["limit"], "recording_remaining": recording_meter["remaining"],
            "recording_over": recording_meter["over"], "recording_percent": recording_meter["percent"],
            "updated_at": last_synced.isoformat() if last_synced else None,
            "websites": websites, "max_websites": plan.max_websites if plan else None,
            "members": members, "max_members": plan.max_team_members if plan else None,
        },
        "invoices": [invoice_dict(i, today) for i in invoices],
        "outstanding": {
            "amount": num(sum((balance(i) for i in open_invoices), Decimal("0"))),
            "count": len(open_invoices),
            "overdue_count": sum(1 for i in open_invoices if is_overdue(i, today)),
        },
        "payment_instructions": get_setting(db, "billing.payment_instructions"),
        "online_payments": providers.online_provider(db) is not None,
        "support": support_info(db),
    }


def _subscription_dict(db: Session, client: Client, sub, today: date) -> dict[str, Any]:
    start = next_invoice_start(db, sub, today)
    amount, intro = invoice_price_for(client, sub, start)
    return {
        "id": str(sub.id), "plan_id": str(sub.plan_id), "started_at": sub.started_at.isoformat(), "billing_day": sub.billing_day,
        "price_override": num(sub.price_override),
        # when the next invoice is issued, what it will cost, and whether that is the introductory ("first month") price
        "next_invoice_date": start.isoformat(), "next_invoice_amount": num(amount), "next_invoice_is_intro": intro,
    }


def support_info(db: Session) -> dict[str, str]:
    return {"whatsapp": get_setting(db, "support.whatsapp"), "email": get_setting(db, "support.email")}
