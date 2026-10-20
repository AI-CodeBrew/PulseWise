"""
Billing rules, in one place (the API, the daily job and the tests all use these functions).

  - Money is `Decimal` with 2 places, never float.
  - A client with NO subscription is unrestricted and never invoiced (that is you / internal accounts / not yet sold).
  - Invoices are issued on the subscription's billing day, in advance, for one month.
  - An unpaid invoice past its due date + grace period suspends the client; paying it lifts the suspension again.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts import notify_admins, raise_alert, resolve_alerts
from app.audit import audit
from app.models import Client, Invoice, Payment, Plan, Subscription, UsageDaily, Website
from app.settings_store import get_setting

log = logging.getLogger(__name__)

CENT = Decimal("0.01")

# The parts of the dashboard a plan can switch on or off.
FEATURES: dict[str, str] = {
    "sessions": "Sessions",
    "people": "People",
    "live_events": "Live events",
    "recordings": "Recordings",
    "weekly_reports": "Weekly reports",
    "shopify": "Shopify sales",
    "team_members": "Team members",
}


class BillingError(ValueError):
    """A billing action that can't be done; the message is safe to show to the admin."""


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ plans and features


def active_subscription(db: Session, client_id: uuid.UUID) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.client_id == client_id, Subscription.status == "active"))


def plan_for_client(db: Session, client_id: uuid.UUID) -> Plan | None:
    sub = active_subscription(db, client_id)
    return sub.plan if sub else None


def client_features(db: Session, client_id: uuid.UUID) -> dict[str, bool]:
    """Which dashboard parts this client's plan includes. No plan = everything (unrestricted)."""
    plan = plan_for_client(db, client_id)
    if plan is None:
        return {name: True for name in FEATURES}
    return {name: bool((plan.features or {}).get(name, False)) for name in FEATURES}


def has_feature(db: Session, client_id: uuid.UUID, feature: str) -> bool:
    return client_features(db, client_id).get(feature, False)


def price_for(client: Client, subscription: Subscription) -> Decimal:
    """What the client pays per month, in the client's currency (the normal price, not the introductory one)."""
    if subscription.price_override is not None:
        return money(subscription.price_override)
    plan = subscription.plan
    return money(plan.price_usd if client.currency == "USD" else plan.price_pkr)


def intro_price_for(client: Client, subscription: Subscription) -> Decimal | None:
    """The plan's introductory price in the client's currency (None = this plan has none)."""
    plan = subscription.plan
    price = plan.intro_price_usd if client.currency == "USD" else plan.intro_price_pkr
    return None if price is None else money(price)


def first_billing_date(subscription: Subscription) -> date:
    """The day of a subscription's FIRST invoice: the billing day on or after the start date."""
    start = subscription.started_at
    if start.day <= subscription.billing_day:
        return start.replace(day=subscription.billing_day)
    return (start.replace(day=1) + timedelta(days=32)).replace(day=subscription.billing_day)


def billed_month_number(subscription: Subscription, period_start: date) -> int:
    """1 for the first billed month of a subscription, 2 for the second... (counted by the calendar, not by invoices,
    so a free first month or a cancelled invoice can't make the introductory price last longer)."""
    first = first_billing_date(subscription)
    return (period_start.year - first.year) * 12 + (period_start.month - first.month) + 1


def invoice_price_for(client: Client, subscription: Subscription, period_start: date) -> tuple[Decimal, bool]:
    """What the invoice for the month starting `period_start` costs, and whether that is the introductory price.

    A special price for one client (price_override) always wins. Otherwise the first `intro_months` billed months
    cost the plan's introductory price (if it has one), and every month after that the normal price.
    """
    if subscription.price_override is not None:
        return money(subscription.price_override), False
    intro = intro_price_for(client, subscription)
    if intro is not None and billed_month_number(subscription, period_start) <= subscription.plan.intro_months:
        return intro, True
    return price_for(client, subscription), False


def next_invoice_start(db: Session, subscription: Subscription, today: date) -> date:
    """The first day of the billing period the NEXT invoice will cover."""
    first = first_billing_date(subscription)
    if first > today:
        return first  # billing hasn't begun yet
    latest = latest_billing_date(subscription.billing_day, today)
    if latest == today and db.scalar(select(Invoice.id).where(Invoice.subscription_id == subscription.id, Invoice.period_start == latest)) is None:
        return latest  # due today: the daily job just hasn't issued it yet
    return next_billing_date(subscription.billing_day, today)


def usage_between(db: Session, client_id: uuid.UUID, first: date, last: date) -> tuple[int, int]:
    """(events, recordings) of all the client's websites from `first` to `last`, both days included."""
    events, recordings = db.execute(
        select(func.coalesce(func.sum(UsageDaily.events), 0), func.coalesce(func.sum(UsageDaily.recordings), 0))
        .join(Website, Website.id == UsageDaily.website_id)
        .where(Website.client_id == client_id, UsageDaily.day >= first, UsageDaily.day <= last)
    ).one()
    return int(events or 0), int(recordings or 0)


def month_usage(db: Session, client_id: uuid.UUID, today: date | None = None) -> tuple[int, int]:
    """(events, recordings) this calendar month across all of the client's websites."""
    today = today or today_utc()
    return usage_between(db, client_id, today.replace(day=1), today)


def check_website_limit(db: Session, client_id: uuid.UUID) -> None:
    plan = plan_for_client(db, client_id)
    if plan is not None and plan.max_websites is not None:
        count = db.scalar(select(func.count()).select_from(Website).where(Website.client_id == client_id, Website.is_active.is_(True))) or 0
        if count >= plan.max_websites:
            raise BillingError(f"The {plan.name} plan allows {plan.max_websites} website{'s' if plan.max_websites != 1 else ''}, and this client already has {count}.")


def check_member_limit(db: Session, client_id: uuid.UUID) -> None:
    plan = plan_for_client(db, client_id)
    if plan is not None and plan.max_team_members is not None:
        from app.models import ClientMember

        count = db.scalar(select(func.count()).select_from(ClientMember).where(ClientMember.client_id == client_id)) or 0
        if count >= plan.max_team_members:
            raise BillingError(f"The {plan.name} plan allows {plan.max_team_members} team member{'s' if plan.max_team_members != 1 else ''}, and this client already has {count}.")


# ------------------------------------------------------------------ invoices


def next_invoice_number(db: Session, year: int, attempt: int = 0) -> str:
    prefix = f"INV-{year}-"
    count = db.scalar(select(func.count()).select_from(Invoice).where(Invoice.number.startswith(prefix, autoescape=True))) or 0
    return f"{prefix}{count + 1 + attempt:04d}"


def paid_amount(invoice: Invoice) -> Decimal:
    return sum((p.amount for p in invoice.payments), Decimal("0"))


def balance(invoice: Invoice) -> Decimal:
    return Decimal("0") if invoice.status in ("paid", "void") else max(money(invoice.amount) - paid_amount(invoice), Decimal("0"))


def is_overdue(invoice: Invoice, today: date | None = None) -> bool:
    return invoice.status == "open" and (today or today_utc()) > invoice.due_date


def create_invoice(
    db: Session,
    client: Client,
    *,
    amount: Decimal,
    line_items: list[dict[str, Any]],
    issue_date: date,
    due_date: date,
    subscription: Subscription | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
    source: str = "auto",
    notes: str | None = None,
) -> Invoice:
    """Create an invoice with the next free number. Commits."""
    if amount <= 0:
        raise BillingError("An invoice amount must be more than zero.")
    if due_date < issue_date:
        raise BillingError("The due date can't be before the issue date.")
    for attempt in range(6):  # two invoices created at the same moment could pick the same number: try the next one
        invoice = Invoice(
            number=next_invoice_number(db, issue_date.year, attempt), client_id=client.id,
            subscription_id=subscription.id if subscription else None, source=source,
            period_start=period_start, period_end=period_end, issue_date=issue_date, due_date=due_date,
            currency=client.currency, amount=money(amount), line_items=line_items, notes=notes,
        )
        db.add(invoice)
        try:
            db.commit()
            return invoice
        except IntegrityError:
            db.rollback()
            if subscription is not None and db.scalar(
                select(Invoice.id).where(Invoice.subscription_id == subscription.id, Invoice.period_start == period_start)
            ):
                raise BillingError("This period was already invoiced.") from None
    raise BillingError("Could not allocate an invoice number. Please try again.")


def latest_billing_date(billing_day: int, today: date) -> date:
    """The most recent day (today or earlier) that falls on the billing day of a month."""
    if today.day >= billing_day:
        return today.replace(day=billing_day)
    return (today.replace(day=1) - timedelta(days=1)).replace(day=billing_day)


def next_billing_date(billing_day: int, today: date) -> date:
    start = latest_billing_date(billing_day, today)
    return (start.replace(day=1) + timedelta(days=32)).replace(day=billing_day)


def generate_due_invoices(db: Session, today: date | None = None) -> list[Invoice]:
    """Issue this month's invoice for every active subscription that doesn't have one yet. Safe to run many times."""
    today = today or today_utc()
    terms = get_setting(db, "billing.payment_terms_days")
    created: list[Invoice] = []
    for sub in db.scalars(select(Subscription).where(Subscription.status == "active")):
        client = db.get(Client, sub.client_id)
        if client is None:
            continue
        start = latest_billing_date(sub.billing_day, today)
        if start < sub.started_at:
            continue  # billing hasn't begun yet
        if db.scalar(select(Invoice.id).where(Invoice.subscription_id == sub.id, Invoice.period_start == start)):
            continue  # already invoiced
        amount, intro = invoice_price_for(client, sub, start)
        if amount <= 0:
            continue  # a free plan (or a free first month)
        end = next_billing_date(sub.billing_day, today) - timedelta(days=1)
        kind = ("first month price" if sub.plan.intro_months == 1 else "introductory price") if intro else None
        try:
            invoice = create_invoice(
                db, client, amount=amount, subscription=sub, period_start=start, period_end=end,
                issue_date=today, due_date=today + timedelta(days=terms), source="auto",
                line_items=[{"description": f"{sub.plan.name} plan{', ' + kind if kind else ''} ({start:%d %b %Y} to {end:%d %b %Y})", "amount": str(amount)}],
            )
        except BillingError as exc:
            log.warning("Not invoicing %s: %s", client.name, exc)
            continue
        audit(db, "billing.invoice_created", target_type="invoice", target_id=invoice.id, details={"number": invoice.number, "source": "auto", "client_id": str(client.id)})
        db.commit()
        created.append(invoice)
    return created


# ------------------------------------------------------------------ payments


def record_payment(
    db: Session,
    invoice: Invoice,
    *,
    method: str,
    amount: Decimal | None = None,
    reference: str | None = None,
    note: str | None = None,
    paid_at: datetime | None = None,
    provider: str = "manual",
    provider_payment_id: str | None = None,
    recorded_by: uuid.UUID | None = None,
) -> Payment:
    """Record money received. If the invoice is now fully paid it is closed (and a suspension for it lifted). Commits.

    Safe to call twice with the same provider payment id (payment gateways repeat notifications).
    """
    if provider_payment_id:
        existing = db.scalar(select(Payment).where(Payment.provider == provider, Payment.provider_payment_id == provider_payment_id))
        if existing is not None:
            return existing
    if invoice.status == "void":
        raise BillingError("This invoice was cancelled.")
    if invoice.status == "paid":
        raise BillingError("This invoice is already paid.")
    due = balance(invoice)
    amount = money(amount) if amount is not None else due
    if amount <= 0:
        raise BillingError("The payment amount must be more than zero.")
    if amount > due:
        raise BillingError(f"That is more than the {due} still owed on this invoice.")

    payment = Payment(
        invoice_id=invoice.id, amount=amount, currency=invoice.currency, method=method, reference=(reference or None), note=note,
        provider=provider, provider_payment_id=provider_payment_id, paid_at=paid_at or datetime.now(timezone.utc), recorded_by=recorded_by,
    )
    db.add(payment)
    db.flush()
    db.refresh(invoice)
    if balance(invoice) <= 0:
        invoice.status = "paid"
        invoice.paid_at = payment.paid_at
        resolve_alerts(db, dedupe_key=f"invoice_overdue:{invoice.id}")
    db.commit()
    lift_overdue_suspensions(db)
    return payment


def void_invoice(db: Session, invoice: Invoice) -> None:
    if invoice.status == "paid" or invoice.payments:
        raise BillingError("An invoice that has payments can't be cancelled.")
    invoice.status = "void"
    resolve_alerts(db, dedupe_key=f"invoice_overdue:{invoice.id}")
    db.commit()
    lift_overdue_suspensions(db)


# ------------------------------------------------------------------ overdue invoices and suspension


def _suspension_cutoff(db: Session, today: date) -> date:
    return today - timedelta(days=get_setting(db, "billing.grace_days"))


def lift_overdue_suspensions(db: Session, today: date | None = None) -> list[Client]:
    """Re-activate clients that were suspended for non-payment but have nothing overdue beyond the grace period now."""
    today = today or today_utc()
    cutoff = _suspension_cutoff(db, today)
    lifted = []
    for client in db.scalars(select(Client).where(Client.status == "suspended", Client.suspended_reason == "overdue")):
        still_bad = db.scalar(select(Invoice.id).where(Invoice.client_id == client.id, Invoice.status == "open", Invoice.due_date < cutoff).limit(1))
        if still_bad is None:
            client.status = "active"
            client.suspended_reason = None
            audit(db, "billing.reactivated", target_type="client", target_id=client.id, details={"reason": "no overdue invoices"})
            lifted.append(client)
    if lifted:
        db.commit()
    return lifted


def apply_overdue_rules(db: Session, today: date | None = None) -> dict[str, Any]:
    """The daily rules for unpaid invoices: reminders, alerts, and suspension after the grace period."""
    from app.billing import notifications  # (imported here: it needs the PDF and email code)

    today = today or today_utc()
    cutoff = _suspension_cutoff(db, today)
    extra = get_setting(db, "alerts.extra_recipients")
    summary: dict[str, Any] = {"reminded": 0, "overdue": 0, "suspended": [], "reactivated": []}

    for invoice in db.scalars(select(Invoice).where(Invoice.status == "open").order_by(Invoice.due_date)):
        client = db.get(Client, invoice.client_id)
        if client is None:
            continue
        if today >= invoice.due_date - timedelta(days=1) and today <= invoice.due_date and invoice.reminder_sent_at is None:
            if notifications.send_due_reminder(db, invoice, client):
                summary["reminded"] += 1
        if today > invoice.due_date:
            summary["overdue"] += 1
            days_late = (today - invoice.due_date).days
            beyond_grace = invoice.due_date < cutoff
            alert, created = raise_alert(
                db, kind="invoice_overdue", dedupe_key=f"invoice_overdue:{invoice.id}", client_id=client.id,
                severity="critical" if beyond_grace else "warning",
                message=f"Invoice {invoice.number} of {client.name} ({invoice.currency} {invoice.amount}) is {days_late} day{'s' if days_late != 1 else ''} overdue."
                + (" The account is suspended." if beyond_grace else ""),
                details={"invoice_id": str(invoice.id), "days_late": days_late},
            )
            if created:
                notify_admins(alert, extra)
            if invoice.overdue_notice_sent_at is None:
                notifications.send_overdue_notice(db, invoice, client)
            if beyond_grace and client.status == "active":
                client.status = "suspended"
                client.suspended_reason = "overdue"
                audit(db, "billing.suspended", target_type="client", target_id=client.id, details={"invoice": invoice.number, "days_late": days_late})
                db.commit()
                summary["suspended"].append(client.name)

    summary["reactivated"] = [c.name for c in lift_overdue_suspensions(db, today)]
    return summary
