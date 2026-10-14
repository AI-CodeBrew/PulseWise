"""
Database connection (SQLAlchemy).

All our tables live in their own Postgres schema, "portal". On Supabase that matters:
Supabase's public REST API (the one the anon key works with) only exposes the
`public` schema, so tables in "portal" can't be reached from outside. Only this
backend, connecting with the database password, can read them.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

SCHEMA = "portal"

# Predictable constraint names, so database migrations can refer to them later.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Parent class of every table (see app/models.py)."""

    metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)


def normalize_database_url(url: str) -> str:
    """Accept the URL exactly as Supabase shows it ("postgresql://...") and tell
    SQLAlchemy to use the psycopg (v3) driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_database_url(url)

    if url.startswith("sqlite"):
        # Only the automated tests use SQLite. SQLite has no schemas, so "portal.x"
        # is translated to plain "x" there.
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            execution_options={"schema_translate_map": {SCHEMA: None}},
        )

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # SQLite ignores FKs unless asked
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        return engine

    return create_engine(
        url,
        pool_pre_ping=True,  # replace connections the server closed (poolers do that)
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
        # Supabase's poolers don't support server-side prepared statements in every
        # mode; turning them off makes every connection type work.
        connect_args={"prepare_threshold": None},
    )


@lru_cache
def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set in backend/.env")
    return make_engine(settings.database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request, closed afterwards."""
    with get_sessionmaker()() as session:
        yield session
