"""
Admin API, part 3: plans, subscriptions, invoices, payments and the business overview.
The whole router requires an admin (same rule as routers/admin.py).
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import pricing
from app.audit import audit
from app.billing import notifications
from app.billing.extra_usage import create_extra_usage_invoice, extra_usage
from app.billing.service import (
    FEATURES,
    BillingError,
    balance,
    create_invoice,
    is_overdue,
    money,
    price_for,
    record_payment,
    today_utc,
    void_invoice,
)
from app.billing.summary import billing_summary, invoice_dict, num, plan_dict
from app.deps import AdminUser, DbSession, client_ip, require_admin
from app.models import PAYMENT_METHODS, Client, Invoice, Payment, Plan, Subscription
from app.params import CursorParam, LimitParam, decode_cursor, encode_cursor
from app.routers.admin_ops import MonthParam, month_range, usage_by_website
from app.settings_store import get_setting

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

Method = Literal["bank_transfer", "jazzcash", "easypaisa", "card", "other"]
BigMoney = Annotated[Decimal, Field(ge=0, lt=Decimal("100000000"), max_digits=12, decimal_places=2)]


def _bad(message: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=message)


def _get_client(db, client_id: uuid.UUID) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found.")
    return client


def _get_invoice(db, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice


def _features(raw: dict[str, Any]) -> dict[str, bool]:
    unknown = set(raw) - set(FEATURES)
    if unknown:
        raise _bad(f"Unknown feature: {', '.join(sorted(unknown))}.")
    if not all(isinstance(v, bool) for v in raw.values()):
        raise _bad("Each feature must be true or false.")
    return {name: bool(raw.get(name, False)) for name in FEATURES}


# ------------------------------------------------------------------ plans


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    price_pkr: BigMoney = Decimal("0")
    price_usd: BigMoney = Decimal("0")
    intro_price_pkr: BigMoney | None = None  # the price of the first month(s); None = no introductory price
    intro_price_usd: BigMoney | None = None
    intro_months: int = Field(default=1, ge=1, le=12)
    monthly_event_limit: int | None = Field(default=None, ge=1)  # None = unlimited
    monthly_recording_limit: int | None = Field(default=None, ge=1)  # recordings = "videos"; None = unlimited
    max_websites: int | None = Field(default=None, ge=1)
    max_team_members: int | None = Field(default=None, ge=1)
    features: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    sort_order: int = 0


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    price_pkr: BigMoney | None = None
    price_usd: BigMoney | None = None
    intro_price_pkr: BigMoney | None = None
    intro_price_usd: BigMoney | None = None
    intro_months: int | None = Field(default=None, ge=1, le=12)
    monthly_event_limit: int | None = Field(default=None, ge=1)
    monthly_recording_limit: int | None = Field(default=None, ge=1)
    max_websites: int | None = Field(default=None, ge=1)
    max_team_members: int | None = Field(default=None, ge=1)
    features: dict[str, Any] | None = None
    is_active: bool | None = None
    sort_order: int | None = None


def _slug(db, name: str) -> str:
    base = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-") or "plan"
    slug, n = base, 2
    while db.scalar(select(Plan.id).where(Plan.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def _quote(db, events: int, recordings: int) -> dict[str, Any]:
    """What a plan with these monthly amounts SHOULD cost: base price + the provider's price above its free allowance + our commission."""
    return pricing.suggest_price(
        events, recordings, base_usd=float(get_setting(db, "billing.base_price_usd")),
        commission_percent=float(get_setting(db, "billing.commission_percent")), usd_to_pkr=float(get_setting(db, "billing.usd_to_pkr")),
    )


def _plan_row(db, plan: Plan) -> dict[str, Any]:
    # An "unlimited" plan can't be priced from its limits, so it has no suggestion.
    quote = _quote(db, plan.monthly_event_limit, plan.monthly_recording_limit) if plan.monthly_event_limit and plan.monthly_recording_limit else None
    return {**plan_dict(plan), "quote": quote}


def _check_intro_prices(plan: Plan) -> None:
    """A first-month price above the normal price is almost certainly a typing mistake."""
    for intro, regular, currency in ((plan.intro_price_usd, plan.price_usd, "USD"), (plan.intro_price_pkr, plan.price_pkr, "PKR")):
        if intro is not None and money(intro) > money(regular):
            raise _bad(f"The first-month price ({currency}) can't be higher than the normal monthly price.")


def _optional_money(value: Decimal | None) -> Decimal | None:
    return None if value is None else money(value)


@router.get("/plans", summary="All plans, with how many clients are on each")
def list_plans(db: DbSession):
    counts = dict(db.execute(select(Subscription.plan_id, func.count()).where(Subscription.status == "active").group_by(Subscription.plan_id)).all())
    return {
        "results": [{**_plan_row(db, p), "clients": counts.get(p.id, 0)} for p in db.scalars(select(Plan).order_by(Plan.sort_order, Plan.name))],
        # what PostHog gives away free every month (the Plans page offers it as a starting point for a plan's limits)
        "free_allowance": {"events": int(pricing.FREE_EVENTS), "recordings": int(pricing.FREE_RECORDINGS)},
    }


@router.get("/pricing/quote", summary="What a plan with these monthly amounts should cost (base price + PostHog's price above the free allowance + your commission)")
def pricing_quote(
    db: DbSession,
    events: Annotated[int, Query(ge=1, le=10_000_000_000)],
    recordings: Annotated[int, Query(ge=1, le=1_000_000_000)],
):
    return _quote(db, events, recordings)


@router.post("/plans", status_code=201, summary="Create a plan")
def create_plan(body: PlanIn, request: Request, admin: AdminUser, db: DbSession):
    plan = Plan(
        name=body.name.strip(), slug=_slug(db, body.name), description=(body.description or "").strip() or None,
        price_pkr=money(body.price_pkr), price_usd=money(body.price_usd),
        intro_price_pkr=_optional_money(body.intro_price_pkr), intro_price_usd=_optional_money(body.intro_price_usd), intro_months=body.intro_months,
        monthly_event_limit=body.monthly_event_limit, monthly_recording_limit=body.monthly_recording_limit,
        max_websites=body.max_websites, max_team_members=body.max_team_members, features=_features(body.features),
        is_active=body.is_active, sort_order=body.sort_order,
    )
    _check_intro_prices(plan)
    db.add(plan)
    db.flush()
    audit(db, "admin.plan_created", actor_id=admin.id, target_type="plan", target_id=plan.id, ip=client_ip(request), details={"name": plan.name})
    db.commit()
    return _plan_row(db, plan)


@router.patch("/plans/{plan_id}", summary="Edit a plan (new prices apply to FUTURE invoices only)")
def update_plan(plan_id: uuid.UUID, body: PlanPatch, request: Request, admin: AdminUser, db: DbSession):
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    changes = body.model_dump(exclude_unset=True)
    for field in ("monthly_event_limit", "monthly_recording_limit", "max_websites", "max_team_members"):
        if field in changes:  # null = unlimited
            setattr(plan, field, changes[field])
    for field in ("name", "intro_months", "is_active", "sort_order"):
        if changes.get(field) is not None:  # (these can't be empty)
            setattr(plan, field, changes[field].strip() if field == "name" else changes[field])
    if "description" in changes:
        plan.description = (changes["description"] or "").strip() or None
    for field in ("price_pkr", "price_usd"):
        if changes.get(field) is not None:
            setattr(plan, field, money(changes[field]))
    for field in ("intro_price_pkr", "intro_price_usd"):
        if field in changes:  # null = take the introductory price away
            setattr(plan, field, _optional_money(changes[field]))
    if "features" in changes and changes["features"] is not None:
        plan.features = _features(changes["features"])
    try:
        _check_intro_prices(plan)
    except HTTPException:
        db.rollback()  # nothing of this edit is kept
        raise
    audit(db, "admin.plan_updated", actor_id=admin.id, target_type="plan", target_id=plan.id, ip=client_ip(request), details={"fields": sorted(changes)})
    db.commit()
    return _plan_row(db, plan)


@router.delete("/plans/{plan_id}", summary="Delete a plan nobody has ever used")
def delete_plan(plan_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    if db.scalar(select(Subscription.id).where(Subscription.plan_id == plan.id).limit(1)):
        raise _bad("Clients are or were on this plan. Switch it off (inactive) instead of deleting it.", 409)
    audit(db, "admin.plan_deleted", actor_id=admin.id, target_type="plan", target_id=plan.id, ip=client_ip(request), details={"name": plan.name})
    db.delete(plan)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ a client's subscription


class SubscriptionIn(BaseModel):
    plan_id: uuid.UUID
    billing_day: int | None = Field(default=None, ge=1, le=28)
    started_at: date | None = None  # only used when the client has no subscription yet
    price_override: BigMoney | None = None  # a special price in the client's currency (None = list price)


@router.get("/clients/{client_id}/billing", summary="A client's plan, usage and invoices (as the admin sees it)")
def client_billing(client_id: uuid.UUID, db: DbSession):
    return billing_summary(db, _get_client(db, client_id))


@router.put("/clients/{client_id}/subscription", summary="Put a client on a plan (or change their plan)")
def set_subscription(client_id: uuid.UUID, body: SubscriptionIn, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    plan = db.get(Plan, body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    sub = db.scalar(select(Subscription).where(Subscription.client_id == client.id, Subscription.status == "active"))
    if sub is None:
        if not plan.is_active:
            raise _bad("That plan is switched off and can't be sold.")
        start = body.started_at or today_utc()
        sub = Subscription(client_id=client.id, plan_id=plan.id, started_at=start, billing_day=body.billing_day or min(start.day, 28),
                           price_override=money(body.price_override) if body.price_override is not None else None)
        db.add(sub)
        action = "admin.subscription_created"
    else:
        if plan.id != sub.plan_id and not plan.is_active:
            raise _bad("That plan is switched off and can't be sold.")
        sub.plan_id = plan.id
        if body.billing_day:
            sub.billing_day = body.billing_day
        sub.price_override = money(body.price_override) if body.price_override is not None else None
        action = "admin.subscription_changed"
    db.flush()
    audit(db, action, actor_id=admin.id, target_type="client", target_id=client.id, ip=client_ip(request),
          details={"plan": plan.name, "billing_day": sub.billing_day, "price_override": str(sub.price_override) if sub.price_override is not None else None})
    db.commit()
    return billing_summary(db, client)


@router.delete("/clients/{client_id}/subscription", summary="Cancel a client's subscription (no more invoices)")
def cancel_subscription(client_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    sub = db.scalar(select(Subscription).where(Subscription.client_id == client.id, Subscription.status == "active"))
    if sub is None:
        raise _bad("This client has no subscription.", 404)
    sub.status = "cancelled"
    sub.cancelled_at = datetime.now(timezone.utc)
    audit(db, "admin.subscription_cancelled", actor_id=admin.id, target_type="client", target_id=client.id, ip=client_ip(request), details={"plan": sub.plan.name})
    db.commit()
    return billing_summary(db, client)


# ------------------------------------------------------------------ invoices and payments


class ManualInvoiceIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    amount: BigMoney = Field(gt=0)
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


class PaymentIn(BaseModel):
    method: Method
    amount: BigMoney | None = Field(default=None, gt=0)  # empty = the whole balance
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)
    paid_on: date | None = None


def _invoice_row(invoice: Invoice, today: date) -> dict[str, Any]:
    return {**invoice_dict(invoice, today), "client_id": str(invoice.client_id), "client_name": invoice.client.name}


@router.get("/invoices", summary="Invoices (newest first)")
def list_invoices(
    db: DbSession,
    status: Annotated[str, Query(pattern="^(all|open|overdue|paid|void)$")] = "all",
    client_id: uuid.UUID | None = None,
    limit: LimitParam = 50,
    cursor: CursorParam = None,
):
    today = today_utc()
    query = select(Invoice).order_by(Invoice.created_at.desc(), Invoice.id.desc())
    if status == "overdue":
        query = query.where(Invoice.status == "open", Invoice.due_date < today)
    elif status != "all":
        query = query.where(Invoice.status == status)
    if client_id:
        query = query.where(Invoice.client_id == client_id)
    position = decode_cursor(cursor)
    if position:
        try:
            at, last_id = datetime.fromisoformat(position["t"]), uuid.UUID(position["i"])
        except (KeyError, ValueError):
            raise HTTPException(status_code=422, detail="Invalid cursor") from None
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        query = query.where((Invoice.created_at < at) | ((Invoice.created_at == at) & (Invoice.id < last_id)))
    rows = db.scalars(query.limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "results": [_invoice_row(i, today) for i in rows],
        "next_cursor": encode_cursor(t=rows[-1].created_at.isoformat(), i=str(rows[-1].id)) if more and rows else None,
    }


@router.get("/invoices/{invoice_id}", summary="One invoice with its payments")
def get_invoice(invoice_id: uuid.UUID, db: DbSession):
    invoice = _get_invoice(db, invoice_id)
    return {**invoice_dict(invoice, with_payments=True), "client_id": str(invoice.client_id), "client_name": invoice.client.name}


@router.post("/clients/{client_id}/invoices", status_code=201, summary="Create a one-off invoice")
def create_manual_invoice(client_id: uuid.UUID, body: ManualInvoiceIn, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    today = today_utc()
    try:
        invoice = create_invoice(
            db, client, amount=money(body.amount), source="manual", issue_date=today,
            due_date=body.due_date or today + timedelta(days=get_setting(db, "billing.payment_terms_days")),
            line_items=[{"description": body.description.strip(), "amount": str(money(body.amount))}], notes=(body.notes or "").strip() or None,
        )
    except BillingError as exc:
        raise _bad(str(exc)) from None
    audit(db, "admin.invoice_created", actor_id=admin.id, target_type="invoice", target_id=invoice.id, ip=client_ip(request),
          details={"number": invoice.number, "client_id": str(client.id), "amount": str(invoice.amount), "source": "manual"})
    db.commit()
    return invoice_dict(invoice, with_payments=True)


class ExtraUsageIn(BaseModel):
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")  # YYYY-MM, default: this month


@router.get("/clients/{client_id}/extra-usage", summary="What a client used above their plan in a month, priced at PostHog's price + your commission")
def client_extra_usage(client_id: uuid.UUID, db: DbSession, month: MonthParam = None):
    first, _ = month_range(month)
    return extra_usage(db, _get_client(db, client_id), first)


@router.post("/clients/{client_id}/extra-usage-invoice", status_code=201, summary="Create the invoice for that extra usage (once per month)")
def create_extra_usage_invoice_api(client_id: uuid.UUID, body: ExtraUsageIn, request: Request, admin: AdminUser, db: DbSession):
    client = _get_client(db, client_id)
    first, _ = month_range(body.month)
    try:
        invoice = create_extra_usage_invoice(db, client, first)
    except BillingError as exc:
        raise _bad(str(exc), 409) from None
    audit(db, "admin.invoice_created", actor_id=admin.id, target_type="invoice", target_id=invoice.id, ip=client_ip(request),
          details={"number": invoice.number, "client_id": str(client.id), "amount": str(invoice.amount), "source": "usage", "month": first.strftime("%Y-%m")})
    db.commit()
    return invoice_dict(invoice, with_payments=True)


@router.post("/invoices/{invoice_id}/payments", status_code=201, summary="Record a payment (\"mark as paid\")")
def add_payment(invoice_id: uuid.UUID, body: PaymentIn, request: Request, admin: AdminUser, db: DbSession):
    invoice = _get_invoice(db, invoice_id)
    paid_at = datetime.combine(body.paid_on, datetime.min.time(), tzinfo=timezone.utc) if body.paid_on else None
    try:
        payment = record_payment(
            db, invoice, method=body.method, amount=money(body.amount) if body.amount is not None else None,
            reference=body.reference, note=body.note, paid_at=paid_at, recorded_by=admin.id,
        )
    except BillingError as exc:
        raise _bad(str(exc), 409) from None
    audit(db, "admin.payment_recorded", actor_id=admin.id, target_type="invoice", target_id=invoice.id, ip=client_ip(request),
          details={"number": invoice.number, "amount": str(payment.amount), "method": body.method, "reference": body.reference, "invoice_status": invoice.status})
    db.commit()
    db.refresh(invoice)
    return invoice_dict(invoice, with_payments=True)


@router.post("/invoices/{invoice_id}/void", summary="Cancel an invoice that has no payments")
def void(invoice_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    invoice = _get_invoice(db, invoice_id)
    try:
        void_invoice(db, invoice)
    except BillingError as exc:
        raise _bad(str(exc), 409) from None
    audit(db, "admin.invoice_voided", actor_id=admin.id, target_type="invoice", target_id=invoice.id, ip=client_ip(request), details={"number": invoice.number})
    db.commit()
    return invoice_dict(invoice, with_payments=True)


@router.post("/invoices/{invoice_id}/send", summary="Email the invoice to the client now")
def send_invoice(invoice_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    from app import emailer

    invoice = _get_invoice(db, invoice_id)
    if not emailer.email_configured():
        raise _bad("Email sending isn't set up yet (add the SMTP_* settings to backend/.env).", 409)
    to = notifications.recipients(db, invoice.client)
    if not to:
        raise _bad("This client has no contact email or owner to send it to.", 409)
    sent = notifications.send_invoice_email(db, invoice, invoice.client)
    audit(db, "admin.invoice_emailed", actor_id=admin.id, target_type="invoice", target_id=invoice.id, ip=client_ip(request),
          details={"number": invoice.number, "sent": sent})
    db.commit()
    return {"sent": sent, "to": to}


@router.get("/invoices/{invoice_id}/pdf", summary="The invoice as a PDF")
def invoice_pdf(invoice_id: uuid.UUID, db: DbSession):
    invoice = _get_invoice(db, invoice_id)
    return Response(
        content=notifications.render_pdf(db, invoice, invoice.client),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.number}.pdf"'},
    )


# ------------------------------------------------------------------ business overview


def _by_currency(rows: list[tuple[str, Decimal]]) -> dict[str, float]:
    out = {"PKR": Decimal("0"), "USD": Decimal("0")}
    for currency, amount in rows:
        out[currency] += Decimal(str(amount))
    return {k: float(v) for k, v in out.items()}


@router.get("/business", summary="Money overview: income, unpaid bills, and what PostHog costs you")
def business_overview(db: DbSession):
    today = today_utc()
    rate = Decimal(str(get_setting(db, "billing.usd_to_pkr")))

    clients = db.scalars(select(Client)).all()
    subs = db.scalars(select(Subscription).where(Subscription.status == "active")).all()
    by_id = {c.id: c for c in clients}
    mrr = _by_currency([(by_id[s.client_id].currency, price_for(by_id[s.client_id], s)) for s in subs if s.client_id in by_id])

    open_invoices = db.scalars(select(Invoice).where(Invoice.status == "open")).all()
    unpaid = _by_currency([(i.currency, balance(i)) for i in open_invoices])
    overdue_invoices = [i for i in open_invoices if is_overdue(i, today)]
    overdue = _by_currency([(i.currency, balance(i)) for i in overdue_invoices])

    first = today.replace(day=1)
    received = _by_currency([
        (p.currency, p.amount) for p in db.scalars(select(Payment).where(Payment.paid_at >= datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)))
    ])

    # What PostHog is costing this month (the same estimate as the Usage page).
    month_first, month_last = month_range(None)
    websites = usage_by_website(db, month_first, month_last)
    events = sum(w["events"] for w in websites)
    recordings = sum(w["recordings"] for w in websites)
    elapsed = max((today - month_first).days + 1, 1)
    days = (month_last - month_first).days + 1
    factor = days / elapsed
    cost_now = pricing.event_cost(events) + pricing.recording_cost(recordings)
    cost_projected = pricing.event_cost(events * factor) + pricing.recording_cost(recordings * factor)

    mrr_total_pkr = Decimal(str(mrr["PKR"])) + Decimal(str(mrr["USD"])) * rate
    return {
        "clients": {"total": len(clients), "active": sum(c.status == "active" for c in clients), "suspended": sum(c.status == "suspended" for c in clients),
                    "paying": len(subs), "without_plan": len(clients) - len(subs)},
        "mrr": {**mrr, "total_pkr": float(mrr_total_pkr), "usd_to_pkr": float(rate)},
        "unpaid": {**unpaid, "count": len(open_invoices), "overdue_count": len(overdue_invoices), "overdue": overdue},
        "received_this_month": received,
        "posthog_cost_usd": {"so_far": round(cost_now, 2), "projected": round(cost_projected, 2)},
        "estimated_margin_pkr": float(mrr_total_pkr - Decimal(str(cost_projected)) * rate),
        "note": "MRR = what active subscriptions bill per month. The PostHog cost is an estimate (see Usage & cost).",
    }
