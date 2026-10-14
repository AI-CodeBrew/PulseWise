"""Phase 7: plans, subscriptions, invoices, payments, clients.currency (+ three EXAMPLE plans).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
TABLES = ("plans", "subscriptions", "invoices", "payments")
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
Money = sa.Numeric(12, 2)


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    now = sa.func.now()
    postgres = op.get_context().dialect.name == "postgresql"

    op.add_column("clients", sa.Column("currency", sa.String(length=3), server_default="PKR", nullable=False), schema=_schema())
    if postgres:
        op.create_check_constraint(op.f("ck_clients_currency"), "clients", "currency IN ('PKR', 'USD')", schema=SCHEMA)

    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_pkr", Money, server_default="0", nullable=False),
        sa.Column("price_usd", Money, server_default="0", nullable=False),
        sa.Column("monthly_event_limit", sa.BigInteger(), nullable=True),
        sa.Column("max_websites", sa.Integer(), nullable=True),
        sa.Column("max_team_members", sa.Integer(), nullable=True),
        sa.Column("features", Json, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("slug", name="uq_plans_slug"),
        schema=SCHEMA,
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="active", nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("billing_day", sa.Integer(), server_default="1", nullable=False),
        sa.Column("price_override", Money, nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("status IN ('active', 'cancelled')", name="status"),
        sa.CheckConstraint("billing_day BETWEEN 1 AND 28", name="billing_day"),
        sa.ForeignKeyConstraint(["client_id"], [f"{SCHEMA}.clients.id"], name="fk_subscriptions_client_id_clients", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], [f"{SCHEMA}.plans.id"], name="fk_subscriptions_plan_id_plans", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        schema=SCHEMA,
    )
    op.create_index("ix_subscriptions_client_id", "subscriptions", ["client_id"], schema=_schema())
    op.create_index(
        "uq_subscriptions_one_active", "subscriptions", ["client_id"], unique=True, schema=_schema(),
        postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=10), server_default="auto", nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", Money, nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("line_items", Json, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overdue_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("status IN ('open', 'paid', 'void')", name="status"),
        sa.CheckConstraint("currency IN ('PKR', 'USD')", name="currency"),
        sa.ForeignKeyConstraint(["client_id"], [f"{SCHEMA}.clients.id"], name="fk_invoices_client_id_clients", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], [f"{SCHEMA}.subscriptions.id"], name="fk_invoices_subscription_id_subscriptions", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        sa.UniqueConstraint("number", name="uq_invoices_number"),
        schema=SCHEMA,
    )
    op.create_index("ix_invoices_client_id", "invoices", ["client_id"], schema=_schema())
    op.create_index("ix_invoices_status", "invoices", ["status"], schema=_schema())
    op.create_index("uq_invoices_subscription_period", "invoices", ["subscription_id", "period_start"], unique=True, schema=_schema())

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("amount", Money, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=30), server_default="manual", nullable=False),
        sa.Column("provider_payment_id", sa.String(length=120), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("currency IN ('PKR', 'USD')", name="currency"),
        sa.ForeignKeyConstraint(["invoice_id"], [f"{SCHEMA}.invoices.id"], name="fk_payments_invoice_id_invoices", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by"], [f"{SCHEMA}.users.id"], name="fk_payments_recorded_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        schema=SCHEMA,
    )
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"], schema=_schema())
    op.create_index("uq_payments_provider_ref", "payments", ["provider", "provider_payment_id"], unique=True, schema=_schema())

    # Three EXAMPLE plans so the admin panel isn't empty. The prices are placeholders: set your own in Admin -> Plans.
    plans = sa.table(
        "plans",
        sa.column("id", sa.Uuid()), sa.column("name", sa.String()), sa.column("slug", sa.String()), sa.column("description", sa.Text()),
        sa.column("price_pkr", Money), sa.column("price_usd", Money), sa.column("monthly_event_limit", sa.BigInteger()),
        sa.column("max_websites", sa.Integer()), sa.column("max_team_members", sa.Integer()), sa.column("features", Json),
        sa.column("sort_order", sa.Integer()),
        schema=_schema(),
    )
    off = {"sessions": False, "people": False, "live_events": False, "recordings": False, "weekly_reports": False, "shopify": False, "team_members": False}
    op.bulk_insert(plans, [
        {"id": uuid.uuid4(), "name": "Starter", "slug": "starter", "sort_order": 1,
         "description": "EXAMPLE plan (edit the price): a small website with the basic dashboard.",
         "price_pkr": Decimal("3000"), "price_usd": Decimal("12"), "monthly_event_limit": 100_000, "max_websites": 1, "max_team_members": 1,
         "features": dict(off)},
        {"id": uuid.uuid4(), "name": "Growth", "slug": "growth", "sort_order": 2,
         "description": "EXAMPLE plan (edit the price): a growing shop. Adds sessions, people, live events and the weekly report.",
         "price_pkr": Decimal("8000"), "price_usd": Decimal("29"), "monthly_event_limit": 500_000, "max_websites": 3, "max_team_members": 3,
         "features": {**off, "sessions": True, "people": True, "live_events": True, "weekly_reports": True}},
        {"id": uuid.uuid4(), "name": "Pro", "slug": "pro", "sort_order": 3,
         "description": "EXAMPLE plan (edit the price): a bigger business. Adds recordings, Shopify sales data and team members.",
         "price_pkr": Decimal("20000"), "price_usd": Decimal("75"), "monthly_event_limit": 2_000_000, "max_websites": 10, "max_team_members": 10,
         "features": {k: True for k in off}},
    ])

    if postgres:
        for table in TABLES:  # same protection as the other tables (see 0001)
            op.execute(f'ALTER TABLE "{SCHEMA}"."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("payments", schema=SCHEMA)
    op.drop_table("invoices", schema=SCHEMA)
    op.drop_table("subscriptions", schema=SCHEMA)
    op.drop_table("plans", schema=SCHEMA)
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_clients_currency", "clients", schema=SCHEMA, type_="check")
    op.drop_column("clients", "currency", schema=_schema())
