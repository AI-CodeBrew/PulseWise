"""
Alembic's entry point: connects to the database and runs the migrations.

All our tables (and Alembic's own `alembic_version` bookkeeping table) live in the
"portal" schema. Supabase has many other schemas (auth, storage, ...): we tell
Alembic to ignore them, so autogenerate can never try to change or drop them.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

import app.models  # noqa: F401  (loads the table definitions onto Base.metadata)
from app.config import settings
from app.db import SCHEMA, Base, make_engine, normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):  # noqa: ARG001
    """Only look inside our own schema."""
    if type_ == "schema":
        return name == SCHEMA
    return True


def database_url() -> str:
    # Tests pass their own (SQLite) URL; normally it comes from backend/.env.
    url = config.attributes.get("database_url") or settings.database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    return url


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(
        url=normalize_database_url(database_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        # The schema must exist before the version table (portal.alembic_version) is created.
        context.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(database_url())
    is_sqlite = engine.dialect.name == "sqlite"  # only in the automated tests
    try:
        with engine.connect() as connection:
            if not is_sqlite:
                # The schema must exist before Alembic creates its version table in it.
                connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
                connection.commit()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table_schema=None if is_sqlite else SCHEMA,
                include_schemas=not is_sqlite,
                include_name=include_name,
                compare_type=True,
                render_as_batch=is_sqlite,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
