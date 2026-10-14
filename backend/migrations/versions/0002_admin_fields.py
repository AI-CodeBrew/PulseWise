"""Admin panel fields: clients.notes / suspended_reason, websites.posthog_project_token.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    op.add_column("clients", sa.Column("notes", sa.Text(), nullable=True), schema=_schema())
    op.add_column("clients", sa.Column("suspended_reason", sa.String(length=32), nullable=True), schema=_schema())
    op.add_column("websites", sa.Column("posthog_project_token", sa.String(length=100), nullable=True), schema=_schema())


def downgrade() -> None:
    op.drop_column("websites", "posthog_project_token", schema=_schema())
    op.drop_column("clients", "suspended_reason", schema=_schema())
    op.drop_column("clients", "notes", schema=_schema())
