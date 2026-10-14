"""
THE most important tests: one client can never see another client's data.

The endpoint lists are read from the app's own OpenAPI description (the same list
you see at /docs), so any endpoint added later is automatically covered.
"""

import collections
import uuid

import pytest

from app.main import app

from .conftest import make_user

SOME_UUID = "01a125cf-d633-793d-bbf9-c8e737c3d94d"

# Every (METHOD, path) the API offers, e.g. ("GET", "/api/websites/{website_id}/overview").
ALL_ENDPOINTS = sorted(
    (method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations
)

WEBSITE_ROUTES = [
    path for method, path in ALL_ENDPOINTS if method == "GET" and path.startswith("/api/websites/{website_id}")
]
# The routes that always fetch live data from PostHog (weekly reports and sales mostly read our own database).
POSTHOG_ROUTES = [path for path in WEBSITE_ROUTES if "/reports" not in path and "/sales" not in path]

# Endpoints that are open on purpose (you must be able to log in without being logged in).
PUBLIC_ENDPOINTS = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("POST", "/api/billing/webhooks/{provider}"),  # called by payment gateways, protected by their signature
}


def url(path_template: str, website_id) -> str:
    # Any other {placeholder} in a path (client_id, user_id, ...) gets a harmless UUID.
    path = path_template.format_map(collections.defaultdict(lambda: SOME_UUID, website_id=website_id))
    if path.endswith("/events") and "/recordings/" in path:  # this endpoint needs ?start=&end=
        path += "?start=0&end=0"
    return path


def test_all_analytics_and_report_endpoints_are_website_scoped():
    assert len(POSTHOG_ROUTES) == 15, POSTHOG_ROUTES  # the 15 analytics endpoints
    assert len(WEBSITE_ROUTES) == 20, WEBSITE_ROUTES  # + 3 weekly-report endpoints + 2 sales endpoints


def test_every_non_public_api_endpoint_requires_login(api, world):
    client = api()
    checked = 0
    for method, path in ALL_ENDPOINTS:
        if not path.startswith("/api/") or (method, path) in PUBLIC_ENDPOINTS:
            continue
        response = client.request(method, url(path, world.site_a.id), json={})
        assert response.status_code == 401, f"{method} {path} answered {response.status_code}"
        checked += 1
    assert checked >= 17  # 15 analytics endpoints + /me + change-password + the admin API


@pytest.mark.parametrize("path", WEBSITE_ROUTES)
def test_a_client_cannot_read_another_clients_website(path, api, world, fake_posthog):
    alice = api("alice@a.test")  # alice belongs to client A only
    response = alice.get(url(path, world.site_b.id))
    assert response.status_code == 404  # same answer as "doesn't exist"
    assert fake_posthog.calls == []  # PostHog was never even asked


@pytest.mark.parametrize("path", POSTHOG_ROUTES)
def test_a_client_reads_its_own_website_with_its_own_key(path, api, world, fake_posthog):
    alice = api("alice@a.test")
    response = alice.get(url(path, world.site_a.id))
    # Detail endpoints answer 404 "not found" because the fake PostHog has no data,
    # but PostHog WAS asked, and only for client A's project, with client A's key.
    assert response.status_code in (200, 404)
    assert fake_posthog.calls, "PostHog should have been called"
    assert fake_posthog.projects_called() == {7350981}
    assert {call["api_key"] for call in fake_posthog.calls} == {"phx_secret_key_of_A"}


@pytest.mark.parametrize("path", WEBSITE_ROUTES)
def test_not_logged_in_gets_401_everywhere(path, api, world, fake_posthog):
    assert api().get(url(path, world.site_a.id)).status_code == 401
    assert fake_posthog.calls == []


def test_viewer_can_read_their_clients_website(api, world, fake_posthog):
    vera = api("vera@a.test")
    assert vera.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200
    assert vera.get(f"/api/websites/{world.site_b.id}/overview").status_code == 404


def test_admin_can_read_every_website(api, world, fake_posthog):
    admin = api("admin@agency.test")
    assert admin.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200
    assert admin.get(f"/api/websites/{world.site_b.id}/overview").status_code == 200
    assert fake_posthog.projects_called() == {7350981, 8462092}


def test_me_lists_only_the_users_own_websites(api, world):
    alice_sites = {w["id"] for w in api("alice@a.test").get("/api/auth/me").json()["websites"]}
    bob_sites = {w["id"] for w in api("bob@b.test").get("/api/auth/me").json()["websites"]}
    admin_sites = {w["id"] for w in api("admin@agency.test").get("/api/auth/me").json()["websites"]}
    assert alice_sites == {str(world.site_a.id)}
    assert bob_sites == {str(world.site_b.id)}
    assert admin_sites == {str(world.site_a.id), str(world.site_b.id)}


def test_a_user_with_no_client_sees_nothing(api, db, world, fake_posthog):
    make_user(db, "loner@x.test")
    db.commit()
    loner = api("loner@x.test")
    assert loner.get("/api/auth/me").json()["websites"] == []
    assert loner.get(f"/api/websites/{world.site_a.id}/overview").status_code == 404
    assert fake_posthog.calls == []


def test_cached_data_is_not_shared_between_clients(api, world, fake_posthog):
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200  # now cached
    bob = api("bob@b.test")
    assert bob.get(f"/api/websites/{world.site_a.id}/overview").status_code == 404  # cache doesn't help bob


def test_unknown_and_malformed_website_ids(api, world):
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{uuid.uuid4()}/overview").status_code == 404
    assert alice.get("/api/websites/1/overview").status_code == 422
    assert alice.get("/api/websites/x' OR '1'='1/overview").status_code in (404, 422)


def test_suspended_client_is_blocked_but_admin_still_has_access(api, db, world, fake_posthog):
    world.client_a.status = "suspended"
    db.merge(world.client_a)
    db.commit()
    alice = api("alice@a.test")
    response = alice.get(f"/api/websites/{world.site_a.id}/overview")
    assert response.status_code == 403
    assert "suspended" in response.json()["detail"]
    assert api("admin@agency.test").get(f"/api/websites/{world.site_a.id}/overview").status_code == 200


def test_inactive_website_is_hidden(api, db, world):
    world.site_a.is_active = False
    db.merge(world.site_a)
    db.commit()
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 404
    assert alice.get("/api/auth/me").json()["websites"] == []


def test_removing_a_member_takes_effect_immediately(api, db, world):
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 200
    from app.models import ClientMember

    db.delete(db.get(ClientMember, (world.client_a.id, world.alice.id)))
    db.commit()
    assert alice.get(f"/api/websites/{world.site_a.id}/trends").status_code == 404
