"""Initial tables: users, clients, client_members, websites, audit_log.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "portal"
TABLES = ("users", "clients", "client_members", "websites", "audit_log")


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    if is_postgres:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        schema=SCHEMA,
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="status"),
        sa.PrimaryKeyConstraint("id", name="pk_clients"),
        schema=SCHEMA,
    )

    op.create_table(
        "client_members",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'viewer')", name="role"),
        sa.ForeignKeyConstraint(
            ["client_id"], [f"{SCHEMA}.clients.id"], name="fk_client_members_client_id_clients", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA}.users.id"], name="fk_client_members_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("client_id", "user_id", name="pk_client_members"),
        schema=SCHEMA,
    )
    op.create_index("ix_client_members_user_id", "client_members", ["user_id"], schema=SCHEMA)

    op.create_table(
        "websites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("posthog_host", sa.String(length=255), nullable=False),
        sa.Column("posthog_project_id", sa.BigInteger(), nullable=False),
        sa.Column("posthog_org_id", sa.String(length=64), nullable=True),
        sa.Column("posthog_api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"], [f"{SCHEMA}.clients.id"], name="fk_websites_client_id_clients", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_websites"),
        schema=SCHEMA,
    )
    op.create_index("ix_websites_client_id", "websites", ["client_id"], schema=SCHEMA)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], [f"{SCHEMA}.users.id"], name="fk_audit_log_actor_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        schema=SCHEMA,
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], schema=SCHEMA)

    if is_postgres:
        # Defense in depth for Supabase: row-level security with NO policies blocks the
        # anon/authenticated roles completely, even if this schema were ever exposed to
        # Supabase's REST API. Our backend connects as the tables' owner, which RLS
        # doesn't restrict.
        for table in TABLES:
            op.execute(f'ALTER TABLE "{SCHEMA}"."{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log", schema=SCHEMA)
    op.drop_table("audit_log", schema=SCHEMA)
    op.drop_index("ix_websites_client_id", table_name="websites", schema=SCHEMA)
    op.drop_table("websites", schema=SCHEMA)
    op.drop_index("ix_client_members_user_id", table_name="client_members", schema=SCHEMA)
    op.drop_table("client_members", schema=SCHEMA)
    op.drop_table("clients", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
