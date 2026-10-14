"""The management CLI (python -m app.cli)."""

import io
import sys

import pytest
from sqlalchemy import select

from app import cli
from app.models import Client, ClientMember, User, Website
from app.security import decrypt_secret, verify_password

from .conftest import PASSWORD


class FakeStdin:
    """Stands in for sys.stdin with raw bytes (the CLI reads bytes, to handle a BOM)."""

    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


def run(monkeypatch, *argv: str, stdin: bytes | None = None) -> int:
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", FakeStdin(stdin))
    return cli.main(list(argv))


@pytest.mark.parametrize(
    "piped",
    [
        b"a-Good-Password-1\r\n",  # cmd / Linux style
        b"\xef\xbb\xbfa-Good-Password-1\r\n",  # Windows PowerShell 5.1 adds a BOM
        b"a-Good-Password-1",  # no newline
    ],
)
def test_piped_passwords_work_with_and_without_a_bom(db, monkeypatch, piped):
    code = run(monkeypatch, "create-admin", "--email", "boss@x.test", "--password-stdin", stdin=piped)
    assert code == 0
    user = db.scalar(select(User).where(User.email == "boss@x.test"))
    assert user.is_admin and verify_password(user.password_hash, "a-Good-Password-1")


def test_too_short_password_is_refused(db, monkeypatch, capsys):
    assert run(monkeypatch, "create-admin", "--email", "boss@x.test", "--password-stdin", stdin=b"short\n") == 1
    assert "at least" in capsys.readouterr().err
    assert db.scalar(select(User).where(User.email == "boss@x.test")) is None


def test_client_website_and_user_setup_end_to_end(db, api, monkeypatch):
    assert run(monkeypatch, "create-client", "--name", "Ali's Shop", "--contact-email", "ali@shop.test") == 0
    monkeypatch.setenv("POSTHOG_HOST", "https://us.posthog.com")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "424242")
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_cli_test_key")
    assert run(monkeypatch, "add-website", "--client", "ali's shop", "--name", "alishop.test", "--from-env", "--skip-check") == 0
    assert run(monkeypatch, "add-user", "--email", "Ali@Shop.test", "--client", "Ali's Shop", "--role", "owner",
               "--password-stdin", stdin=PASSWORD.encode() + b"\n") == 0

    website = db.scalar(select(Website))
    assert website.posthog_project_id == 424242
    assert "phx_cli_test_key" not in website.posthog_api_key_encrypted  # stored encrypted
    assert decrypt_secret(website.posthog_api_key_encrypted) == "phx_cli_test_key"
    member = db.scalar(select(ClientMember))
    assert member.role == "owner"

    # ...and that user can really log in and see exactly that website.
    me = api("ali@shop.test").get("/api/auth/me").json()
    assert [w["id"] for w in me["websites"]] == [str(website.id)]


def test_suspending_a_client_blocks_its_users(db, api, monkeypatch, world):
    assert run(monkeypatch, "set-client-status", "--client", "Client A", "--status", "suspended") == 0
    assert api("alice@a.test").get(f"/api/websites/{world.site_a.id}/overview").status_code == 403
    assert run(monkeypatch, "set-client-status", "--client", "Client A", "--status", "active") == 0
    assert api("alice@a.test").get(f"/api/websites/{world.site_a.id}/overview").status_code == 200


def test_set_password_logs_the_user_out_everywhere(db, api, monkeypatch, world):
    session = api("alice@a.test")
    assert run(monkeypatch, "set-password", "--email", "alice@a.test", "--password-stdin", stdin=b"Another-Pass-9876\n") == 0
    assert session.get("/api/auth/me").status_code == 401
    api("alice@a.test", password="Another-Pass-9876")


def test_unknown_client_gives_a_friendly_error(db, monkeypatch, capsys):
    assert run(monkeypatch, "set-client-status", "--client", "Nobody Inc", "--status", "suspended") == 1
    assert "No client" in capsys.readouterr().err


def test_bootstrap_only_works_on_an_empty_database(db, monkeypatch, capsys, world):
    assert run(monkeypatch, "bootstrap", "--email", "me@x.test", "--name", "Me", "--password-stdin", stdin=b"a-Good-Password-1\n") == 1
    assert "already has users" in capsys.readouterr().err
    assert db.scalar(select(Client).where(Client.name == "My Company")) is None
