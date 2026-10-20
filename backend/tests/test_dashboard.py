"""The "My dashboard" tiles on the Overview page: what can be chosen, saving a choice per person, and the numbers."""

import pytest
from sqlalchemy import select

from app.models import DashboardPref, User
from app.services import tiles

DEFAULT = ["active_users_30d", "sessions_7d", "pageviews_7d"]


def url(site, suffix=""):
    return f"/api/websites/{site.id}/dashboard{suffix}"


def answer_everything(fake):
    # Each total comes with the same number for the period before ("prev_..."); "today" in the daily answers is 2026-10-19.
    fake.answer("tiles:events_agg", ["active_users_30d", "prev_active_users_30d", "events_7d", "prev_events_7d", "pageviews_7d", "prev_pageviews_7d", "visitors_7d", "prev_visitors_7d"],
                [[605, 500, 4665, 4000, 994, 1100, 541, 541]])
    fake.answer("tiles:sessions", ["sessions", "avg_duration", "bounce_rate", "pages_per_visit", "prev_sessions", "prev_avg_duration", "prev_bounce_rate", "prev_pages_per_visit"],
                [[570, 92.67, 0.1719, 1.7439, 400, 80.0, 0.25, 1.5]])
    fake.answer("tiles:top_page", ["path", "views"], [["/collections/kitchen", 267]])
    fake.answer("tiles:top_country", ["country", "visitors"], [["Pakistan", 502]])
    fake.answer("tiles:mobile", ["mobile", "total", "prev_mobile", "prev_total"], [[514, 541, 400, 500]])
    fake.answer("tiles:events", ["event", "last_7", "last_30", "prev_7", "prev_30"], [["whatsapp_click", 33, 120, 30, 100], ["cta_click", 10, 40, 5, 0]])
    fake.answer("tiles:events_daily", ["day", "today", "events", "pageviews", "active", "visitors", "mobile"],
                [["2026-10-18", "2026-10-19", 100, 40, 12, 9, 8], ["2026-10-19", "2026-10-19", 150, 60, 15, 11, 5]])
    fake.answer("tiles:sessions_daily", ["day", "today", "sessions", "avg_duration", "bounce_rate", "pages_per_visit"], [["2026-10-19", "2026-10-19", 30, 90.0, 0.2, 2.0]])
    fake.answer("tiles:events_by_day", ["event", "day", "today", "times"], [["whatsapp_click", "2026-10-19", "2026-10-19", 5], ["whatsapp_click", "2026-10-17", "2026-10-19", 3]])


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


def test_every_tile_has_a_short_label_a_comparison_with_the_period_before_and_a_graph(api, world, fake_posthog):
    answer_everything(fake_posthog)
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": [t.key for t in tiles.BUILTIN] + ["event:whatsapp_click:7", "event:cta_click:30"]})
    by_key = {t["key"]: t for t in alice.get(url(world.site_a, "/tiles")).json()["tiles"]}

    # the short name for the card (the full title, with the period, is for the chooser and the box)
    assert by_key["active_users_30d"]["label"] == "Active users" and by_key["active_users_30d"]["title"] == "Active users (last 30 days)"
    assert by_key["event:whatsapp_click:7"]["label"] == "whatsapp_click" and by_key["event:whatsapp_click:7"]["title"] == "whatsapp_click (last 7 days)"
    assert {k: t["better"] for k, t in by_key.items() if t["better"] != "up"} == {"bounce_rate_7d": "down"}  # fewer people leaving is the good news

    # the same number for the period just before it
    assert {k: by_key[k]["previous"] for k in ("active_users_30d", "events_7d", "pageviews_7d", "visitors_7d", "sessions_7d")} == {
        "active_users_30d": 500, "events_7d": 4000, "pageviews_7d": 1100, "visitors_7d": 541, "sessions_7d": 400}
    assert (by_key["bounce_rate_7d"]["previous"], by_key["avg_visit_7d"]["previous"], by_key["pages_per_visit_7d"]["previous"], by_key["mobile_share_7d"]["previous"]) == (25.0, 80, 1.5, 80.0)
    assert (by_key["event:whatsapp_click:7"]["previous"], by_key["event:cta_click:30"]["previous"]) == (30, 0)
    assert by_key["top_page_7d"]["previous"] is None and by_key["top_country_7d"]["previous"] is None  # words have nothing to compare

    # one number per day, oldest first, ending today (a day without rows is a real zero)
    assert by_key["pageviews_7d"]["series"] == [0, 0, 0, 0, 0, 40, 60]
    assert by_key["visitors_7d"]["series"] == [0, 0, 0, 0, 0, 9, 11] and by_key["events_7d"]["series"] == [0, 0, 0, 0, 0, 100, 150]
    assert len(by_key["active_users_30d"]["series"]) == 30 and by_key["active_users_30d"]["series"][-2:] == [12, 15]  # (a 30 day tile gets 30 days)
    assert by_key["sessions_7d"]["series"] == [0, 0, 0, 0, 0, 0, 30] and by_key["bounce_rate_7d"]["series"][-1] == 20.0
    assert by_key["avg_visit_7d"]["series"][-1] == 90 and by_key["pages_per_visit_7d"]["series"][-1] == 2.0
    assert by_key["mobile_share_7d"]["series"][-2:] == [88.9, 45.5]  # a share of that day's visitors
    assert by_key["event:whatsapp_click:7"]["series"] == [0, 0, 0, 0, 3, 0, 5] and len(by_key["event:cta_click:30"]["series"]) == 30
    assert by_key["top_page_7d"]["series"] is None and by_key["top_country_7d"]["series"] is None
    assert not any(t["empty"] for t in by_key.values())


def test_the_numbers_still_show_when_the_daily_numbers_for_the_graphs_cannot_be_read(api, world, fake_posthog):
    from app.posthog_client import AnalyticsError

    answer_everything(fake_posthog)
    original = fake_posthog.request

    async def graphs_down(ph, method, path, **kwargs):
        if (kwargs.get("json") or {}).get("name", "").endswith(("_daily", "events_by_day")):
            raise AnalyticsError(502, "slow", upstream_status=500, upstream_detail="timeout")
        return await original(ph, method, path, **kwargs)

    fake_posthog.request = graphs_down
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["pageviews_7d", "sessions_7d", "event:whatsapp_click:7"]})
    response = alice.get(url(world.site_a, "/tiles"))
    assert response.status_code == 200  # a missing graph is no reason to lose the page
    by_key = {t["key"]: t for t in response.json()["tiles"]}
    assert (by_key["pageviews_7d"]["value"], by_key["sessions_7d"]["value"], by_key["event:whatsapp_click:7"]["value"]) == (994, 570, 33)
    assert by_key["pageviews_7d"]["previous"] == 1100  # (the comparison comes with the totals)
    assert all(by_key[k]["series"] is None for k in by_key)

    async def numbers_down(ph, method, path, **kwargs):
        if (kwargs.get("json") or {}).get("name") == "tiles:events_agg":
            raise AnalyticsError(502, "down", upstream_status=500, upstream_detail="boom")
        return await original(ph, method, path, **kwargs)

    from app.cache import cache

    cache.clear()  # (the first answers were remembered for a few minutes)
    fake_posthog.request = numbers_down
    assert alice.get(url(world.site_a, "/tiles")).status_code == 502  # the numbers themselves are a real error


def test_an_average_of_no_visits_is_marked_empty_and_has_nothing_to_compare(api, world, fake_posthog):
    fake_posthog.answer("tiles:sessions", ["sessions", "avg_duration", "bounce_rate", "pages_per_visit", "prev_sessions", "prev_avg_duration", "prev_bounce_rate", "prev_pages_per_visit"],
                        [[0, None, None, None, 0, None, None, None]])  # a quiet week, and a quiet week before it
    fake_posthog.answer("tiles:mobile", ["mobile", "total", "prev_mobile", "prev_total"], [[0, 0, 0, 0]])
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["sessions_7d", "bounce_rate_7d", "avg_visit_7d", "pages_per_visit_7d", "mobile_share_7d", "top_page_7d", "top_country_7d"]})
    by_key = {t["key"]: t for t in alice.get(url(world.site_a, "/tiles")).json()["tiles"]}
    # no visits is a real zero for a COUNT, but "0% left after one page" would be a lie: those cards say "no visits" instead
    assert by_key["sessions_7d"]["empty"] is False and by_key["sessions_7d"]["value"] == 0 and by_key["sessions_7d"]["previous"] == 0
    for key in ("bounce_rate_7d", "avg_visit_7d", "pages_per_visit_7d", "mobile_share_7d", "top_page_7d", "top_country_7d"):
        assert by_key[key]["empty"] is True, key
    assert [by_key[k]["previous"] for k in ("bounce_rate_7d", "avg_visit_7d", "pages_per_visit_7d", "mobile_share_7d")] == [None, None, None, None]


def test_a_week_with_visits_after_a_quiet_week_has_no_average_to_compare_with(api, world, fake_posthog):
    answer_everything(fake_posthog)
    fake_posthog.answer("tiles:sessions", ["sessions", "avg_duration", "bounce_rate", "pages_per_visit", "prev_sessions", "prev_avg_duration", "prev_bounce_rate", "prev_pages_per_visit"],
                        [[570, 92.67, 0.1719, 1.7439, 0, None, None, None]])
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["sessions_7d", "bounce_rate_7d"]})
    by_key = {t["key"]: t for t in alice.get(url(world.site_a, "/tiles")).json()["tiles"]}
    assert by_key["sessions_7d"]["previous"] == 0 and by_key["bounce_rate_7d"]["previous"] is None and by_key["bounce_rate_7d"]["empty"] is False


def test_only_the_queries_the_chosen_tiles_need_are_run(api, world, fake_posthog):
    answer_everything(fake_posthog)
    alice = api("alice@a.test")
    alice.put(url(world.site_a, "/prefs"), json={"tiles": DEFAULT})
    alice.get(url(world.site_a, "/tiles"))
    # (each family is one query for the numbers and one for the little graphs) - not top page, country, phone or events
    assert sorted({c["query_name"] for c in fake_posthog.calls}) == ["tiles:events_agg", "tiles:events_daily", "tiles:sessions", "tiles:sessions_daily"]
    fake_posthog.calls.clear()
    alice.put(url(world.site_a, "/prefs"), json={"tiles": ["event:whatsapp_click:7"]})
    alice.get(url(world.site_a, "/tiles"))
    assert sorted(c["query_name"] for c in fake_posthog.calls) == ["tiles:events", "tiles:events_by_day"]


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
    assert len(seen) == 2  # the counts, and the days for the little graph
    for query, values in seen:
        assert evil not in query and "{names}" in query and values == {"names": [evil]}


def test_a_saved_key_that_stopped_making_sense_is_skipped_not_fatal(api, db, world, fake_posthog):
    answer_everything(fake_posthog)
    db.add(DashboardPref(user_id=world.alice.id, website_id=world.site_a.id, tiles=["retired_tile", "sessions_7d"]))
    db.commit()
    assert [t["key"] for t in api("alice@a.test").get(url(world.site_a, "/tiles")).json()["tiles"]] == ["sessions_7d"]
