"""Saved analytics answers, so dashboard pages open at once (see app/saved_answers.py).

The SQL is written with IF NOT EXISTS, so running it by hand in Supabase first (docs/ROADMAP.md has it) does no harm.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"

POSTGRES_SQL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.analytics_cache (
    key varchar(64) NOT NULL,
    website_id uuid NOT NULL,
    name varchar(100) NOT NULL DEFAULT '',
    payload jsonb NOT NULL,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_analytics_cache PRIMARY KEY (key),
    CONSTRAINT fk_analytics_cache_website_id_websites FOREIGN KEY (website_id) REFERENCES {SCHEMA}.websites (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_analytics_cache_website_id ON {SCHEMA}.analytics_cache (website_id);
ALTER TABLE {SCHEMA}.analytics_cache ENABLE ROW LEVEL SECURITY;
"""


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(POSTGRES_SQL)  # (RLS: nothing but the backend may read it through Supabase's public API)
        return
    op.create_table(
        "analytics_cache",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("website_id", sa.Uuid(), sa.ForeignKey(f"{SCHEMA}.websites.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("analytics_cache", schema=SCHEMA)
