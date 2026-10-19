"""A client's own settings: name, logo, time zone, language, weekly report switch, and the team."""

import base64
from datetime import date

import pytest
from sqlalchemy import select

from app import accounts
from app.billing.service import FEATURES
from app.models import AuditLog, Client, ClientMember, Plan, Subscription, User

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def url(client, suffix=""):
    return f"/api/clients/{client.id}{suffix}"


def limit_plan(db, world, *, members=None, team=True):
    """Put client A on a plan with a team-size limit."""
    features = {k: True for k in FEATURES}
    features["team_members"] = team
    plan = Plan(name="Small", slug="small", features=features, price_pkr=1, price_usd=1, max_team_members=members)
    db.add(plan)
    db.commit()
    db.add(Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=date(2026, 1, 1), billing_day=1))
    db.commit()


# ------------------------------------------------------------------ who may use it


def test_only_owners_and_admins_can_use_the_settings(api, world):
    for path in ("/settings", "/team"):
        assert api("alice@a.test").get(url(world.client_a, path)).status_code == 200
        assert api("admin@agency.test").get(url(world.client_a, path)).status_code == 200
        assert api("vera@a.test").get(url(world.client_a, path)).status_code == 403  # a viewer
        assert api("bob@b.test").get(url(world.client_a, path)).status_code == 404  # another client's owner
        assert api().get(url(world.client_a, path)).status_code == 401


def test_changes_by_non_owners_are_refused(api, db, world):
    vera, bob = api("vera@a.test"), api("bob@b.test")
    assert vera.patch(url(world.client_a, "/settings"), json={"name": "Mine now"}).status_code == 403
    assert bob.patch(url(world.client_a, "/settings"), json={"name": "Mine now"}).status_code == 404
    assert vera.put(url(world.client_a, "/logo"), json={"data": b64(PNG)}).status_code == 403
    assert bob.delete(url(world.client_a, "/team/" + str(world.vera.id))).status_code == 404
    db.expire_all()
    assert db.get(Client, world.client_a.id).name == "Client A"


def test_an_admin_looking_as_another_client_cannot_touch_this_one(api, world):
    admin = api("admin@agency.test")
    assert admin.post("/api/admin/view-as", json={"client_id": str(world.client_b.id)}).status_code == 200
    assert admin.get(url(world.client_a, "/settings")).status_code == 404
    assert admin.get(url(world.client_b, "/settings")).status_code == 200


def test_view_as_is_read_only(api, world):
    admin = api("admin@agency.test")
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    assert admin.patch(url(world.client_a, "/settings"), json={"name": "Changed"}).status_code == 403


# ------------------------------------------------------------------ settings


def test_settings_are_read_and_changed(api, db, world):
    alice = api("alice@a.test")
    assert alice.get(url(world.client_a, "/settings")).json() | {"timezones": None} == {
        "name": "Client A", "timezone": "Asia/Karachi", "report_language": "en", "weekly_report_enabled": True, "has_logo": False, "timezones": None,
        "whatsapp_available": False, "whatsapp_number": None, "whatsapp_reports_enabled": False,
    }
    changed = alice.patch(url(world.client_a, "/settings"), json={"name": "  Ali Traders  ", "timezone": "Asia/Dubai", "report_language": "roman_ur", "weekly_report_enabled": False})
    assert changed.status_code == 200 and changed.json()["name"] == "Ali Traders"
    db.expire_all()
    client = db.get(Client, world.client_a.id)
    assert (client.name, client.timezone, client.report_language, client.weekly_report_enabled) == ("Ali Traders", "Asia/Dubai", "roman_ur", False)
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "client.settings_changed")).one()
    assert entry.actor_user_id == world.alice.id and entry.details["fields"] == ["name", "report_language", "timezone", "weekly_report_enabled"]


def test_a_partial_change_leaves_the_rest_alone(api, db, world):
    api("alice@a.test").patch(url(world.client_a, "/settings"), json={"weekly_report_enabled": False})
    db.expire_all()
    client = db.get(Client, world.client_a.id)
    assert client.name == "Client A" and client.timezone == "Asia/Karachi" and client.weekly_report_enabled is False


@pytest.mark.parametrize("body", [
    {"name": ""}, {"name": "x" * 201}, {"timezone": "Mars/Olympus"}, {"timezone": "../../etc/passwd"}, {"timezone": "Asia/Karachi; drop table"},
    {"report_language": "klingon"}, {"weekly_report_enabled": "maybe"},
])
def test_bad_settings_are_refused(api, db, world, body):
    assert api("alice@a.test").patch(url(world.client_a, "/settings"), json=body).status_code in (400, 422)
    db.expire_all()
    assert db.get(Client, world.client_a.id).name == "Client A"


def test_an_unusual_time_zone_still_appears_in_the_list(api, db, world):
    world.client_a.timezone = "Pacific/Auckland"
    db.merge(world.client_a)
    db.commit()
    zones = api("alice@a.test").get(url(world.client_a, "/settings")).json()["timezones"]
    assert zones[0] == "Pacific/Auckland" and "Asia/Karachi" in zones


# ------------------------------------------------------------------ logo


@pytest.mark.parametrize("data, mime", [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")])
def test_a_logo_is_stored_and_served_with_its_real_type(api, world, data, mime):
    alice = api("alice@a.test")
    assert alice.put(url(world.client_a, "/logo"), json={"data": b64(data)}).json() == {"ok": True, "has_logo": True}
    served = alice.get(url(world.client_a, "/logo"))
    assert served.status_code == 200 and served.content == data and served.headers["content-type"] == mime
    assert served.headers["x-content-type-options"] == "nosniff" and "sandbox" in served.headers["content-security-policy"]
    assert alice.get(url(world.client_a, "/settings")).json()["has_logo"] is True
    assert api("vera@a.test").get(url(world.client_a, "/logo")).status_code == 200  # every member can see it


def test_a_data_url_is_accepted(api, world):
    alice = api("alice@a.test")
    assert alice.put(url(world.client_a, "/logo"), json={"data": "data:image/png;base64," + b64(PNG)}).status_code == 200


@pytest.mark.parametrize("payload, why", [
    (SVG, "svg can carry scripts"), (b"GIF89a" + b"\x00" * 30, "gif"), (b"<html>hi</html>", "html"),
    (b"MZ" + b"\x00" * 64, "an exe renamed .png"), (b"", "empty"),
])
def test_only_real_png_jpeg_webp_are_accepted(api, world, payload, why):
    response = api("alice@a.test").put(url(world.client_a, "/logo"), json={"data": b64(payload)})
    assert response.status_code == 400, why
    assert api("alice@a.test").get(url(world.client_a, "/logo")).status_code == 404


def test_a_png_claimed_by_the_browser_but_not_really_a_png_is_refused(api, world):
    fake = "data:image/png;base64," + b64(SVG)  # says png, is svg
    assert api("alice@a.test").put(url(world.client_a, "/logo"), json={"data": fake}).status_code == 400


def test_logo_size_and_encoding_limits(api, world):
    alice = api("alice@a.test")
    assert alice.put(url(world.client_a, "/logo"), json={"data": b64(PNG + b"\x00" * 300_000)}).status_code in (400, 422)
    assert alice.put(url(world.client_a, "/logo"), json={"data": "!!!not base64!!!"}).status_code == 400
    assert alice.put(url(world.client_a, "/logo"), json={}).status_code == 422


def test_a_logo_is_private_to_its_client_and_can_be_removed(api, world):
    alice = api("alice@a.test")
    alice.put(url(world.client_a, "/logo"), json={"data": b64(PNG)})
    assert api("bob@b.test").get(url(world.client_a, "/logo")).status_code == 404  # another client's member
    assert api().get(url(world.client_a, "/logo")).status_code == 401
    assert alice.delete(url(world.client_a, "/logo")).json()["has_logo"] is False
    assert alice.get(url(world.client_a, "/logo")).status_code == 404


# ------------------------------------------------------------------ team


def test_the_team_is_listed(api, world):
    team = api("alice@a.test").get(url(world.client_a, "/team")).json()
    assert [(m["email"], m["role"], m["is_you"]) for m in team["members"]] == [("alice@a.test", "owner", True), ("vera@a.test", "viewer", False)]
    assert team["can_invite"] is True and team["max_members"] is None
    assert "argon2" not in str(team) and "password_hash" not in str(team)  # no hashes, ever


def test_inviting_a_new_person_creates_an_account_and_a_link(api, db, world, monkeypatch):
    sent = []
    monkeypatch.setattr(accounts, "send_invite_email", lambda person, link, client_name, invited_by=None: sent.append((person.email, link, client_name)))
    response = api("alice@a.test").post(url(world.client_a, "/team"), json={"email": "  New.Person@A.test ", "name": "New Person", "role": "viewer"})
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.person@a.test" and "/reset-password?token=" in body["invite_link"]
    assert sent == [("new.person@a.test", body["invite_link"], "Client A")]
    db.expire_all()
    person = db.scalar(select(User).where(User.email == "new.person@a.test"))
    assert db.get(ClientMember, (world.client_a.id, person.id)).role == "viewer"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "client.member_added")).one().details["new_user"] is True


def test_the_invite_link_lets_the_new_person_choose_a_password_once(api, db, world):
    link = api("alice@a.test").post(url(world.client_a, "/team"), json={"email": "fresh@a.test"}).json()["invite_link"]
    token = link.split("token=")[1].split("&")[0]
    guest = api()
    assert guest.post("/api/auth/reset-password", json={"token": token, "new_password": "A-very-long-new-password-1"}).status_code == 200
    assert guest.post("/api/auth/reset-password", json={"token": token, "new_password": "Another-long-password-2"}).status_code == 400  # single use
    assert api("fresh@a.test", "A-very-long-new-password-1").get("/api/auth/me").status_code == 200


def test_no_link_is_ever_made_for_someone_who_already_has_an_account(api, db, world, monkeypatch):
    """SECURITY: otherwise the person inviting could set the password of somebody else's account."""
    sent = []
    monkeypatch.setattr(accounts, "send_invite_email", lambda *a, **k: sent.append(a))
    before = world.bob.token_version
    response = api("alice@a.test").post(url(world.client_a, "/team"), json={"email": "BOB@b.test", "role": "owner"})
    assert response.status_code == 201 and response.json()["invite_link"] is None and sent == []
    db.expire_all()
    assert db.get(ClientMember, (world.client_a.id, world.bob.id)).role == "owner"
    assert db.get(User, world.bob.id).token_version == before


def test_inviting_the_same_person_twice_or_with_a_bad_email(api, world):
    alice = api("alice@a.test")
    assert alice.post(url(world.client_a, "/team"), json={"email": "vera@a.test"}).status_code == 409
    assert alice.post(url(world.client_a, "/team"), json={"email": "not-an-email"}).status_code == 400
    assert alice.post(url(world.client_a, "/team"), json={"email": "x@y.test", "role": "admin"}).status_code == 422


def test_the_plan_decides_if_and_how_many_can_be_invited(api, db, world):
    limit_plan(db, world, members=3)
    alice = api("alice@a.test")
    assert alice.post(url(world.client_a, "/team"), json={"email": "third@a.test"}).status_code == 201  # alice, vera, third = 3
    full = alice.post(url(world.client_a, "/team"), json={"email": "fourth@a.test"})
    assert full.status_code == 409 and "allows 3 team members" in full.json()["detail"]
    assert alice.get(url(world.client_a, "/team")).json()["max_members"] == 3


def test_a_plan_without_team_members_cannot_invite(api, db, world):
    limit_plan(db, world, team=False)
    alice = api("alice@a.test")
    assert alice.get(url(world.client_a, "/team")).json()["can_invite"] is False
    response = alice.post(url(world.client_a, "/team"), json={"email": "new@a.test"})
    assert response.status_code == 403 and "Team members" in response.json()["detail"]


def test_roles_can_be_changed_but_an_account_always_keeps_an_owner(api, db, world):
    alice = api("alice@a.test")
    assert alice.patch(url(world.client_a, f"/team/{world.alice.id}"), json={"role": "viewer"}).status_code == 409  # the only owner
    promoted = alice.patch(url(world.client_a, f"/team/{world.vera.id}"), json={"role": "owner"})
    assert promoted.status_code == 200 and {m["email"]: m["role"] for m in promoted.json()["members"]}["vera@a.test"] == "owner"
    assert alice.patch(url(world.client_a, f"/team/{world.alice.id}"), json={"role": "viewer"}).status_code == 200  # now there is another owner
    db.expire_all()
    assert db.get(ClientMember, (world.client_a.id, world.alice.id)).role == "viewer"


def test_members_can_be_removed_but_never_the_last_owner(api, db, world):
    alice = api("alice@a.test")
    assert alice.delete(url(world.client_a, f"/team/{world.alice.id}")).status_code == 409
    assert alice.delete(url(world.client_a, f"/team/{world.vera.id}")).status_code == 200
    db.expire_all()
    assert db.get(ClientMember, (world.client_a.id, world.vera.id)) is None
    assert db.get(User, world.vera.id) is not None  # the account itself stays; only the access goes
    assert alice.delete(url(world.client_a, f"/team/{world.vera.id}")).status_code == 404
    assert api("vera@a.test").get(f"/api/websites/{world.site_a.id}/overview").status_code == 404  # no access any more


def test_you_cannot_reach_into_another_clients_team(api, world):
    alice = api("alice@a.test")
    assert alice.delete(url(world.client_a, f"/team/{world.bob.id}")).status_code == 404  # bob is not on A's team
    assert alice.patch(url(world.client_b, f"/team/{world.bob.id}"), json={"role": "viewer"}).status_code == 404
    assert alice.post(url(world.client_b, "/team"), json={"email": "mole@x.test"}).status_code == 404


def test_the_website_list_says_whether_there_is_a_logo_without_sending_it(api, world):
    alice = api("alice@a.test")
    assert alice.get("/api/auth/me").json()["websites"][0]["client_has_logo"] is False
    alice.put(url(world.client_a, "/logo"), json={"data": b64(PNG)})
    me = alice.get("/api/auth/me")
    assert me.json()["websites"][0]["client_has_logo"] is True and b64(PNG) not in me.text
