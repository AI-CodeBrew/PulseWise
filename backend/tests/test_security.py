"""Secrets at rest, responses without secrets, and migrations that match the models."""

import json
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, text

from app.db import Base, make_engine
from app.security import decrypt_secret

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_posthog_keys_are_encrypted_in_the_database(db, world):
    stored = db.execute(text("SELECT posthog_api_key_encrypted FROM websites")).scalars().all()
    assert len(stored) == 2
    for value in stored:
        assert "phx_" not in value  # never stored in plain text
    assert {decrypt_secret(v) for v in stored} == {"phx_secret_key_of_A", "phx_secret_key_of_B"}


def test_passwords_are_hashed_with_argon2(db, world):
    hashes = db.execute(text("SELECT password_hash FROM users")).scalars().all()
    assert hashes and all(h.startswith("$argon2") for h in hashes)


def test_no_response_ever_contains_secrets(api, world):
    """/me and the data endpoints must not leak keys, PostHog project ids or hosts to clients."""
    alice = api("alice@a.test")
    site = f"/api/websites/{world.site_a.id}"
    bodies = [alice.get("/api/auth/me").text]
    for path in ("/overview", "/trends", "/sources", "/recordings", "/events/live"):
        bodies.append(alice.get(site + path).text)
    for body in bodies:
        assert "phx_" not in body
        assert "posthog" not in body.lower()
        assert "7350981" not in body  # the PostHog project id


def test_me_has_only_safe_website_fields(api, world):
    website = api("alice@a.test").get("/api/auth/me").json()["websites"][0]
    assert set(website) == {"id", "name", "domain", "client_id", "client_name", "client_status", "client_has_logo", "role", "features"}
    assert website["role"] == "owner"


def test_audit_log_records_logins_without_secrets(api, db, world):
    api("alice@a.test")
    api().post("/api/auth/login", json={"email": "alice@a.test", "password": "a-wrong-password"})
    rows = db.execute(text("SELECT action, details FROM audit_log ORDER BY created_at")).all()
    actions = [row[0] for row in rows]
    assert "auth.login" in actions and "auth.login_failed" in actions
    assert "a-wrong-password" not in json.dumps([str(row[1]) for row in rows])


def test_migrations_build_exactly_the_tables_in_models(tmp_path):
    """`alembic upgrade head` on an empty database must produce what app/models.py describes."""
    url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")

    # SQLite has no schemas, so compare against a schema-less copy of the models.
    expected = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(expected, schema=None)

    engine = make_engine(url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), expected)
    engine.dispose()
    assert differences == []
