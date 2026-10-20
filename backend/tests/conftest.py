"""
Shared test setup.

The tests NEVER touch Supabase or PostHog:
  - the database is a throwaway SQLite file, recreated for every test;
  - every PostHog call is replaced by a fake that records what was asked.
"""

import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

# Settings are read when the app is imported, so these must be set FIRST.
# (Real environment variables win over backend/.env, so .env can't override them.)
_TMP_DIR = Path(tempfile.mkdtemp(prefix="portal-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-0123456789-abcdefghijklmnop"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["FRONTEND_URL"] = "http://localhost:3000"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["COOKIE_SECURE"] = "false"
os.environ["SMTP_HOST"] = ""
os.environ["SCHEDULER_ENABLED"] = "false"  # tests run jobs by hand
os.environ["SAVED_ANSWERS"] = "false"  # answers only in memory (tests/test_saved_answers.py switches the database copy on)
os.environ["ANTHROPIC_API_KEY"] = ""  # no AI in tests (tests that need it inject a fake client)

from collections.abc import Iterator  # noqa: E402
from contextlib import ExitStack  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.cache import cache  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Client, ClientMember, User, Website  # noqa: E402
from app.posthog_client import AnalyticsError, PostHogClient  # noqa: E402
from app.rate_limit import all_limiters  # noqa: E402
from app.security import encrypt_secret, hash_password  # noqa: E402

assert settings.database_url.startswith("sqlite"), "Tests must never run against the real database!"

PASSWORD = "correct-horse-battery-staple"


# ------------------------------------------------------------------ fresh state per test


@pytest.fixture(autouse=True)
def fresh_state() -> Iterator[None]:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    cache.clear()
    for limiter in all_limiters():
        limiter.clear()
    yield


# ------------------------------------------------------------------ the network is OFF in tests


class FakeNetwork:
    """The only "internet" the tests have. By default ANY request fails the test: the tests must never
    reach the real PostHog (or anything else). A test that wants to exercise the real HTTP code of
    PostHogClient sets `FakeNetwork.handler` to a function (request -> httpx.Response)."""

    handler = None
    paths: list[str] = []


def _network(request):
    if FakeNetwork.handler is None:
        raise AssertionError(f"A test tried to use the real network: {request.method} {request.url}")
    FakeNetwork.paths.append(request.url.path)
    return FakeNetwork.handler(request)


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app import posthog_client

    FakeNetwork.handler = None
    FakeNetwork.paths = []

    async def _startup() -> None:  # what the app does at startup, but with the pretend network
        posthog_client._http = httpx.AsyncClient(transport=httpx.MockTransport(_network))

    monkeypatch.setattr(posthog_client, "startup", _startup)


# ------------------------------------------------------------------ fake PostHog


class FakePostHog:
    """Stands in for PostHog. Records every call: which project, which key, which path."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        # Scripted answers to HogQL queries, by the query's `name` (e.g. "health:24h").
        self.query_answers: dict[str, dict] = {}
        # Project info returned for GET /api/projects/<id>/ (None = "no permission", like a key without that scope).
        self.project_info: dict | None = {"api_token": "phc_fake_project_token", "name": "Fake project", "timezone": "UTC"}

    def answer(self, name: str, columns: list[str], rows: list[list]) -> None:
        """Make HogQL queries called `name` return these rows."""
        self.query_answers[name] = {"columns": columns, "results": rows}

    async def request(self, ph: PostHogClient, method: str, path: str, **kwargs) -> Any:
        self.calls.append(
            {
                "website_id": ph.website.website_id,
                "project_id": ph.website.project_id,
                "api_key": ph.website.api_key,
                "method": method,
                "path": path,
                "query_name": (kwargs.get("json") or {}).get("name"),
            }
        )
        if ph.website.api_key == "phx_bad_key":  # simulate PostHog refusing the key
            raise AnalyticsError(502, "not authorized", upstream_status=401, upstream_detail="Invalid API key")
        if method == "POST" and path.endswith("/query/"):
            name = (kwargs.get("json") or {}).get("name")
            if name in self.query_answers:
                return self.query_answers[name]
        if method == "GET" and path.rstrip("/").endswith(f"/projects/{ph.website.project_id}"):
            if self.project_info is None:
                raise AnalyticsError(502, "forbidden", upstream_status=403, upstream_detail="missing scope project:read")
            return self.project_info
        if path.endswith("/snapshots"):
            if kwargs.get("raw"):  # the data blocks, as JSON Lines
                return json.dumps(["w1", {"type": 4, "timestamp": 1000, "data": {"href": "http://x.test/", "width": 800, "height": 600}}]) + "\n"
            return {"sources": [{"source": "blob_v2", "blob_key": "0", "start_timestamp": "2026-10-10T10:00:00Z", "end_timestamp": "2026-10-10T10:05:00Z"}]}
        if "session_recordings/" in path and not path.endswith("session_recordings/"):  # one recording's details
            return {"id": path.rstrip("/").split("/")[-1], "start_time": "2026-10-10T10:00:00Z", "end_time": "2026-10-10T10:05:00Z",
                    "recording_duration": 300, "distinct_id": "visitor-1"}
        if "session_recordings" in path:
            return {
                "results": [
                    {
                        "id": "rec-1",
                        "distinct_id": "visitor-1",
                        "start_time": "2026-10-10T10:00:00Z",
                        "end_time": "2026-10-10T10:05:00Z",
                        "recording_duration": 300,
                        "person": {"distinct_ids": ["visitor-1"], "properties": {}},
                    }
                ],
                "has_next": False,
            }
        return {"columns": [], "results": []}  # an empty HogQL result

    def projects_called(self) -> set[int]:
        return {call["project_id"] for call in self.calls}


@pytest.fixture(autouse=True)
def fake_posthog(monkeypatch: pytest.MonkeyPatch) -> FakePostHog:
    fake = FakePostHog()

    async def _fake_request(self: PostHogClient, method: str, path: str, raw: bool = False, **kwargs) -> Any:
        return await fake.request(self, method, path, raw=raw, **kwargs)

    monkeypatch.setattr(PostHogClient, "_request", _fake_request)
    return fake


# ------------------------------------------------------------------ data helpers


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


def make_user(db, email: str, *, admin: bool = False, active: bool = True, password: str = PASSWORD) -> User:
    user = User(email=email, name=email.split("@")[0], password_hash=hash_password(password), is_admin=admin, is_active=active)
    db.add(user)
    db.flush()
    return user


def make_client(db, name: str, status: str = "active") -> Client:
    # (new clients are billed in US dollars; most billing tests were written with rupee amounts, so the test clients say so)
    client = Client(name=name, status=status, currency="PKR")
    db.add(client)
    db.flush()
    return client


def make_website(db, client: Client, project_id: int, api_key: str, *, active: bool = True) -> Website:
    website = Website(
        client_id=client.id,
        name=f"{client.name} site",
        domain=f"{client.name.lower().replace(' ', '-')}.example.com",
        posthog_host="https://us.posthog.com",
        posthog_project_id=project_id,
        posthog_api_key_encrypted=encrypt_secret(api_key),
        is_active=active,
    )
    db.add(website)
    db.flush()
    return website


def add_member(db, client: Client, user: User, role: str = "viewer") -> None:
    db.add(ClientMember(client_id=client.id, user_id=user.id, role=role))
    db.flush()


@dataclass
class World:
    """Two separate clients (A and B), each with one website and one owner, plus an admin."""

    client_a: Client
    client_b: Client
    site_a: Website
    site_b: Website
    alice: User  # owner at client A
    bob: User  # owner at client B
    vera: User  # viewer at client A
    admin: User


@pytest.fixture
def world(db) -> World:
    client_a = make_client(db, "Client A")
    client_b = make_client(db, "Client B")
    site_a = make_website(db, client_a, project_id=7350981, api_key="phx_secret_key_of_A")
    site_b = make_website(db, client_b, project_id=8462092, api_key="phx_secret_key_of_B")
    alice = make_user(db, "alice@a.test")
    bob = make_user(db, "bob@b.test")
    vera = make_user(db, "vera@a.test")
    admin = make_user(db, "admin@agency.test", admin=True)
    add_member(db, client_a, alice, "owner")
    add_member(db, client_b, bob, "owner")
    add_member(db, client_a, vera, "viewer")
    db.commit()
    return World(client_a, client_b, site_a, site_b, alice, bob, vera, admin)


# ------------------------------------------------------------------ API clients


@pytest.fixture
def api() -> Iterator:
    """Factory for HTTP clients. api() = not logged in, api("alice@a.test") = logged in.

    Each client has its own cookie jar, like separate browsers.
    """
    with ExitStack() as stack:

        def _make(email: str | None = None, password: str = PASSWORD, *, unlock: bool = True) -> TestClient:
            client = stack.enter_context(TestClient(app))
            if email:
                response = client.post("/api/auth/login", json={"email": email, "password": password})
                assert response.status_code == 200, response.text
                if unlock and response.json()["user"]["is_admin"]:
                    # The admin panel asks for the password once more. Most tests are about what the panel DOES, so admins
                    # come already unlocked here; the tests about the lock itself pass unlock=False.
                    opened = client.post("/api/auth/admin-unlock", json={"password": password})
                    assert opened.status_code == 200, opened.text
            return client

        yield _make
