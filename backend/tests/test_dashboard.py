"""The "My dashboard" tiles on the Overview page: what can be chosen, saving a choice per person, and the numbers."""

import pytest
from sqlalchemy import select

from app.models import DashboardPref, User
from app.services import tiles

DEFAULT = ["active_users_30d", "sessions_7d", "pageviews_7d"]


def url(site, suffix=""):
    return f"/api/websites/{site.id}/dashboard{suffix}"


def answer_everything(fake):
    fake.answer("tiles:events_agg", ["active_users_30d", "events_7d", "pageviews_7d", "visitors_7d"], [[605, 4665, 994, 541]])
    fake.answer("tiles:sessions", ["sessions", "avg_duration", "bounce_rate", "pages_per_visit"], [[570, 92.67, 0.1719, 1.7439]])
    fake.answer("tiles:top_page", ["path", "views"], [["/collections/kitchen", 267]])
    fake.answer("tiles:top_country", ["country", "visitors"], [["Pakistan", 502]])
    fake.answer("tiles:mobile", ["mobile", "total"], [[514, 541]])
    fake.answer("tiles:events", ["event", "last_7", "last_30"], [["whatsapp_click", 33, 120], ["cta_click", 10, 40]])


# ------------------------------------------------------------------ first time: ask, don't show


def test_someone_who_never_chose_is_asked_first_and_no_analytics_are_spent(api, world, fake_posthog):
    response = api("alice@a.test").get(url(world.site_a, "/tiles")).json()
    assert response == {"configured": False, "tiles": []}
    assert fake_posthog.calls == []


def test_a_choice_is_saved_and_then_shown_with_numbers_in_the_chosen_order(api, db, world, fake_posthog):
    answer_everything(fake_posthog)
    alice = api("alice@a.test")
    chosen = ["pageviews_7d", "event:whatsapp_click:7", "active_users_30d", "bounce_rate_7d", "avg_visit_7d", "top_page_7d", "top_country_7d", "mobile_share_7d", "pages_per_visit_7d", "event:cta_click:30", "events_7d", "visitors_7d", "sessions_7d"]
    assert alice.put(url(world.site_a, "/prefs"), json={"tiles": chosen}).json() == {"configured": True, "keys": chosen}
    response = alice.get(url(world.site_a, "/tiles")).json()
    assert response["configured"] is True and [t["key"] for t in response["tiles"]] == chosen
    by_key = {t["key"]: t for t in response["tiles"]}
    assert by_key["active_users_30d"]["value"] == 605 and by_key["active_users_30d"]["title"] == "Active users (last 30 days)"
    assert by_key["sessions_7d"]["value"] == 570 and by_key["pageviews_7d"]["value"] == 994 and by_key["events_7d"]["value"] == 4665 and by_key["visitors_7d"]["value"] == 541
    assert by_key["bounce_rate_7d"]["value"] == 17.2 and by_key["bounce_rate_7d"]["kind"] == "percent"
    assert by_key["avg_visit_7d"]["value"] == 93 and by_key["avg_visit_7d"]["kind"] == "duration"
    assert by_key["pages_per_visit_7d"]["value"] == 1.7 and by_key["pages_per_visit_7d"]["kind"] == "decimal"
    assert by_key["top_page_7d"]["value"] == "/collections/kitchen" and by_key["top_country_7d"]["value"] == "Pakistan"
    assert by_key["mobile_share_7d"]["value"] == 95.0
    assert by_key["event:whatsapp_click:7"]["value"] == 33 and by_key["event:whatsapp_click:7"]["title"] == "whatsapp_click (last 7 days)"
    assert by_key["event:cta_click:30"]["value"] == 40 and "last 30 days" in by_key["event:cta_click:30"]["description"]
    for tile in response["tiles"]:
        assert tile["description"] and tile["kind"] in {"number", "decimal", "percent", "duration", "text"}


def test_only_the_queries_the_chosen_tiles_need_are_run(api, world, fake_posthog):
    answer_everything(fake_posthog)
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": DEFAULT})
    alice.get(url(world.site_a, "/tiles"))
    assert sorted({c["query_name"] for c in fake_posthog.calls}) == ["tiles:events_agg", "tiles:sessions"]  # not top page, country, phone, events
    fake_posthog.calls.clear()
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["event:whatsapp_click:7"]})
    alice.get(url(world.site_a, "/tiles"))
    assert [c["query_name"] for c in fake_posthog.calls] == ["tiles:events"]


def test_a_tracked_event_with_no_rows_counts_zero_and_nothing_chosen_is_allowed(api, world, fake_posthog):
    fake_posthog.answer("tiles:events", ["event", "last_7", "last_30"], [])
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["event:never_happened:7"]})
    assert alice.get(url(world.site_a, "/tiles")).json()["tiles"][0]["value"] == 0
    assert alice.put(url(world.site_a, "/prefs"), json={"tiles": []}).status_code == 200  # "show nothing" is a valid choice...
    assert alice.get(url(world.site_a, "/tiles")).json() == {"configured": True, "tiles": []}  # ...and is not the same as "never chose"


def test_a_website_with_no_data_shows_zeros_not_errors(api, world, fake_posthog):
    alice = api("alice@a.test")  # (the fake answers every query with no rows)
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["active_users_30d", "bounce_rate_7d", "top_page_7d", "mobile_share_7d"]})
    values = {t["key"]: t["value"] for t in alice.get(url(world.site_a, "/tiles")).json()["tiles"]}
    assert values == {"active_users_30d": 0, "bounce_rate_7d": 0.0, "top_page_7d": "No data yet", "mobile_share_7d": 0.0}


# ------------------------------------------------------------------ the catalog


def test_the_catalog_lists_builtin_tiles_and_the_websites_tracked_events(api, world, fake_posthog):
    fake_posthog.answer("events:custom", ["event", "count", "visitors", "last_seen"], [["whatsapp_click", 120, 50, "2026-10-14T10:00:00Z"], ["cta_click", 40, 20, "2026-10-13T10:00:00Z"]])
    catalog = api("alice@a.test").get(url(world.site_a, "/tiles/catalog")).json()
    assert [t["key"] for t in catalog["tiles"]] == [t.key for t in tiles.BUILTIN] and len(catalog["tiles"]) == 11
    assert {t["group"] for t in catalog["tiles"]} == {"Traffic", "Engagement", "Content", "Audience"}
    assert catalog["events"] == [{"event": "whatsapp_click", "count": 120}, {"event": "cta_click", "count": 40}]
    assert set(DEFAULT) <= {t["key"] for t in catalog["tiles"]}  # the pre-ticked ones exist


# ------------------------------------------------------------------ everyone has their own view


def test_each_person_and_each_website_has_its_own_choice(api, db, world):
    api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": ["sessions_7d"]})
    assert api("vera@a.test").get(url(world.site_a, "/tiles")).json()["configured"] is False  # vera never chose, whatever alice did
    api("vera@a.test").put(url(world.site_a, "/prefs"), json={"tiles": ["pageviews_7d"]})
    assert [t["key"] for t in api("alice@a.test").get(url(world.site_a, "/tiles")).json()["tiles"]] == ["sessions_7d"]
    admin = api("admin@agency.test")  # an admin sees many websites: one choice per website
    admin.put(url(world.site_a, "/prefs"), json={"tiles": ["events_7d"]})
    assert admin.get(url(world.site_b, "/tiles")).json()["configured"] is False
    assert db.scalar(select(DashboardPref.tiles).where(DashboardPref.website_id == world.site_a.id, DashboardPref.user_id == world.alice.id)) == ["sessions_7d"]


def test_nobody_can_read_or_save_for_another_clients_website(api, world, fake_posthog):
    alice = api("alice@a.test")
    for method, path, body in [("get", "/tiles", None), ("get", "/tiles/catalog", None), ("put", "/prefs", {"tiles": ["sessions_7d"]})]:
        response = getattr(alice, method)(url(world.site_b, path), **({"json": body} if body else {}))
        assert response.status_code == 404, path
    assert fake_posthog.calls == []
    assert api().get(url(world.site_a, "/tiles")).status_code == 401
    assert api().put(url(world.site_a, "/prefs"), json={"tiles": []}).status_code == 401


def test_viewing_as_a_client_is_read_only(api, world):
    admin = api("admin@agency.test")
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    assert admin.put(url(world.site_a, "/prefs"), json={"tiles": ["sessions_7d"]}).status_code == 403
    assert admin.get(url(world.site_a, "/tiles")).json() == {"configured": False, "tiles": []}


def test_deleting_a_user_or_website_removes_the_choices(api, db, world):
    api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": ["sessions_7d"]})
    assert db.scalars(select(DashboardPref)).all()
    db.delete(db.get(User, world.alice.id))
    db.commit()
    assert db.scalars(select(DashboardPref)).all() == []


# ------------------------------------------------------------------ what may be saved


@pytest.mark.parametrize("bad", [
    ["not_a_tile"], ["event:x:5"], ["event::7"], ["event:x"], ["event:" + "a" * 101 + ":7"], ["event: padded :7"], ["event:bad\nname:7"],
    ["sessions_7d", "nope"], ["EVENT:x:7"], ["pageviews_7d;drop table"], [""],
])
def test_unknown_or_malformed_tiles_are_refused_and_nothing_is_saved(api, db, world, bad):
    assert api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": bad}).status_code == 422
    assert db.scalars(select(DashboardPref)).all() == []


def test_too_many_tiles_are_refused(api, world):
    many = [f"event:e{i}:7" for i in range(tiles.MAX_TILES + 1)]
    assert api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": many}).status_code == 422
    assert api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": many[:-1]}).status_code == 200
    assert api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": ["x"] * 101}).status_code == 422
    assert api("alice@a.test").put(url(world.site_a, "/prefs"), json={}).status_code == 422


def test_duplicates_are_dropped_and_event_names_with_odd_characters_are_fine(api, world):
    chosen = ["sessions_7d", "sessions_7d", "event:Add to cart: size “M” ✓:30", "event:a:b:c:7"]
    saved = api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": chosen}).json()["keys"]
    assert saved == ["sessions_7d", "event:Add to cart: size “M” ✓:30", "event:a:b:c:7"]
    assert tiles.parse_event_key("event:a:b:c:7") == ("a:b:c", 7)


def test_a_hostile_event_name_is_only_ever_passed_as_a_value_never_pasted_into_the_query(api, world, fake_posthog, monkeypatch):
    seen = []
    from app import posthog_client

    original = posthog_client.PostHogClient.hogql

    async def spy(self, query, values=None, **kwargs):
        seen.append((query, values))
        return await original(self, query, values, **kwargs)

    monkeypatch.setattr(posthog_client.PostHogClient, "hogql", spy)
    evil = "x') OR 1=1 --"
    api("alice@a.test").put(url(world.site_a, "/prefs"), json={"tiles": [f"event:{evil}:7"]})
    api("alice@a.test").get(url(world.site_a, "/tiles"))
    [(query, values)] = seen
    assert evil not in query and "{names}" in query and values == {"names": [evil]}


def test_a_saved_key_that_stopped_making_sense_is_skipped_not_fatal(api, db, world, fake_posthog):
    answer_everything(fake_posthog)
    db.add(DashboardPref(user_id=world.alice.id, website_id=world.site_a.id, tiles=["retired_tile", "sessions_7d"]))
    db.commit()
    assert [t["key"] for t in api("alice@a.test").get(url(world.site_a, "/tiles")).json()["tiles"]] == ["sessions_7d"]
