"""New clients are billed in US dollars by default, clients with no invoices yet are switched to dollars, and the example Starter plan includes team members.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# The example Starter plan (see 0010) with "Team members" switched on too.
STARTER_FEATURES = {"sessions": True, "people": True, "live_events": True, "recordings": True, "weekly_reports": False, "shopify": False, "team_members": True}


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        # (SQLite databases are throwaway test databases that the models create themselves, with the new default.)
        op.alter_column("clients", "currency", server_default="USD", schema=SCHEMA)

    # A client's currency can't change once it has invoices, and a special price (an amount in that currency) must not
    # silently turn from rupees into dollars: so only clients with NEITHER are switched.
    clients = sa.table("clients", sa.column("id", sa.Uuid()), sa.column("currency", sa.String()), schema=_schema())
    invoices = sa.table("invoices", sa.column("client_id", sa.Uuid()), schema=_schema())
    subscriptions = sa.table("subscriptions", sa.column("client_id", sa.Uuid()), sa.column("price_override", sa.Numeric(12, 2)), schema=_schema())
    op.execute(
        clients.update()
        .where(
            sa.and_(
                clients.c.currency == "PKR",
                ~sa.exists().where(invoices.c.client_id == clients.c.id),
                ~sa.exists().where(sa.and_(subscriptions.c.client_id == clients.c.id, subscriptions.c.price_override.is_not(None))),
            )
        )
        .values(currency="USD")
    )

    plans = sa.table("plans", sa.column("slug", sa.String()), sa.column("description", sa.Text()), sa.column("features", Json), schema=_schema())
    op.execute(
        plans.update()
        .where(sa.and_(plans.c.slug == "starter", plans.c.description.like("EXAMPLE plan%")))  # only while it still looks like the untouched example
        .values(features=STARTER_FEATURES)
    )


def downgrade() -> None:
    # (The clients that were switched to dollars stay in dollars: the migration can't know which ones they were.)
    if op.get_context().dialect.name == "postgresql":
        op.alter_column("clients", "currency", server_default="PKR", schema=SCHEMA)
