"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Reminder: new tables go in the "portal" schema (schema=SCHEMA), and on Postgres
should get row-level security enabled, like in 0001_initial.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}

SCHEMA = "portal"


def _schema() -> str | None:
    """"portal" on PostgreSQL. SQLite (only used by the automated tests) has no schemas, so use
    `schema=_schema()` in op.add_column / op.drop_column / op.alter_column / op.create_index.
    (op.create_table is translated automatically, but ALTER TABLE statements are not.)"""
    return None if op.get_context().dialect.name == "sqlite" else SCHEMA


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
