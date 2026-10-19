"""My dashboard: which Overview tiles each person chose, per website.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "dashboard_prefs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("website_id", sa.Uuid(), nullable=False),
        sa.Column("tiles", Json, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], name="fk_dashboard_prefs_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["website_id"], [f"{SCHEMA}.websites.id"], name="fk_dashboard_prefs_website_id_websites", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "website_id", name="pk_dashboard_prefs"),
        schema=SCHEMA,
    )
    if op.get_context().dialect.name == "postgresql":  # nothing but the backend may read it through Supabase's public API
        op.execute(f'ALTER TABLE "{SCHEMA}"."dashboard_prefs" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("dashboard_prefs", schema=SCHEMA)
