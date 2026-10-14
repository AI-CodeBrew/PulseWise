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
    is_overdue,
    month_events,
    next_billing_date,
    paid_amount,
    price_for,
    today_utc,
)
from app.billing import providers
from app.models import Client, ClientMember, Invoice, Website
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
        "monthly_event_limit": plan.monthly_event_limit, "max_websites": plan.max_websites, "max_team_members": plan.max_team_members,
        "features": {name: bool((plan.features or {}).get(name, False)) for name in FEATURES},
        "is_active": plan.is_active, "sort_order": plan.sort_order,
    }


def billing_summary(db: Session, client: Client) -> dict[str, Any]:
    """Plan, usage against the plan's limits, and the invoices of one client."""
    today = today_utc()
    sub = active_subscription(db, client.id)
    plan = sub.plan if sub else None

    websites = db.scalar(select(func.count()).select_from(Website).where(Website.client_id == client.id, Website.is_active.is_(True))) or 0
    members = db.scalar(select(func.count()).select_from(ClientMember).where(ClientMember.client_id == client.id)) or 0
    events = month_events(db, client.id, today)
    limit = plan.monthly_event_limit if plan else None

    invoices = db.scalars(select(Invoice).where(Invoice.client_id == client.id).order_by(Invoice.issue_date.desc(), Invoice.number.desc())).all()
    open_invoices = [i for i in invoices if i.status == "open"]

    return {
        "client": {"id": str(client.id), "name": client.name, "currency": client.currency, "status": client.status, "suspended_reason": client.suspended_reason},
        "plan": None if plan is None else {**plan_dict(plan, client.currency), "price": num(price_for(client, sub))},
        "subscription": None if sub is None else {
            "id": str(sub.id), "plan_id": str(sub.plan_id), "started_at": sub.started_at.isoformat(), "billing_day": sub.billing_day,
            "price_override": num(sub.price_override), "next_invoice_date": next_billing_date(sub.billing_day, today).isoformat() if next_billing_date(sub.billing_day, today) > sub.started_at else sub.started_at.isoformat(),
        },
        "features": client_features(db, client.id),
        "usage": {
            "events": events, "event_limit": limit, "percent": round(events / limit * 100, 1) if limit else None,
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


def support_info(db: Session) -> dict[str, str]:
    return {"whatsapp": get_setting(db, "support.whatsapp"), "email": get_setting(db, "support.email")}
