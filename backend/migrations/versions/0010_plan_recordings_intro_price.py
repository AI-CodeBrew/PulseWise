"""Plans get a recordings ("videos") limit and an introductory first-month price; the three example plans are updated.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19
"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
Money = sa.Numeric(12, 2)
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


# The three EXAMPLE plans of migration 0004, rebuilt around what the analytics provider gives away free each month
# (1,000,000 events and 5,000 recordings). Price = a base price of $30 + the provider's price for anything above the
# free part + a 30% commission. For example Growth: 1.5M events and 10,000 recordings cost the provider $50, +30% = $65,
# + $30 base = $95. PKR = USD x 280. They are only updated while they still look like the untouched examples.
EXAMPLES = {
    "starter": {
        "description": "EXAMPLE plan (edit the price): everything the free allowance covers, 1,000,000 events and 5,000 recordings (videos). First month $20, then $30.",
        "price_usd": Decimal("30"), "price_pkr": Decimal("8400"), "intro_price_usd": Decimal("20"), "intro_price_pkr": Decimal("5600"),
        "monthly_event_limit": 1_000_000, "monthly_recording_limit": 5_000, "max_websites": 1, "max_team_members": 2,
        "features": {"sessions": True, "people": True, "live_events": True, "recordings": True, "weekly_reports": False, "shopify": False, "team_members": False},
    },
    "growth": {
        "description": "EXAMPLE plan (edit the price): 1,500,000 events and 10,000 recordings (videos), plus the weekly report and team members. Priced as base $30 + provider cost + 30% commission.",
        "price_usd": Decimal("95"), "price_pkr": Decimal("26600"), "intro_price_usd": None, "intro_price_pkr": None,
        "monthly_event_limit": 1_500_000, "monthly_recording_limit": 10_000, "max_websites": 3, "max_team_members": 5,
        "features": {"sessions": True, "people": True, "live_events": True, "recordings": True, "weekly_reports": True, "shopify": False, "team_members": True},
    },
    "pro": {
        "description": "EXAMPLE plan (edit the price): 3,000,000 events and 25,000 recordings (videos), everything switched on including Shopify sales. Priced as base $30 + provider cost + 30% commission.",
        "price_usd": Decimal("251"), "price_pkr": Decimal("70300"), "intro_price_usd": None, "intro_price_pkr": None,
        "monthly_event_limit": 3_000_000, "monthly_recording_limit": 25_000, "max_websites": 10, "max_team_members": 10,
        "features": {"sessions": True, "people": True, "live_events": True, "recordings": True, "weekly_reports": True, "shopify": True, "team_members": True},
    },
}


def upgrade() -> None:
    op.add_column("plans", sa.Column("monthly_recording_limit", sa.BigInteger(), nullable=True), schema=_schema())
    op.add_column("plans", sa.Column("intro_price_pkr", Money, nullable=True), schema=_schema())
    op.add_column("plans", sa.Column("intro_price_usd", Money, nullable=True), schema=_schema())
    op.add_column("plans", sa.Column("intro_months", sa.Integer(), server_default="1", nullable=False), schema=_schema())

    plans = sa.table(
        "plans",
        sa.column("slug", sa.String()), sa.column("description", sa.Text()),
        sa.column("price_pkr", Money), sa.column("price_usd", Money), sa.column("intro_price_pkr", Money), sa.column("intro_price_usd", Money),
        sa.column("monthly_event_limit", sa.BigInteger()), sa.column("monthly_recording_limit", sa.BigInteger()),
        sa.column("max_websites", sa.Integer()), sa.column("max_team_members", sa.Integer()), sa.column("features", Json),
        schema=_schema(),
    )
    for slug, values in EXAMPLES.items():
        op.execute(plans.update().where(sa.and_(plans.c.slug == slug, plans.c.description.like("EXAMPLE plan%"))).values(**values))


def downgrade() -> None:
    for column in ("intro_months", "intro_price_usd", "intro_price_pkr", "monthly_recording_limit"):
        op.drop_column("plans", column, schema=_schema())
