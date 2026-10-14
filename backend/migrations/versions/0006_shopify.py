"""Phase 9: Shopify store connections and synced orders.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
TABLES = ("shop_connections", "shop_orders", "shop_order_items")


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    now = sa.func.now()
    postgres = op.get_context().dialect.name == "postgresql"

    op.create_table(
        "shop_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("shop_domain", sa.String(length=255), nullable=False),
        sa.Column("auth_mode", sa.String(length=24), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("auth_mode IN ('token', 'client_credentials')", name="auth_mode"),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_shop_connections_website_id_websites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_shop_connections"),
        sa.UniqueConstraint("website_id", name="uq_shop_connections_website_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "shop_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("shopify_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("financial_status", sa.String(length=40), nullable=True),
        sa.Column("fulfillment_status", sa.String(length=40), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("refunded", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("is_test", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_shop_orders_website_id_websites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_shop_orders"),
        schema=SCHEMA,
    )
    op.create_index("uq_shop_orders_website_shopify", "shop_orders", ["website_id", "shopify_id"], unique=True, schema=_schema())
    op.create_index("ix_shop_orders_website_created", "shop_orders", ["website_id", "created_at"], schema=_schema())

    op.create_table(
        "shop_order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=True),
        sa.Column("product_id", sa.String(length=64), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], [f"{SCHEMA}.shop_orders.id"], name="fk_shop_order_items_order_id_shop_orders", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_shop_order_items_website_id_websites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_shop_order_items"),
        schema=SCHEMA,
    )
    op.create_index("ix_shop_order_items_order_id", "shop_order_items", ["order_id"], schema=_schema())
    op.create_index("ix_shop_order_items_website_id", "shop_order_items", ["website_id"], schema=_schema())

    if postgres:  # nobody but the backend (which connects as the table owner) may read these through Supabase's public API
        for table in TABLES:
            op.execute(f'ALTER TABLE "{SCHEMA}"."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
