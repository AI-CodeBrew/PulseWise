"""The team on a client account: logins created by the owner (with a password), suspending, re-activating, removing."""

from sqlalchemy import select

from app import accounts
from app.billing.notifications import recipients
from app.models import AuditLog, ClientMember, User
from app.security import verify_password

from .conftest import add_member

GOOD_PASSWORD = "Ali-Gmail-Pass-1"


def url(client, suffix=""):
    return f"/api/clients/{client.id}{suffix}"


def add_person(api, world, email="ali@gmail.com", **extra):
    return api("alice@a.test").post(url(world.client_a, "/team"), json={"email": email, "role": "viewer", **extra})


def user_id(db, email):
    return db.scalar(select(User.id).where(User.email == email))


# ------------------------------------------------------------------ a login created by the owner


def test_an_owner_can_create_a_login_with_a_password_and_no_email_or_link_is_needed(api, db, world, monkeypatch):
    sent = []
    monkeypatch.setattr(accounts, "send_invite_email", lambda *a, **k: sent.append(a))
    response = add_person(api, world, password=GOOD_PASSWORD, name="Ali")
    assert response.status_code == 201
    assert response.json() == {"email": "ali@gmail.com", "role": "viewer", "invite_link": None, "password_set": True, "new_account": True}
    assert sent == []  # nothing is emailed: the owner hands the login over
    db.expire_all()
    assert verify_password(db.scalar(select(User).where(User.email == "ali@gmail.com")).password_hash, GOOD_PASSWORD)
    assert GOOD_PASSWORD not in str([e.details for e in db.scalars(select(AuditLog))])  # the password is never logged
    ali = api("ali@gmail.com", GOOD_PASSWORD)  # and they can log in with it and see the website
    assert [w["id"] for w in ali.get("/api/auth/me").json()["websites"]] == [str(world.site_a.id)]


def test_without_a_password_a_new_person_still_gets_the_invite_link(api, world):
    response = add_person(api, world).json()
    assert response["password_set"] is False and "/reset-password?token=" in response["invite_link"]


def test_a_weak_password_is_refused_before_anything_is_created(api, db, world):
    assert add_person(api, world, password="short").status_code == 400
    assert db.scalar(select(User).where(User.email == "ali@gmail.com")) is None


def test_a_password_given_for_someone_who_already_has_an_account_is_never_applied(api, db, world):
    """SECURITY: otherwise an owner could take over any account by 'inviting' its email together with a password."""
    before = world.bob.password_hash
    response = add_person(api, world, email="bob@b.test", password="Taken-Over-Pass-1")
    assert response.status_code == 201 and response.json()["password_set"] is False and response.json()["new_account"] is False
    db.expire_all()
    assert db.get(User, world.bob.id).password_hash == before
    api("bob@b.test")  # bob's own password still works


# ------------------------------------------------------------------ suspend and re-activate


def test_a_person_can_be_suspended_and_let_back_in(api, db, world):
    add_person(api, world, password=GOOD_PASSWORD)
    ali_id = user_id(db, "ali@gmail.com")
    alice, ali = api("alice@a.test"), api("ali@gmail.com", GOOD_PASSWORD)
    suspended = alice.patch(url(world.client_a, f"/team/{ali_id}"), json={"suspended": True})
    assert suspended.status_code == 200 and {m["email"]: m["suspended"] for m in suspended.json()["members"]}["ali@gmail.com"] is True
    # Locked out at once, on their existing login: no websites, no website data, no client pages.
    assert ali.get("/api/auth/me").json()["websites"] == []
    assert ali.get(f"/api/websites/{world.site_a.id}/overview").status_code == 404
    assert ali.get(url(world.client_a, "/logo")).status_code == 404 and ali.get(url(world.client_a, "/team")).status_code == 404
    assert ali.get(url(world.client_a, "/billing")).status_code == 404
    api("ali@gmail.com", GOOD_PASSWORD)  # they can still log in (and see nothing), and they stay on the list
    again = alice.patch(url(world.client_a, f"/team/{ali_id}"), json={"suspended": False})
    assert again.status_code == 200 and {m["email"]: m["suspended"] for m in again.json()["members"]}["ali@gmail.com"] is False
    assert [w["id"] for w in ali.get("/api/auth/me").json()["websites"]] == [str(world.site_a.id)]
    actions = sorted(e.action for e in db.scalars(select(AuditLog).where(AuditLog.action.like("client.member_%suspended"))))
    assert actions == ["client.member_suspended", "client.member_unsuspended"]


def test_suspending_at_one_client_does_not_touch_the_same_person_at_another(api, db, world):
    add_member(db, world.client_b, world.vera, "viewer")  # vera now belongs to A and B
    db.commit()
    api("alice@a.test").patch(url(world.client_a, f"/team/{world.vera.id}"), json={"suspended": True})
    assert [w["id"] for w in api("vera@a.test").get("/api/auth/me").json()["websites"]] == [str(world.site_b.id)]


def test_you_cannot_suspend_yourself_or_remove_the_last_active_owner(api, db, world):
    alice = api("alice@a.test")
    assert alice.patch(url(world.client_a, f"/team/{world.alice.id}"), json={"suspended": True}).status_code == 409
    add_person(api, world, email="boss@gmail.com", password=GOOD_PASSWORD)
    boss_id = user_id(db, "boss@gmail.com")
    alice.patch(url(world.client_a, f"/team/{boss_id}"), json={"role": "owner"})
    assert alice.patch(url(world.client_a, f"/team/{boss_id}"), json={"suspended": True}).status_code == 200  # two owners: fine
    # Now alice is the only ACTIVE owner (a suspended owner doesn't count): she can't be demoted or removed...
    assert api("boss@gmail.com", GOOD_PASSWORD).get(url(world.client_a, "/team")).status_code == 404
    assert alice.patch(url(world.client_a, f"/team/{world.alice.id}"), json={"role": "viewer"}).status_code == 409
    assert alice.delete(url(world.client_a, f"/team/{world.alice.id}")).status_code == 409
    # ...but the suspended owner can be removed, and the last active owner can't be suspended.
    assert alice.delete(url(world.client_a, f"/team/{boss_id}")).status_code == 200


def test_a_patch_must_change_something_and_only_owners_may_suspend(api, world):
    assert api("alice@a.test").patch(url(world.client_a, f"/team/{world.vera.id}"), json={}).status_code == 422
    assert api("vera@a.test").patch(url(world.client_a, f"/team/{world.alice.id}"), json={"suspended": True}).status_code == 403
    assert api("bob@b.test").patch(url(world.client_a, f"/team/{world.vera.id}"), json={"suspended": True}).status_code == 404


def test_a_suspended_owner_no_longer_gets_the_clients_emails(db, world):
    assert "alice@a.test" in recipients(db, world.client_a)
    db.get(ClientMember, (world.client_a.id, world.alice.id)).suspended = True
    db.commit()
    assert "alice@a.test" not in recipients(db, world.client_a)


def test_a_suspended_person_can_be_removed_and_added_again(api, db, world):
    add_person(api, world, password=GOOD_PASSWORD)
    ali_id = user_id(db, "ali@gmail.com")
    alice = api("alice@a.test")
    alice.patch(url(world.client_a, f"/team/{ali_id}"), json={"suspended": True})
    assert alice.delete(url(world.client_a, f"/team/{ali_id}")).status_code == 200
    again = add_person(api, world, password="Another-Pass-9")  # the login still exists, so this only gives access again
    assert again.json()["new_account"] is False and again.json()["password_set"] is False
    assert [w["id"] for w in api("ali@gmail.com", GOOD_PASSWORD).get("/api/auth/me").json()["websites"]] == [str(world.site_a.id)]


# ------------------------------------------------------------------ a new password made by the owner


def test_an_owner_can_set_a_new_password_for_their_own_people_and_it_logs_them_out(api, db, world):
    add_person(api, world, password=GOOD_PASSWORD)
    ali_id = user_id(db, "ali@gmail.com")
    ali = api("ali@gmail.com", GOOD_PASSWORD)
    team = api("alice@a.test").get(url(world.client_a, "/team")).json()["members"]
    assert {m["email"]: m["can_set_password"] for m in team} == {"alice@a.test": False, "ali@gmail.com": True, "vera@a.test": True}
    assert api("alice@a.test").put(url(world.client_a, f"/team/{ali_id}/password"), json={"password": "Brand-New-Pass-2"}).status_code == 200
    assert ali.get("/api/auth/me").status_code == 401  # the old session is gone
    assert api("ali@gmail.com", "Brand-New-Pass-2").get("/api/auth/me").status_code == 200
    assert api().post("/api/auth/login", json={"email": "ali@gmail.com", "password": GOOD_PASSWORD}).status_code == 401
    assert "Brand-New-Pass-2" not in str([e.details for e in db.scalars(select(AuditLog))])


def test_a_password_can_not_be_set_for_logins_that_are_not_only_this_clients(api, db, world):
    """SECURITY: someone who also belongs to another business (or an admin) has a login the owner must not take over."""
    add_member(db, world.client_b, world.vera, "viewer")
    db.add(ClientMember(client_id=world.client_a.id, user_id=world.admin.id, role="viewer"))
    db.commit()
    alice = api("alice@a.test")
    attempt = {"password": "Taken-Over-Pass-1"}
    assert alice.put(url(world.client_a, f"/team/{world.vera.id}/password"), json=attempt).status_code == 409  # also at client B
    assert alice.put(url(world.client_a, f"/team/{world.admin.id}/password"), json=attempt).status_code == 409  # an admin
    assert alice.put(url(world.client_a, f"/team/{world.alice.id}/password"), json=attempt).status_code == 409  # herself: use Account
    assert alice.put(url(world.client_a, f"/team/{world.bob.id}/password"), json=attempt).status_code == 404  # not on this team at all
    db.expire_all()
    assert not verify_password(db.get(User, world.vera.id).password_hash, "Taken-Over-Pass-1")


def test_setting_a_password_needs_an_owner_and_a_decent_password(api, db, world):
    add_person(api, world, password=GOOD_PASSWORD)
    path = url(world.client_a, f"/team/{user_id(db, 'ali@gmail.com')}/password")
    assert api("alice@a.test").put(path, json={"password": "short"}).status_code == 400
    assert api("vera@a.test").put(path, json={"password": "Brand-New-Pass-2"}).status_code == 403
    assert api("bob@b.test").put(path, json={"password": "Brand-New-Pass-2"}).status_code == 404
    assert api().put(path, json={"password": "Brand-New-Pass-2"}).status_code == 401
