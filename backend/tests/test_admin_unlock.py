"""The admin panel asks for the password once more ("unlock"): being logged in as an admin is not enough."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.deps import ADMIN_COOKIE, ADMIN_LOCKED_MESSAGE
from app.models import AuditLog
from app.security import ADMIN_TOKEN, create_token

from .conftest import PASSWORD, make_user
from .test_admin import ADMIN_ENDPOINTS, fill

UNLOCK = "/api/auth/admin-unlock"
LOCK = "/api/auth/admin-lock"
SOME_ADMIN_PAGE = "/api/admin/clients"


def locked_admin(api, email="admin@agency.test"):
    """An admin who has logged in but NOT confirmed the password for the admin panel."""
    return api(email, unlock=False)


def audit_actions(db):
    db.expire_all()
    return [a for a in db.scalars(select(AuditLog.action).order_by(AuditLog.created_at))]


# ------------------------------------------------------------------ the lock


def test_a_logged_in_admin_cannot_use_the_admin_panel_until_the_password_is_confirmed(api, world):
    admin = locked_admin(api)
    locked = admin.get(SOME_ADMIN_PAGE)
    assert locked.status_code == 423 and locked.json()["detail"] == ADMIN_LOCKED_MESSAGE
    me = admin.get("/api/auth/me").json()
    assert me["user"]["is_admin"] is True and me["admin_unlocked"] is False
    assert len(me["websites"]) == 2  # the normal dashboards are still open: only the admin PANEL asks for the password

    opened = admin.post(UNLOCK, json={"password": PASSWORD})
    assert opened.status_code == 200 and opened.json()["admin_unlocked"] is True
    assert admin.get(SOME_ADMIN_PAGE).status_code == 200
    assert admin.get("/api/auth/me").json()["admin_unlocked"] is True


@pytest.mark.parametrize("method, path", ADMIN_ENDPOINTS)
def test_every_admin_endpoint_asks_for_the_password_first(method, path, api, world, fake_posthog):
    """No admin tool can be reached around the screen: the lock is in the backend, on every /api/admin route."""
    response = locked_admin(api).request(method, fill(path), json={})
    assert response.status_code == 423, f"{method} {path} -> {response.status_code}"
    assert fake_posthog.calls == []


def test_the_cookie_is_httponly_strict_and_only_sent_to_the_api(api, world):
    admin = locked_admin(api)
    cookie = admin.post(UNLOCK, json={"password": PASSWORD}).headers.get_list("set-cookie")
    [mine] = [c for c in cookie if c.startswith(f"{ADMIN_COOKIE}=")]
    assert "httponly" in mine.lower() and "samesite=strict" in mine.lower() and "path=/api" in mine.lower()
    assert f"max-age={settings.admin_unlock_minutes * 60}" in mine.lower()


# ------------------------------------------------------------------ the password


def test_a_wrong_password_does_not_open_the_panel_does_not_log_out_and_is_logged(api, world, db):
    admin = locked_admin(api)
    wrong = admin.post(UNLOCK, json={"password": "not-the-password"})
    assert wrong.status_code == 403 and wrong.json()["detail"] == "Wrong password."  # (not 401: the admin must stay logged in)
    assert admin.get("/api/auth/me").status_code == 200
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423
    assert audit_actions(db).count("auth.admin_unlock_failed") == 1


def test_guessing_the_admin_password_is_limited(api, world, db):
    admin = locked_admin(api)
    for _ in range(5):
        assert admin.post(UNLOCK, json={"password": "guess"}).status_code == 403
    blocked = admin.post(UNLOCK, json={"password": PASSWORD})  # even the right one waits now
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers and "Too many wrong passwords" in blocked.json()["detail"]
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423
    assert audit_actions(db).count("auth.admin_unlock_failed") == 5


def test_a_right_password_clears_the_wrong_ones(api, world):
    admin = locked_admin(api)
    for _ in range(4):
        admin.post(UNLOCK, json={"password": "guess"})
    assert admin.post(UNLOCK, json={"password": PASSWORD}).status_code == 200
    for _ in range(4):  # the count started again from zero
        assert admin.post(UNLOCK, json={"password": "guess"}).status_code == 403


def test_only_admins_can_unlock_and_only_when_logged_in(api, world):
    assert api().post(UNLOCK, json={"password": PASSWORD}).status_code == 401
    alice = api("alice@a.test")
    assert alice.post(UNLOCK, json={"password": PASSWORD}).status_code == 403
    assert alice.get("/api/auth/me").json()["admin_unlocked"] is False
    assert ADMIN_COOKIE not in alice.cookies


# ------------------------------------------------------------------ whose unlock it is, and for how long


def test_an_unlock_cookie_is_useless_to_anybody_else(api, world, db):
    make_user(db, "second@agency.test", admin=True)
    db.commit()
    first = api("admin@agency.test")  # unlocked
    stolen = first.cookies.get(ADMIN_COOKIE)
    assert stolen

    second = locked_admin(api, "second@agency.test")
    second.cookies.set(ADMIN_COOKIE, stolen)
    assert second.get(SOME_ADMIN_PAGE).status_code == 423  # made for the first admin only

    alice = api("alice@a.test")
    alice.cookies.set(ADMIN_COOKIE, stolen)
    assert alice.get(SOME_ADMIN_PAGE).status_code == 403  # and a client never becomes an admin because of it
    assert alice.get("/api/auth/me").json()["admin_unlocked"] is False


def test_an_expired_or_forged_unlock_does_not_count(api, world):
    admin = locked_admin(api)
    admin.cookies.set(ADMIN_COOKIE, create_token(world.admin.id, world.admin.token_version, ADMIN_TOKEN, timedelta(seconds=-5)))
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423  # ran out
    admin.cookies.set(ADMIN_COOKIE, "not-a-token")
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423
    admin.cookies.set(ADMIN_COOKIE, create_token(world.admin.id, world.admin.token_version + 1, ADMIN_TOKEN, timedelta(minutes=5)))
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423  # from before a password change: the version no longer matches
    # a login cookie can't be used as an unlock cookie (every token has its own type)
    admin.cookies.set(ADMIN_COOKIE, admin.cookies.get("portal_session"))
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423


def test_the_panel_stays_open_while_it_is_used_and_closes_after_a_quiet_while(api, world):
    admin = locked_admin(api)

    def renewed(remaining: timedelta) -> bool:
        admin.cookies.set(ADMIN_COOKIE, create_token(world.admin.id, world.admin.token_version, ADMIN_TOKEN, remaining))
        response = admin.get(SOME_ADMIN_PAGE)
        assert response.status_code == 200
        return any(c.startswith(f"{ADMIN_COOKIE}=") for c in response.headers.get_list("set-cookie"))

    assert renewed(timedelta(minutes=1)) is True  # nearly out of time and still in use: a fresh full period
    assert renewed(timedelta(minutes=settings.admin_unlock_minutes - 1)) is False  # plenty left: nothing to do


# ------------------------------------------------------------------ closing it


def test_locking_the_panel_again_asks_for_the_password_next_time(api, world, db):
    admin = api("admin@agency.test")
    assert admin.get(SOME_ADMIN_PAGE).status_code == 200
    closed = admin.post(LOCK)
    assert closed.status_code == 200 and closed.json()["admin_unlocked"] is False
    assert admin.get(SOME_ADMIN_PAGE).status_code == 423
    assert admin.get("/api/auth/me").status_code == 200  # still logged in
    assert "auth.admin_locked" in audit_actions(db)


def test_logging_out_removes_the_unlock_too(api, world):
    admin = api("admin@agency.test")
    cookies = admin.post("/api/auth/logout").headers.get_list("set-cookie")
    assert any(c.startswith(f"{ADMIN_COOKIE}=") and "max-age=0" in c.lower() for c in cookies)


def test_opening_the_panel_is_written_to_the_audit_log(api, world, db):
    locked_admin(api).post(UNLOCK, json={"password": PASSWORD})
    assert "auth.admin_unlocked" in audit_actions(db)


# ------------------------------------------------------------------ the rest of the product is not affected


def test_viewing_as_a_client_still_works_and_clients_never_see_a_prompt(api, world):
    admin = api("admin@agency.test")
    assert admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)}).status_code == 200
    assert admin.get("/api/auth/me").json()["view_as"]["client_name"] == "Client A"
    assert admin.get(SOME_ADMIN_PAGE).status_code == 403  # (exit the client view first, as before)
    assert admin.post("/api/auth/view-as/end").json()["admin_unlocked"] is True  # and the panel was never closed meanwhile
    bob = api("bob@b.test")
    assert bob.get("/api/auth/me").json()["admin_unlocked"] is False
