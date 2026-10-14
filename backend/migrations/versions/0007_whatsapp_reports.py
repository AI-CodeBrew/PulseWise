"""Phase 10: WhatsApp weekly reports (a client's number + opt-in, and when a report was sent).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    op.add_column("clients", sa.Column("whatsapp_number", sa.String(length=20), nullable=True), schema=_schema())
    op.add_column("clients", sa.Column("whatsapp_reports_enabled", sa.Boolean(), server_default=sa.false(), nullable=False), schema=_schema())
    op.add_column("reports", sa.Column("whatsapp_sent_at", sa.DateTime(timezone=True), nullable=True), schema=_schema())


def downgrade() -> None:
    op.drop_column("reports", "whatsapp_sent_at", schema=_schema())
    op.drop_column("clients", "whatsapp_reports_enabled", schema=_schema())
    op.drop_column("clients", "whatsapp_number", schema=_schema())
