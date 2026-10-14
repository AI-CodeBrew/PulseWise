"""Phase 6: usage_daily, alerts, job_runs, app_settings.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
TABLES = ("usage_daily", "alerts", "job_runs", "app_settings")
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    now = sa.func.now()

    op.create_table(
        "usage_daily",
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("events", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("pageviews", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("recordings", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_usage_daily_website_id_websites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("website_id", "day", name="pk_usage_daily"),
        schema=SCHEMA,
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("severity", sa.String(length=10), server_default="warning", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="open", nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("details", Json, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="status"),
        sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity"),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_alerts_website_id_websites", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], [f"{SCHEMA}.clients.id"], name="fk_alerts_client_id_clients", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        schema=SCHEMA,
    )
    op.create_index("ix_alerts_website_id", "alerts", ["website_id"], schema=_schema())
    op.create_index("ix_alerts_client_id", "alerts", ["client_id"], schema=_schema())
    op.create_index("ix_alerts_status", "alerts", ["status"], schema=_schema())
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"], schema=_schema())
    # At most one OPEN alert per dedupe_key.
    op.create_index(
        "uq_alerts_open_dedupe", "alerts", ["dedupe_key"], unique=True, schema=_schema(),
        postgresql_where=sa.text("status = 'open'"), sqlite_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job", sa.String(length=60), nullable=False),
        sa.Column("triggered_by", sa.String(length=40), server_default="schedule", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="running", nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", Json, nullable=True),
        sa.CheckConstraint("status IN ('running', 'ok', 'error', 'skipped')", name="status"),
        sa.PrimaryKeyConstraint("id", name="pk_job_runs"),
        schema=SCHEMA,
    )
    op.create_index("ix_job_runs_job_started_at", "job_runs", ["job", "started_at"], schema=_schema())

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", Json, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_app_settings"),
        schema=SCHEMA,
    )

    if op.get_context().dialect.name == "postgresql":
        for table in TABLES:  # same protection as the other tables (see 0001)
            op.execute(f'ALTER TABLE "{SCHEMA}"."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("app_settings", schema=SCHEMA)
    op.drop_index("ix_job_runs_job_started_at", table_name="job_runs", schema=_schema())
    op.drop_table("job_runs", schema=SCHEMA)
    op.drop_table("alerts", schema=SCHEMA)  # its indexes go with it
    op.drop_table("usage_daily", schema=SCHEMA)
