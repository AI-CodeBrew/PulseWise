"""Phase 8: reports, plus client settings (timezone, report language, weekly switch, logo).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    now = sa.func.now()
    postgres = op.get_context().dialect.name == "postgresql"

    op.add_column("clients", sa.Column("timezone", sa.String(length=64), server_default="Asia/Karachi", nullable=False), schema=_schema())
    op.add_column("clients", sa.Column("report_language", sa.String(length=10), server_default="en", nullable=False), schema=_schema())
    op.add_column("clients", sa.Column("weekly_report_enabled", sa.Boolean(), server_default=sa.true(), nullable=False), schema=_schema())
    op.add_column("clients", sa.Column("logo_data", sa.LargeBinary(), nullable=True), schema=_schema())
    op.add_column("clients", sa.Column("logo_mime", sa.String(length=40), nullable=True), schema=_schema())
    if postgres:
        op.create_check_constraint(op.f("ck_clients_report_language"), "clients", "report_language IN ('en', 'roman_ur', 'ur')", schema=SCHEMA)

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("language", sa.String(length=10), server_default="en", nullable=False),
        sa.Column("data", Json, nullable=False),
        sa.Column("summary", Json, nullable=False),
        sa.Column("summary_source", sa.String(length=10), server_default="rules", nullable=False),
        sa.Column("generated_by", sa.String(length=20), server_default="schedule", nullable=False),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emailed_to", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.CheckConstraint("summary_source IN ('ai', 'rules')", name="summary_source"),
        sa.CheckConstraint("language IN ('en', 'roman_ur', 'ur')", name="language"),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_reports_website_id_websites", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], [f"{SCHEMA}.clients.id"], name="fk_reports_client_id_clients", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_reports"),
        schema=SCHEMA,
    )
    op.create_index("ix_reports_website_id", "reports", ["website_id"], schema=_schema())
    op.create_index("ix_reports_client_id", "reports", ["client_id"], schema=_schema())
    op.create_index("uq_reports_website_period", "reports", ["website_id", "period_start", "period_end"], unique=True, schema=_schema())

    if postgres:
        op.execute(f'ALTER TABLE "{SCHEMA}"."reports" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("reports", schema=SCHEMA)
    if op.get_context().dialect.name == "postgresql":
        op.drop_constraint("ck_clients_report_language", "clients", schema=SCHEMA, type_="check")
    for column in ("logo_mime", "logo_data", "weekly_report_enabled", "report_language", "timezone"):
        op.drop_column("clients", column, schema=_schema())
