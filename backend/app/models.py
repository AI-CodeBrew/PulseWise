"""
Database tables.

    users            people who can log in (you as admin, client owners and viewers)
    clients          a business / company that pays you
    client_members   which user belongs to which client, and their role there
    websites         a client's websites, each mapped to its own PostHog project
    audit_log        who did what, and when (logins, password changes, admin actions)

Later phases add: plans, subscriptions, invoices, payments, usage_daily, reports, alerts.
Any change here needs a migration: see backend/migrations/ and the README.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    LargeBinary,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

ROLES = ("owner", "viewer")  # roles inside a client's team
CLIENT_STATUSES = ("active", "suspended")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _created_at() -> Mapped[datetime]:
    # Set by Python (microsecond precision on every database) with the database clock as a fallback.
    return mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # always stored lowercase
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    password_hash: Mapped[str] = mapped_column(String(255))  # argon2 hash, never the password
    # Admin = you (the agency). Admins can see every client's websites.
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    # Bumped on password change/reset: every older login token stops working.
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list["ClientMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email}{' (admin)' if self.is_admin else ''}>"


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="status"),
        CheckConstraint("currency IN ('PKR', 'USD')", name="currency"),
        CheckConstraint("report_language IN ('en', 'roman_ur', 'ur')", name="report_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)  # private admin notes, never shown to the client
    # "suspended" blocks the client's users from their dashboards (Phase 7: unpaid invoices).
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    # Why it is suspended: "manual" (an admin did it) or "overdue" (unpaid invoice; lifted automatically when paid).
    suspended_reason: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")  # what this client is billed in (new clients: US dollars)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi", server_default="Asia/Karachi")  # for "Monday morning" reports
    report_language: Mapped[str] = mapped_column(String(10), default="en", server_default="en")  # en | roman_ur | ur
    weekly_report_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    whatsapp_number: Mapped[str | None] = mapped_column(String(20))  # international digits, e.g. 923001234567
    whatsapp_reports_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # opt-in: off until they say yes
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)  # the client's logo (PNG / JPEG / WebP, at most 300 KB); deferred = only loaded when asked for
    logo_mime: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = _created_at()

    members: Mapped[list["ClientMember"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    websites: Mapped[list["Website"]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Client {self.name}>"


class ClientMember(Base):
    """Links a user to a client. One user may belong to several clients."""

    __tablename__ = "client_members"
    __table_args__ = (CheckConstraint("role IN ('owner', 'viewer')", name="role"),)

    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # "owner" or "viewer"
    # Suspended = kept on the team but locked out of THIS client (their other clients, if any, are unaffected).
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _created_at()

    client: Mapped[Client] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Website(Base):
    """One client website = one PostHog project."""

    __tablename__ = "websites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(255))  # e.g. "myshop.com"

    # PostHog connection. The API key is ENCRYPTED (see app/security.py) and is only
    # decrypted inside the backend, per request. It never goes to the frontend.
    posthog_host: Mapped[str] = mapped_column(String(255))  # https://us.posthog.com
    posthog_project_id: Mapped[int] = mapped_column(BigInteger)
    posthog_org_id: Mapped[str | None] = mapped_column(String(64))
    # The project's PUBLIC token ("phc_..."), used in the tracking snippet. Not a secret.
    posthog_project_token: Mapped[str | None] = mapped_column(String(100))
    posthog_api_key_encrypted: Mapped[str] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = _created_at()

    client: Mapped[Client] = relationship(back_populates="websites")

    def __repr__(self) -> str:  # never include the key
        return f"<Website {self.name} project={self.posthog_project_id}>"


class AuditLog(Base):
    """Append-only history of important actions."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64))  # e.g. "auth.login", "website.created"
    target_type: Mapped[str | None] = mapped_column(String(32))  # e.g. "user", "website"
    target_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON().with_variant(postgresql.JSONB(), "postgresql"))


# ---------------------------------------------------------------- Phase 6: usage, alerts, jobs, settings

# JSON that is binary-indexed JSONB on PostgreSQL and plain JSON elsewhere (SQLite, in the tests).
JsonType = JSON().with_variant(postgresql.JSONB(), "postgresql")


class UsageDaily(Base):
    """How many events a website sent on one day (PostHog bills by events, so this is our cost)."""

    __tablename__ = "usage_daily"

    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)  # in the PostHog project's time zone
    events: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    pageviews: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    recordings: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class Alert(Base):
    """Something an admin should look at: tracking stopped, PostHog errors, a job failed, usage near the limit...

    At most ONE open alert per `dedupe_key` (e.g. "no_events:<website id>"): repeats only raise `occurrences`.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved')", name="status"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity"),
        Index("uq_alerts_open_dedupe", "dedupe_key", unique=True, postgresql_where=text("status = 'open'"), sqlite_where=text("status = 'open'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # no_events, posthog_error, job_failed, usage_limit, invoice_overdue...
    dedupe_key: Mapped[str] = mapped_column(String(160))
    severity: Mapped[str] = mapped_column(String(10), default="warning", server_default="warning")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open", index=True)
    occurrences: Mapped[int] = mapped_column(default=1, server_default="1")
    details: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobRun(Base):
    """One run of a background job (so you can see what ran, when, and whether it worked)."""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ok', 'error', 'skipped')", name="status"),
        Index("ix_job_runs_job_started_at", "job", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job: Mapped[str] = mapped_column(String(60))
    triggered_by: Mapped[str] = mapped_column(String(40), default="schedule", server_default="schedule")  # schedule | admin | cli
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="running", server_default="running")
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JsonType)


class AppSetting(Base):
    """Settings an admin can change in the admin panel (only the values that differ from the defaults are stored)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


# ---------------------------------------------------------------- Phase 7: plans, subscriptions, invoices, payments

CURRENCIES = ("PKR", "USD")
PAYMENT_METHODS = ("bank_transfer", "jazzcash", "easypaisa", "card", "other")
Money = Numeric(12, 2)


class Plan(Base):
    """What a client can buy: a price in each currency plus limits and feature switches."""

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    price_pkr: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), server_default="0")  # per month
    price_usd: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), server_default="0")  # per month
    monthly_event_limit: Mapped[int | None] = mapped_column(BigInteger)  # None = unlimited
    monthly_recording_limit: Mapped[int | None] = mapped_column(BigInteger)  # None = unlimited; one recording ("video") = one recorded visit
    # An introductory price for the first `intro_months` billed months (None = no intro price: the normal price applies from the start).
    intro_price_pkr: Mapped[Decimal | None] = mapped_column(Money)
    intro_price_usd: Mapped[Decimal | None] = mapped_column(Money)
    intro_months: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_websites: Mapped[int | None] = mapped_column(Integer)  # None = unlimited
    max_team_members: Mapped[int | None] = mapped_column(Integer)  # None = unlimited
    # Which dashboard parts the plan includes, e.g. {"recordings": true, "weekly_reports": false}
    features: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # inactive plans can't be sold any more
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created_at()


class Subscription(Base):
    """Which plan a client is on. At most ONE active subscription per client."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'cancelled')", name="status"),
        CheckConstraint("billing_day BETWEEN 1 AND 28", name="billing_day"),
        Index("uq_subscriptions_one_active", "client_id", unique=True, postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    started_at: Mapped[date] = mapped_column(Date)  # nothing is invoiced before this day
    billing_day: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # invoices are issued on this day of the month (1-28)
    # A special price for THIS client, in the client's currency (None = the plan's list price).
    price_override: Mapped[Decimal | None] = mapped_column(Money)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    plan: Mapped[Plan] = relationship()


class Invoice(Base):
    """A bill. Money is stored with exact decimals, never floats."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'paid', 'void')", name="status"),
        CheckConstraint("currency IN ('PKR', 'USD')", name="currency"),
        # One automatic invoice per subscription per billing period (manual invoices have no subscription).
        Index("uq_invoices_subscription_period", "subscription_id", "period_start", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(30), unique=True)  # INV-2026-0001
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"), index=True)  # invoices outlive their client's data
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(10), default="auto", server_default="auto")  # "auto" (monthly job) or "manual"
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open", index=True)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)  # [{"description", "amount"}]
    notes: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # "it is due" email
    overdue_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # "it is overdue" email
    created_at: Mapped[datetime] = _created_at()

    client: Mapped[Client] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", order_by="Payment.paid_at")


class Payment(Base):
    """Money received for an invoice (recorded by hand today; by a payment gateway later)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("currency IN ('PKR', 'USD')", name="currency"),
        # A gateway may repeat a notification: the same provider payment is recorded only once.
        Index("uq_payments_provider_ref", "provider", "provider_payment_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    method: Mapped[str] = mapped_column(String(20))  # bank_transfer, jazzcash, easypaisa, card, other
    reference: Mapped[str | None] = mapped_column(String(120))  # transaction id / receipt number
    note: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(30), default="manual", server_default="manual")
    provider_payment_id: Mapped[str | None] = mapped_column(String(120))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created_at()

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


# ---------------------------------------------------------------- Phase 8: weekly reports

REPORT_LANGUAGES = ("en", "roman_ur", "ur")


class Report(Base):
    """One weekly report for one website: the numbers, the plain-language summary, and whether it was emailed."""

    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint("summary_source IN ('ai', 'rules')", name="summary_source"),
        CheckConstraint("language IN ('en', 'roman_ur', 'ur')", name="language"),
        # One report per website per week: generating it again replaces the content.
        Index("uq_reports_website_period", "website_id", "period_start", "period_end", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)  # inclusive
    language: Mapped[str] = mapped_column(String(10), default="en", server_default="en")
    data: Mapped[dict[str, Any]] = mapped_column(JsonType)  # the numbers (visitors, top pages, ...)
    summary: Mapped[dict[str, Any]] = mapped_column(JsonType)  # {"headline", "bullets": [...], "recommendation"}
    summary_source: Mapped[str] = mapped_column(String(10), default="rules", server_default="rules")  # who wrote it
    generated_by: Mapped[str] = mapped_column(String(20), default="schedule", server_default="schedule")  # schedule | admin
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    emailed_to: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # how many people got it
    whatsapp_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


# ------------------------------------------------------------------ Shopify (Phase 9)


class ShopConnection(Base):
    """A website's Shopify store. The credentials are stored encrypted and never leave the backend."""

    __tablename__ = "shop_connections"
    __table_args__ = (CheckConstraint("auth_mode IN ('token', 'client_credentials')", name="auth_mode"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), unique=True)
    shop_domain: Mapped[str] = mapped_column(String(255))  # "my-shop.myshopify.com"
    auth_mode: Mapped[str] = mapped_column(String(24))  # token = a ready-made Admin API token; client_credentials = Dev Dashboard app
    credentials_encrypted: Mapped[str] = mapped_column(Text)  # JSON, encrypted: {"access_token"} or {"client_id","client_secret"}
    shop_name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str | None] = mapped_column(String(8))  # the shop's own currency, e.g. "PKR"
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # "we have everything updated before this"
    last_error: Mapped[str | None] = mapped_column(Text)  # why the last sync failed (admin-only)
    created_at: Mapped[datetime] = _created_at()


class ShopOrder(Base):
    """One Shopify order. No customer details are stored: the dashboard only needs the money and the products."""

    __tablename__ = "shop_orders"
    __table_args__ = (
        Index("uq_shop_orders_website_shopify", "website_id", "shopify_id", unique=True),
        Index("ix_shop_orders_website_created", "website_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"))
    shopify_id: Mapped[str] = mapped_column(String(64))  # "gid://shopify/Order/123"
    name: Mapped[str] = mapped_column(String(64))  # "#1001"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when the customer ordered
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    financial_status: Mapped[str | None] = mapped_column(String(40))  # PAID, PENDING, REFUNDED, ...
    fulfillment_status: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(8))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # current total (after edits and refunds), in the shop's currency
    refunded: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), server_default="0")
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    source_name: Mapped[str | None] = mapped_column(String(64))  # "web" = online store, "pos", ...
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["ShopOrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan", lazy="selectin")


class ShopOrderItem(Base):
    __tablename__ = "shop_order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_orders.id", ondelete="CASCADE"), index=True)
    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    sku: Mapped[str | None] = mapped_column(String(120))
    product_id: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)  # units still counted (refunded/removed ones excluded)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # price after discounts

    order: Mapped[ShopOrder] = relationship(back_populates="items")


# ------------------------------------------------------------------ "My dashboard" tiles


class DashboardPref(Base):
    """Which tiles a person chose for the Overview dashboard of one website (see app/services/tiles.py).

    One row per (user, website): everyone has their own view. No row yet = "never chose": the page asks first.
    """

    __tablename__ = "dashboard_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), primary_key=True)
    tiles: Mapped[list[str]] = mapped_column(JsonType)  # tile keys in the order shown
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())


class AnalyticsCache(Base):
    """Saved answers of the analytics service, so dashboard pages open at once (see app/saved_answers.py).

    One row per question: website + query + its values (`key` is a hash of those). Only numbers that are shown
    anyway (counts, lists, charts), never an API key. A background job keeps the most-used pages fresh.
    """

    __tablename__ = "analytics_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    website_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("websites.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")  # which query (for debugging)
    payload: Mapped[Any] = mapped_column(JsonType)  # the answer, as it was received
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
