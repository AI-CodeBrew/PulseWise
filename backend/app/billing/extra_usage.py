"""Extra usage: events and recordings ("videos") ABOVE what a client's plan includes, priced like PostHog prices them plus our commission.

Nothing is charged automatically. The admin sees the suggestion on the client's page and creates the invoice with one click.

How the price is worked out (per month):
  - the extra units are priced as if this client were PostHog's only customer, starting where the plan ends:
    `cost(used) - cost(included)` on PostHog's tiered prices (a plan that includes the free allowance pays from the first paid tier on);
  - our commission is added on top, and the result is converted to the client's currency (PKR clients: USD x the rate in Settings).
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import pricing
from app.billing.service import BillingError, active_subscription, create_invoice, money, today_utc, usage_between
from app.models import Client, Invoice
from app.settings_store import get_setting


def last_day(first: date) -> date:
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def _already_invoiced(db: Session, client: Client, first: date) -> Invoice | None:
    return db.scalar(
        select(Invoice).where(Invoice.client_id == client.id, Invoice.source == "usage", Invoice.period_start == first, Invoice.status != "void")
    )


def extra_usage(db: Session, client: Client, first: date) -> dict[str, Any]:
    """What the client used above their plan in the month starting `first`, and what that costs (nothing is saved)."""
    last = last_day(first)
    sub = active_subscription(db, client.id)
    plan = sub.plan if sub else None
    events, recordings = usage_between(db, client.id, first, last)
    commission = float(get_setting(db, "billing.commission_percent"))
    rate = Decimal(str(get_setting(db, "billing.usd_to_pkr")))
    month_name = f"{first:%B %Y}"

    result: dict[str, Any] = {
        "month": first.strftime("%Y-%m"), "plan": plan.name if plan else None, "currency": client.currency,
        "commission_percent": commission, "lines": [],
    }
    total = Decimal("0")
    provider_total = 0.0
    for key, noun, used, included, tiers in (
        ("events", "events", events, plan.monthly_event_limit if plan else None, pricing.EVENT_TIERS),
        ("recordings", "recordings (videos)", recordings, plan.monthly_recording_limit if plan else None, pricing.RECORDING_TIERS),
    ):
        over = max(used - included, 0) if included else 0
        provider_usd = pricing.overage_cost(used, included, tiers)
        charge_usd = Decimal(str(round(pricing.with_commission(provider_usd, commission), 6)))
        amount = money(charge_usd if client.currency == "USD" else charge_usd * rate)
        result[key] = {"used": used, "included": included, "over": over, "provider_usd": round(provider_usd, 2), "amount": float(amount)}
        provider_total += provider_usd
        if amount > 0:
            result["lines"].append({"description": f"Extra {noun} in {month_name}: {over:,} above the {included:,} in the {plan.name} plan", "amount": str(amount)})
            total += amount

    existing = _already_invoiced(db, client, first)
    result["provider_usd"] = round(provider_total, 2)
    result["amount"] = float(total)
    result["already_invoiced"] = None if existing is None else {"id": str(existing.id), "number": existing.number, "status": existing.status, "amount": float(existing.amount)}
    result["can_invoice"] = total > 0 and existing is None
    return result


def create_extra_usage_invoice(db: Session, client: Client, first: date) -> Invoice:
    """Invoice the extra usage of one month. Refuses when there is nothing to charge or the month was already invoiced. Commits."""
    info = extra_usage(db, client, first)
    if info["already_invoiced"]:
        raise BillingError(f"The extra usage of {first:%B %Y} was already invoiced ({info['already_invoiced']['number']}).")
    if not info["lines"]:
        raise BillingError(f"{client.name} has no extra usage to charge for {first:%B %Y}.")
    today = today_utc()
    return create_invoice(
        db, client, amount=sum((Decimal(line["amount"]) for line in info["lines"]), Decimal("0")), line_items=info["lines"],
        issue_date=today, due_date=today + timedelta(days=get_setting(db, "billing.payment_terms_days")),
        period_start=first, period_end=last_day(first), source="usage",
    )
