"""Login, logout, sessions and passwords."""

from datetime import timedelta

from app import routers
from app.deps import SESSION_COOKIE
from app.security import RESET_TOKEN, create_token

from .conftest import PASSWORD, make_user


def test_login_sets_a_safe_cookie_and_returns_me(api, world):
    client = api()
    response = client.post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD})
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"]
    assert cookie_header.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie_header  # JavaScript can't read it
    assert "samesite=lax" in cookie_header.lower()  # not sent by other websites' requests
    assert response.json()["user"]["email"] == "alice@a.test"


def test_email_is_case_insensitive(api, world):
    response = api().post("/api/auth/login", json={"email": "  Alice@A.TEST ", "password": PASSWORD})
    assert response.status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(api, world):
    client = api()
    wrong_password = client.post("/api/auth/login", json={"email": "alice@a.test", "password": "nope-nope"})
    unknown_email = client.post("/api/auth/login", json={"email": "nobody@x.test", "password": "nope-nope"})
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()  # no hint about which emails exist


def test_inactive_user_cannot_log_in(api, db):
    make_user(db, "gone@a.test", active=False)
    db.commit()
    response = api().post("/api/auth/login", json={"email": "gone@a.test", "password": PASSWORD})
    assert response.status_code == 401


def test_me_requires_login(api):
    assert api().get("/api/auth/me").status_code == 401


def test_logout_ends_the_session(api, world):
    client = api("alice@a.test")
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_too_many_wrong_passwords_are_blocked(api, world):
    client = api()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "alice@a.test", "password": "wrong"}).status_code == 401
    # Now even the RIGHT password is refused for a while.
    blocked = client.post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_tampered_or_garbage_cookie_is_rejected(api, world):
    token = api("alice@a.test").cookies.get(SESSION_COOKIE)
    for bad_value in (token[:-3] + "abc", "not-a-token"):  # broken signature, garbage
        client = api()  # a fresh "browser" holding only the bad cookie
        client.cookies.set(SESSION_COOKIE, bad_value)
        assert client.get("/api/auth/me").status_code == 401


def test_change_password_logs_out_other_sessions_but_not_this_one(api, world):
    laptop = api("alice@a.test")
    phone = api("alice@a.test")
    response = laptop.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 200
    assert laptop.get("/api/auth/me").status_code == 200  # still logged in here
    assert phone.get("/api/auth/me").status_code == 401  # logged out everywhere else
    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD}).status_code == 401
    api("alice@a.test", password="a-brand-new-password")  # new password works


def test_change_password_needs_the_current_password(api, world):
    client = api("alice@a.test")
    response = client.post(
        "/api/auth/change-password", json={"current_password": "wrong", "new_password": "a-brand-new-password"}
    )
    assert response.status_code == 400


def test_new_password_must_be_long_enough(api, world):
    client = api("alice@a.test")
    response = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"})
    assert response.status_code == 400
    assert "at least" in response.json()["detail"]


def test_forgot_and_reset_password_flow(api, world, monkeypatch):
    sent = []
    monkeypatch.setattr(routers.auth, "send_email", lambda to, subject, body: sent.append((to, body)))
    old_session = api("alice@a.test")

    response = api().post("/api/auth/forgot-password", json={"email": "alice@a.test"})
    assert response.status_code == 200
    assert len(sent) == 1 and sent[0][0] == "alice@a.test"
    token = sent[0][1].split("token=")[1].split()[0]

    reset = api().post("/api/auth/reset-password", json={"token": token, "new_password": "fresh-password-123"})
    assert reset.status_code == 200
    api("alice@a.test", password="fresh-password-123")  # new password works
    assert old_session.get("/api/auth/me").status_code == 401  # old sessions are gone
    # The link works only once.
    again = api().post("/api/auth/reset-password", json={"token": token, "new_password": "another-password-1"})
    assert again.status_code == 400


def test_forgot_password_gives_the_same_answer_for_unknown_emails(api, world, monkeypatch):
    sent = []
    monkeypatch.setattr(routers.auth, "send_email", lambda *args: sent.append(args))
    known = api().post("/api/auth/forgot-password", json={"email": "alice@a.test"})
    unknown = api().post("/api/auth/forgot-password", json={"email": "nobody@x.test"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(sent) == 1  # but only a real account gets an email


def test_a_reset_token_is_not_a_login_cookie(api, world):
    reset_token = create_token(world.alice.id, world.alice.token_version, RESET_TOKEN, timedelta(minutes=5))
    client = api()
    client.cookies.set(SESSION_COOKIE, reset_token)
    assert client.get("/api/auth/me").status_code == 401


def test_a_login_cookie_is_not_a_reset_token(api, world):
    session_token = api("alice@a.test").cookies.get(SESSION_COOKIE)
    response = api().post("/api/auth/reset-password", json={"token": session_token, "new_password": "hijacked-pass-1"})
    assert response.status_code == 400


def test_requests_from_other_websites_are_blocked(api, world):
    response = api().post(
        "/api/auth/login",
        json={"email": "alice@a.test", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    ok = api().post(
        "/api/auth/login",
        json={"email": "alice@a.test", "password": PASSWORD},
        headers={"Origin": "http://localhost:3000"},
    )
    assert ok.status_code == 200
