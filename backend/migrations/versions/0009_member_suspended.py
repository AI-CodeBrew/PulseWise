"""Team: a member can be suspended (locked out of one client) without being removed.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas."""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    op.add_column("client_members", sa.Column("suspended", sa.Boolean(), server_default=sa.false(), nullable=False), schema=_schema())


def downgrade() -> None:
    op.drop_column("client_members", "suspended", schema=_schema())
