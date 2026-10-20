"""The admin API: access control, clients, websites, members, view-as-client, audit log."""

import collections
import json
import uuid

import pytest
from sqlalchemy import select, text

from app import accounts
from app.main import app
from app.models import AuditLog, Client, ClientMember, User, Website
from app.security import decrypt_secret

from .conftest import PASSWORD, make_client, make_user

SOME_UUID = "01a125cf-d633-793d-bbf9-c8e737c3d94d"

ADMIN_ENDPOINTS = sorted(
    (method.upper(), path)
    for path, operations in app.openapi()["paths"].items()
    if path.startswith("/api/admin")
    for method in operations
)


def fill(path: str) -> str:
    return path.format_map(collections.defaultdict(lambda: SOME_UUID))  # any {placeholder} -> a harmless id


# ------------------------------------------------------------------ who may use the admin API


def test_there_are_admin_endpoints_to_check():
    assert len(ADMIN_ENDPOINTS) >= 18, ADMIN_ENDPOINTS


@pytest.mark.parametrize("method, path", ADMIN_ENDPOINTS)
def test_not_logged_in_gets_401_on_every_admin_endpoint(method, path, api, world):
    assert api().request(method, fill(path), json={}).status_code == 401


@pytest.mark.parametrize("method, path", ADMIN_ENDPOINTS)
@pytest.mark.parametrize("who", ["alice@a.test", "vera@a.test"])  # a client owner and a client viewer
def test_clients_get_403_on_every_admin_endpoint(method, path, who, api, world, fake_posthog):
    response = api(who).request(method, fill(path), json={})
    assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
    assert fake_posthog.calls == []


# ------------------------------------------------------------------ clients


def test_create_edit_suspend_and_delete_a_client(api, db):
    make_user(db, "boss@agency.test", admin=True)
    db.commit()
    admin = api("boss@agency.test")

    created = admin.post("/api/admin/clients", json={"name": "  Ali's Shop ", "contact_email": "ALI@shop.test", "phone": "0300"})
    assert created.status_code == 201
    client = created.json()
    assert client["name"] == "Ali's Shop" and client["contact_email"] == "ali@shop.test" and client["status"] == "active"

    assert any(c["id"] == client["id"] for c in admin.get("/api/admin/clients").json()["results"])
    edited = admin.patch(f"/api/admin/clients/{client['id']}", json={"notes": "pays in cash", "status": "suspended"}).json()
    assert edited["notes"] == "pays in cash" and edited["status"] == "suspended"
    assert admin.patch(f"/api/admin/clients/{client['id']}", json={"contact_email": "not-an-email"}).status_code == 400

    # Deleting needs the exact name.
    assert admin.request("DELETE", f"/api/admin/clients/{client['id']}", json={"confirm": "wrong"}).status_code == 400
    assert admin.request("DELETE", f"/api/admin/clients/{client['id']}", json={"confirm": "Ali's Shop"}).status_code == 200
    assert admin.get(f"/api/admin/clients/{client['id']}").status_code == 404


def test_suspending_a_client_blocks_its_users(api, world):
    admin = api("admin@agency.test")
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200
    admin.patch(f"/api/admin/clients/{world.client_a.id}", json={"status": "suspended"})
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 403
    admin.patch(f"/api/admin/clients/{world.client_a.id}", json={"status": "active"})
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200


def test_deleting_a_client_removes_its_websites_and_memberships(api, db, world):
    admin = api("admin@agency.test")
    client_a_id, site_a_id, site_b_id, alice_id = world.client_a.id, world.site_a.id, world.site_b.id, world.alice.id
    assert admin.request("DELETE", f"/api/admin/clients/{client_a_id}", json={"confirm": "Client A"}).status_code == 200
    db.expire_all()
    assert db.get(Website, site_a_id) is None
    assert db.scalar(select(ClientMember).where(ClientMember.client_id == client_a_id)) is None
    assert db.get(User, alice_id) is not None  # people are kept, only their access goes
    assert db.get(Website, site_b_id) is not None  # other clients untouched


# ------------------------------------------------------------------ websites


GOOD_WEBSITE = {"name": "alishop.pk", "domain": "alishop.pk", "posthog_host": "https://us.posthog.com",
                "posthog_project_id": 555001, "posthog_api_key": "phx_new_secret_key_123"}


def test_add_a_website_stores_the_key_encrypted_and_never_returns_it(api, db, world, fake_posthog):
    admin = api("admin@agency.test")
    response = admin.post(f"/api/admin/clients/{world.client_a.id}/websites", json=GOOD_WEBSITE)
    assert response.status_code == 201, response.text
    body = response.json()
    assert "phx_new_secret_key_123" not in response.text and "posthog_api_key" not in body
    assert body["has_api_key"] is True
    assert body["posthog_project_token"] == "phc_fake_project_token"  # found automatically

    stored = db.scalar(select(Website).where(Website.id == uuid.UUID(body["id"])))
    assert "phx_" not in stored.posthog_api_key_encrypted
    assert decrypt_secret(stored.posthog_api_key_encrypted) == "phx_new_secret_key_123"
    assert fake_posthog.projects_called() == {555001}  # the key was tested before saving

    # The audit entry says WHAT happened but never contains the key.
    entries = db.execute(text("SELECT details FROM audit_log WHERE action = 'admin.website_created'")).scalars().all()
    assert len(entries) == 1 and "phx_" not in str(entries[0])


def test_a_website_is_not_saved_when_posthog_rejects_the_key(api, db, world):
    admin = api("admin@agency.test")
    response = admin.post(f"/api/admin/clients/{world.client_a.id}/websites", json={**GOOD_WEBSITE, "posthog_api_key": "phx_bad_key"})
    assert response.status_code == 400
    assert "Could not connect to PostHog" in response.json()["detail"]
    assert "Invalid API key" in response.json()["detail"]  # the real reason, for the admin
    assert db.scalar(select(Website).where(Website.posthog_project_id == 555001)) is None


@pytest.mark.parametrize("host", ["https://evil.example", "http://us.posthog.com", "https://us.posthog.com.evil.example",
                                  "https://169.254.169.254", "https://localhost:8000"])
def test_only_allowed_posthog_hosts_are_accepted(host, api, world, fake_posthog):
    admin = api("admin@agency.test")
    response = admin.post(f"/api/admin/clients/{world.client_a.id}/websites", json={**GOOD_WEBSITE, "posthog_host": host})
    assert response.status_code == 400
    assert "not an allowed PostHog address" in response.json()["detail"]
    assert fake_posthog.calls == []  # the key was never sent anywhere


def test_rotating_the_key_tests_it_and_replaces_it(api, db, world, fake_posthog):
    admin = api("admin@agency.test")
    bad = admin.patch(f"/api/admin/websites/{world.site_a.id}", json={"posthog_api_key": "phx_bad_key"})
    assert bad.status_code == 400
    db.expire_all()
    assert decrypt_secret(db.get(Website, world.site_a.id).posthog_api_key_encrypted) == "phx_secret_key_of_A"  # unchanged

    good = admin.patch(f"/api/admin/websites/{world.site_a.id}", json={"posthog_api_key": "phx_rotated_key_456"})
    assert good.status_code == 200 and "phx_rotated" not in good.text
    db.expire_all()
    assert decrypt_secret(db.get(Website, world.site_a.id).posthog_api_key_encrypted) == "phx_rotated_key_456"
    # ...and the dashboard now uses the new key.
    fake_posthog.calls.clear()
    api("alice@a.test").get(f"/api/websites/{world.site_a.id}/overview")
    assert {c["api_key"] for c in fake_posthog.calls} == {"phx_rotated_key_456"}


def test_deactivating_a_website_hides_it_from_the_client(api, world):
    admin = api("admin@agency.test")
    alice = api("alice@a.test")
    admin.patch(f"/api/admin/websites/{world.site_a.id}", json={"is_active": False})
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 404
    assert alice.get("/api/auth/me").json()["websites"] == []


def test_delete_a_website_needs_its_name(api, db, world):
    admin = api("admin@agency.test")
    assert admin.request("DELETE", f"/api/admin/websites/{world.site_a.id}", json={"confirm": "nope"}).status_code == 400
    assert admin.request("DELETE", f"/api/admin/websites/{world.site_a.id}", json={"confirm": world.site_a.name}).status_code == 200
    assert api("alice@a.test").get("/api/auth/me").json()["websites"] == []


def test_website_detail_never_includes_the_key(api, world):
    body = api("admin@agency.test").get(f"/api/admin/websites/{world.site_a.id}").text
    assert "phx_" not in body and "encrypted" not in body.lower()


# ------------------------------------------------------------------ onboarding: snippet and health


def test_snippet_contains_the_token_and_the_ingestion_host(api, db, world):
    world.site_a.posthog_project_token = "phc_ABC123"
    db.merge(world.site_a)
    db.commit()
    body = api("admin@agency.test").get(f"/api/admin/websites/{world.site_a.id}/snippet").json()
    assert body["needs_token"] is False
    assert "posthog.init('phc_ABC123'" in body["snippet"]
    assert "api_host: 'https://us.i.posthog.com'" in body["snippet"]
    assert body["snippet"].startswith("<script>") and body["snippet"].endswith("</script>")
    assert "phx_" not in json.dumps(body)  # the PRIVATE key never appears in the public snippet


def test_snippet_finds_the_token_by_itself_or_asks_for_it(api, db, world, fake_posthog):
    admin = api("admin@agency.test")
    found = admin.get(f"/api/admin/websites/{world.site_a.id}/snippet").json()
    assert found["project_token"] == "phc_fake_project_token" and not found["needs_token"]
    db.expire_all()
    assert db.get(Website, world.site_a.id).posthog_project_token == "phc_fake_project_token"  # saved for next time

    fake_posthog.project_info = None  # the key has no permission to read project info
    missing = admin.get(f"/api/admin/websites/{world.site_b.id}/snippet").json()
    assert missing["needs_token"] is True and missing["snippet"] is None


def test_health_check_green_amber_and_red(api, world, fake_posthog):
    from datetime import datetime, timedelta, timezone

    admin = api("admin@agency.test")
    url = f"/api/admin/websites/{world.site_a.id}/check"
    now = datetime.now(timezone.utc)

    fake_posthog.answer("health:24h", ["events", "pageviews", "last_event_at"], [[120, 40, now.isoformat()]])
    green = admin.get(url).json()
    assert green["connection"]["ok"] and green["health"]["status"] == "green" and green["health"]["events_24h"] == 120

    fake_posthog.answer("health:24h", ["events", "pageviews", "last_event_at"], [[0, 0, None]])
    fake_posthog.answer("health:last", ["last_event_at"], [[(now - timedelta(hours=30)).isoformat()]])
    from app.cache import cache
    cache.clear()
    assert admin.get(url).json()["health"]["status"] == "amber"

    fake_posthog.answer("health:last", ["last_event_at"], [[(now - timedelta(hours=60)).isoformat()]])
    cache.clear()
    red = admin.get(url).json()["health"]
    assert red["status"] == "red" and red["hours_since_last_event"] >= 59

    fake_posthog.answer("health:last", ["last_event_at"], [[None]])
    cache.clear()
    assert admin.get(url).json()["health"]["status"] == "red"  # never any data


def test_health_check_reports_a_broken_connection_to_the_admin(api, db, world):
    from app.security import encrypt_secret

    world.site_a.posthog_api_key_encrypted = encrypt_secret("phx_bad_key")
    db.merge(world.site_a)
    db.commit()
    body = api("admin@agency.test").get(f"/api/admin/websites/{world.site_a.id}/check").json()
    assert body["connection"]["ok"] is False and "Invalid API key" in body["connection"]["message"]


# ------------------------------------------------------------------ members and users


def test_a_new_person_cannot_be_added_without_a_password(api, db, world):
    # (there is no invitation-link way in any more: every new login gets the password the admin chose)
    response = api("admin@agency.test").post(f"/api/admin/clients/{world.client_a.id}/members", json={"email": "New.Person@A.test", "name": "New", "role": "viewer"})
    assert response.status_code == 400 and "needs a password" in response.json()["detail"]
    assert db.scalar(select(User).where(User.email == "new.person@a.test")) is None  # nobody was created


def test_adding_an_existing_person_just_gives_them_access(api, db, world):
    admin = api("admin@agency.test")
    response = admin.post(f"/api/admin/clients/{world.client_b.id}/members", json={"email": "alice@a.test", "role": "viewer"}).json()
    assert response["new_user"] is False  # (somebody who already has an account needs no password)
    sites = {w["id"] for w in api("alice@a.test").get("/api/auth/me").json()["websites"]}
    assert sites == {str(world.site_a.id), str(world.site_b.id)}  # one person, two clients
    duplicate = admin.post(f"/api/admin/clients/{world.client_b.id}/members", json={"email": "alice@a.test", "role": "owner"})
    assert duplicate.status_code == 409


def test_adding_a_new_person_with_a_password_makes_the_login_at_once(api, db, world, monkeypatch):
    sent = []
    monkeypatch.setattr(accounts, "send_invite_email", lambda *a, **k: sent.append(a))
    response = api("admin@agency.test").post(
        f"/api/admin/clients/{world.client_a.id}/members",
        json={"email": "Ali@Gmail.test", "name": "Ali", "role": "viewer", "password": "Chosen-By-Admin-1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["new_user"] is True and "invite_link" not in body
    assert body["email"] == "ali@gmail.test" and body["login_url"].endswith("/login")
    assert "Chosen-By-Admin-1" not in response.text
    assert sent == []  # nothing is emailed: the admin hands the login over
    ali = api("ali@gmail.test", password="Chosen-By-Admin-1")  # can log in at once, and sees the client's website
    assert [w["id"] for w in ali.get("/api/auth/me").json()["websites"]] == [str(world.site_a.id)]
    assert "Chosen-By-Admin-1" not in json.dumps([e.details for e in db.scalars(select(AuditLog))], default=str)  # never logged


def test_a_password_typed_for_an_existing_person_is_never_used(api, world):
    # (otherwise adding somebody to a second client would change the password of their first login)
    response = api("admin@agency.test").post(
        f"/api/admin/clients/{world.client_b.id}/members", json={"email": "alice@a.test", "role": "viewer", "password": "Chosen-By-Admin-1"}
    )
    assert response.status_code == 201 and response.json()["new_user"] is False
    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD}).status_code == 200  # her own password is unchanged
    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": "Chosen-By-Admin-1"}).status_code == 401


def test_a_weak_password_adds_nobody(api, db, world):
    response = api("admin@agency.test").post(f"/api/admin/clients/{world.client_a.id}/members", json={"email": "ali@gmail.test", "password": "short"})
    assert response.status_code == 400 and "at least" in response.json()["detail"]
    assert db.scalar(select(User).where(User.email == "ali@gmail.test")) is None


def test_change_a_role_and_remove_a_member(api, world):
    admin = api("admin@agency.test")
    assert admin.patch(f"/api/admin/clients/{world.client_a.id}/members/{world.vera.id}", json={"role": "owner"}).json()["role"] == "owner"
    assert admin.patch(f"/api/admin/clients/{world.client_a.id}/members/{world.vera.id}", json={"role": "boss"}).status_code == 422
    vera = api("vera@a.test")
    assert vera.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200
    assert admin.delete(f"/api/admin/clients/{world.client_a.id}/members/{world.vera.id}").status_code == 200
    assert vera.get(f"/api/websites/{world.site_a.id}/overview").status_code == 404
    assert admin.delete(f"/api/admin/clients/{world.client_a.id}/members/{world.vera.id}").status_code == 404


def test_deactivating_a_user_logs_them_out_immediately(api, world):
    admin = api("admin@agency.test")
    bob = api("bob@b.test")
    assert bob.get("/api/auth/me").status_code == 200
    assert admin.patch(f"/api/admin/users/{world.bob.id}", json={"is_active": False}).status_code == 200
    assert bob.get("/api/auth/me").status_code == 401
    assert api().post("/api/auth/login", json={"email": "bob@b.test", "password": PASSWORD}).status_code == 401


def test_an_admin_cannot_deactivate_themselves(api, world):
    admin = api("admin@agency.test")
    assert admin.patch(f"/api/admin/users/{world.admin.id}", json={"is_active": False}).status_code == 400


def test_user_list_shows_memberships(api, world):
    users = {u["email"]: u for u in api("admin@agency.test").get("/api/admin/users").json()["results"]}
    assert users["alice@a.test"]["clients"] == [{"id": str(world.client_a.id), "name": "Client A", "role": "owner"}]
    assert users["admin@agency.test"]["is_admin"] is True
    assert "password" not in json.dumps(users)


def test_fresh_invite_link_for_an_existing_user(api, world):
    body = api("admin@agency.test").post(f"/api/admin/users/{world.alice.id}/invite-link").json()
    assert body["email"] == "alice@a.test" and "reset-password?token=" in body["invite_link"]


# ------------------------------------------------------------------ the admin edits a user's login (email / password)

NEW_PASSWORD = "A-Brand-New-Pass-1"


def login_url(user) -> str:
    return f"/api/admin/users/{user.id}/login"


def test_admin_sets_a_users_password_without_the_old_one(api, world):
    alice_before = api("alice@a.test")  # logged in before the change
    assert alice_before.get("/api/auth/me").status_code == 200

    response = api("admin@agency.test").patch(login_url(world.alice), json={"password": NEW_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@a.test" and body["password_set"] is True and body["email_changed"] is False
    assert body["login_url"].endswith("/login")
    assert NEW_PASSWORD not in response.text  # the answer never repeats the password

    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD}).status_code == 401  # the old one is dead
    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": NEW_PASSWORD}).status_code == 200
    assert alice_before.get("/api/auth/me").status_code == 401  # logged out everywhere


def test_admin_changes_a_users_email_and_the_password_stays(api, world):
    alice_before = api("alice@a.test")
    response = api("admin@agency.test").patch(login_url(world.alice), json={"email": "  Alice.New@A.test "})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice.new@a.test" and body["email_changed"] is True and body["password_set"] is False

    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD}).status_code == 401  # the old address is gone
    assert api().post("/api/auth/login", json={"email": "alice.new@a.test", "password": PASSWORD}).status_code == 200  # same password, new address
    assert alice_before.get("/api/auth/me").status_code == 401  # logged out everywhere


def test_email_and_password_can_be_changed_together(api, world):
    response = api("admin@agency.test").patch(login_url(world.alice), json={"email": "alice.new@a.test", "password": NEW_PASSWORD})
    assert response.status_code == 200 and response.json()["email_changed"] is True and response.json()["password_set"] is True
    assert api().post("/api/auth/login", json={"email": "alice.new@a.test", "password": NEW_PASSWORD}).status_code == 200


def test_a_login_change_kills_invitation_links_sent_earlier(api, world):
    admin = api("admin@agency.test")
    link = admin.post(f"/api/admin/users/{world.alice.id}/invite-link").json()["invite_link"]
    token = link.split("token=")[1].split("&")[0]
    assert admin.patch(login_url(world.alice), json={"password": NEW_PASSWORD}).status_code == 200
    # the old link would let whoever holds it choose a password for her account: it must be dead now
    assert api().post("/api/auth/reset-password", json={"token": token, "new_password": "Someone-Elses-Pass-1"}).status_code == 400


def test_login_changes_have_rules(api, world):
    url = login_url(world.alice)
    assert api().patch(url, json={"password": NEW_PASSWORD}).status_code == 401  # not logged in
    assert api("bob@b.test").patch(url, json={"password": NEW_PASSWORD}).status_code == 403  # the owner of another account is not an admin

    admin = api("admin@agency.test")
    assert admin.patch(login_url(world.admin), json={"password": NEW_PASSWORD}).status_code == 400  # never for an admin login (not even their own)
    assert admin.patch(f"/api/admin/users/{uuid.uuid4()}/login", json={"password": NEW_PASSWORD}).status_code == 404
    weak = admin.patch(url, json={"password": "short"})
    assert weak.status_code == 400 and "at least" in weak.json()["detail"]
    assert admin.patch(url, json={"email": "not-an-email"}).status_code == 400
    taken = admin.patch(url, json={"email": "BOB@b.test"})  # somebody else's address, in any capitals
    assert taken.status_code == 409 and "already belongs" in taken.json()["detail"]
    assert admin.patch(url, json={}).status_code == 400  # nothing to change
    assert admin.patch(url, json={"email": "alice@a.test"}).status_code == 400  # the same address again is nothing to change
    assert admin.patch(url, json={"email": "alice.new@a.test", "password": "short"}).status_code == 400  # all or nothing: a bad password stops a good email too

    # none of the refusals changed anything
    assert api().post("/api/auth/login", json={"email": "alice@a.test", "password": PASSWORD}).status_code == 200
    assert api().post("/api/auth/login", json={"email": "alice.new@a.test", "password": PASSWORD}).status_code == 401


def test_changing_the_email_names_the_clients_whose_billing_contact_is_still_the_old_one(api, world, db):
    world.client_a.contact_email = "Alice@A.test"  # (how onboarding fills it in: the person's own address)
    db.commit()
    body = api("admin@agency.test").patch(login_url(world.alice), json={"email": "alice.new@a.test"}).json()
    assert body["billing_contact_of"] == [{"id": str(world.client_a.id), "name": "Client A"}]
    db.expire_all()
    assert world.client_a.contact_email == "Alice@A.test"  # told, not changed: where invoices go is the admin's decision


def test_login_changes_are_in_the_audit_log_without_the_password(api, world, db):
    api("admin@agency.test").patch(login_url(world.alice), json={"email": "alice.new@a.test", "password": NEW_PASSWORD})
    entries = {e.action: e for e in db.scalars(select(AuditLog).where(AuditLog.action.in_(["admin.user_email_changed", "admin.user_password_set"])))}
    assert set(entries) == {"admin.user_email_changed", "admin.user_password_set"}
    assert entries["admin.user_email_changed"].details == {"from": "alice@a.test", "to": "alice.new@a.test"}
    assert all(e.actor_user_id == world.admin.id and e.target_id == str(world.alice.id) for e in entries.values())
    assert NEW_PASSWORD not in json.dumps([e.details for e in db.scalars(select(AuditLog))], default=str)


# ------------------------------------------------------------------ view as client


def test_view_as_client_shows_exactly_what_the_client_sees_and_is_read_only(api, world, fake_posthog):
    admin = api("admin@agency.test")
    assert len(admin.get("/api/auth/me").json()["websites"]) == 2  # normally an admin sees everything

    started = admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    assert started.status_code == 200 and started.json()["website_id"] == str(world.site_a.id)

    me = admin.get("/api/auth/me").json()
    assert me["view_as"] == {"client_id": str(world.client_a.id), "client_name": "Client A"}
    assert [w["id"] for w in me["websites"]] == [str(world.site_a.id)] and me["websites"][0]["role"] == "owner"

    assert admin.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200
    assert admin.get(f"/api/websites/{world.site_b.id}/overview").status_code == 404  # like the client: no access to B

    # Read-only, and no admin tools while acting as a client.
    assert admin.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "Sneaky-Change-1"}).status_code == 403
    assert admin.get("/api/admin/clients").status_code == 403
    assert admin.post("/api/admin/view-as", json={"client_id": str(world.client_b.id)}).status_code == 403

    ended = admin.post("/api/auth/view-as/end")
    assert ended.status_code == 200 and ended.json()["view_as"] is None and len(ended.json()["websites"]) == 2
    assert admin.get("/api/admin/clients").status_code == 200  # admin again


def test_view_as_a_suspended_client_shows_the_suspension(api, db, world):
    world.client_a.status = "suspended"
    db.merge(world.client_a)
    db.commit()
    admin = api("admin@agency.test")
    assert admin.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200  # normal admin: allowed
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    assert admin.get(f"/api/websites/{world.site_a.id}/overview").status_code == 403  # exactly what the client sees


def test_view_as_is_recorded_in_the_audit_log(api, db, world):
    admin = api("admin@agency.test")
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    admin.post("/api/auth/view-as/end")
    actions = [a for a in db.scalars(select(AuditLog.action).where(AuditLog.action.like("admin.view_as%")))]
    assert sorted(actions) == ["admin.view_as_ended", "admin.view_as_started"]


def test_logout_also_ends_the_client_view(api, world):
    admin = api("admin@agency.test")
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    admin.post("/api/auth/logout")
    assert admin.cookies.get("portal_view_as") is None


def test_view_as_cookie_of_another_admin_is_ignored(api, db, world):
    other = make_user(db, "second-admin@agency.test", admin=True)
    db.commit()
    first = api("admin@agency.test")
    first.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    stolen = first.cookies.get("portal_view_as")
    second = api("second-admin@agency.test")
    second.cookies.set("portal_view_as", stolen)
    assert second.get("/api/auth/me").json()["view_as"] is None  # the cookie was made for the first admin
    assert other.is_admin


def test_a_client_cannot_use_a_view_as_cookie(api, world):
    admin = api("admin@agency.test")
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_b.id)})
    forged = admin.cookies.get("portal_view_as")
    alice = api("alice@a.test")
    alice.cookies.set("portal_view_as", forged)
    me = alice.get("/api/auth/me").json()
    assert me["view_as"] is None and [w["id"] for w in me["websites"]] == [str(world.site_a.id)]


# ------------------------------------------------------------------ audit log and overview


def test_every_admin_change_is_in_the_audit_log(api, world):
    admin = api("admin@agency.test")
    admin.post("/api/admin/clients", json={"name": "Audited"})
    admin.patch(f"/api/admin/clients/{world.client_a.id}", json={"phone": "123"})
    entries = admin.get("/api/admin/audit", params={"action": "admin."}).json()["results"]
    actions = [e["action"] for e in entries]
    assert "admin.client_created" in actions and "admin.client_updated" in actions
    assert all(e["actor"] == "admin@agency.test" for e in entries)


def test_audit_log_paging_and_filter(api, db, world):
    admin = api("admin@agency.test")
    for i in range(5):
        admin.post("/api/admin/clients", json={"name": f"Client {i}"})
    first = admin.get("/api/admin/audit", params={"limit": 3, "action": "admin.client_created"}).json()
    assert len(first["results"]) == 3 and first["next_cursor"]
    second = admin.get("/api/admin/audit", params={"limit": 3, "action": "admin.client_created", "cursor": first["next_cursor"]}).json()
    assert len(second["results"]) == 2 and second["next_cursor"] is None
    assert not {e["id"] for e in first["results"]} & {e["id"] for e in second["results"]}
    assert admin.get("/api/admin/audit", params={"action": "Robert'); DROP TABLE users;--"}).status_code == 422


def test_overview_counts(api, world):
    body = api("admin@agency.test").get("/api/admin/overview").json()
    assert body["clients"] == {"total": 2, "active": 2, "suspended": 0}
    assert body["websites"] == 2 and body["users"] == 3 and body["admins"] == 1


def test_clients_search_is_safe(api, world):
    admin = api("admin@agency.test")
    assert [c["name"] for c in admin.get("/api/admin/clients", params={"q": "client a"}).json()["results"]] == ["Client A"]
    assert admin.get("/api/admin/clients", params={"q": "%"}).json()["results"] == []  # '%' is not a wildcard here
    assert make_client  # (imported helper used elsewhere)


# ------------------------------------------------------------------ onboarding a customer in one step


ONBOARD = {"email": "Ali@Shop.test", "name": "Ali", "password": "Admin-Chosen-Pw-1", "website_name": "alishop.pk",
           "posthog_host": "https://us.posthog.com", "posthog_project_id": 777001, "posthog_api_key": "phx_onboard_key_123"}


def test_onboarding_creates_a_login_that_sees_only_its_own_website(api, db, world, fake_posthog):
    response = api("admin@agency.test").post("/api/admin/users", json=ONBOARD)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "ali@shop.test" and body["login_url"].endswith("/login")
    assert "Admin-Chosen-Pw-1" not in response.text and "phx_onboard_key_123" not in response.text

    # The user logs in with the password the admin chose and sees their own website, and only that.
    me = api("ali@shop.test", password="Admin-Chosen-Pw-1").get("/api/auth/me").json()
    assert [w["id"] for w in me["websites"]] == [body["website_id"]]

    stored = db.get(Website, uuid.UUID(body["website_id"]))
    assert decrypt_secret(stored.posthog_api_key_encrypted) == "phx_onboard_key_123"
    assert stored.posthog_project_token == "phc_fake_project_token"
    assert 777001 in fake_posthog.projects_called()  # the key was tested first

    entries = db.execute(text("SELECT details FROM audit_log WHERE action = 'admin.customer_onboarded'")).scalars().all()
    assert len(entries) == 1 and "phx_" not in str(entries[0]) and "Admin-Chosen" not in str(entries[0])


def test_onboarding_saves_nothing_when_posthog_rejects_the_key(api, db, world):
    response = api("admin@agency.test").post("/api/admin/users", json={**ONBOARD, "posthog_api_key": "phx_bad_key"})
    assert response.status_code == 400 and "Could not connect to PostHog" in response.json()["detail"]
    assert db.scalar(select(User).where(User.email == "ali@shop.test")) is None
    assert db.scalar(select(Client).where(Client.name == "ali@shop.test")) is None


def test_onboarding_refuses_weak_passwords_and_existing_emails(api, db, world):
    admin = api("admin@agency.test")
    assert admin.post("/api/admin/users", json={**ONBOARD, "password": "short"}).status_code == 400
    assert admin.post("/api/admin/users", json={**ONBOARD, "email": "alice@a.test"}).status_code == 409
    assert admin.post("/api/admin/users", json={**ONBOARD, "email": "not-an-email"}).status_code == 400
