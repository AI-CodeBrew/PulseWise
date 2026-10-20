"""The box behind a dashboard tile: the trend and breakdowns, the latest visits or events, and the Watch-recording flags."""

from datetime import date, timedelta

import pytest

from app.billing.service import FEATURES
from app.models import Plan, Subscription
from app.posthog_client import AnalyticsError, PostHogClient
from app.services import tile_details, tiles

TODAY = "2026-10-19"
BUILTIN_KEYS = [t.key for t in tiles.BUILTIN]


def detail_url(site, key):
    return f"/api/websites/{site.id}/dashboard/tiles/detail"


def get_detail(client, site, key):
    return client.get(f"/api/websites/{site.id}/dashboard/tiles/detail", params={"key": key})


def get_recent(client, site, key):
    return client.get(f"/api/websites/{site.id}/dashboard/tiles/recent", params={"key": key})


def answer_detail(fake, breakdown_keys=(), series_rows=None):
    fake.answer("tiles:detail:series", ["day", "value", "today"], series_rows if series_rows is not None else [["2026-10-17", 10, TODAY], ["2026-10-19", 30, TODAY]])
    for k in breakdown_keys:
        fake.answer(f"tiles:detail:breakdown:{k}", ["name", "value"], [["/collections/kitchen", 267], ["/collections/skincare", 129], [None, 3]])
    fake.answer("tiles:top_page", ["path", "views"], [["/collections/kitchen", 267]])
    fake.answer("tiles:top_country", ["country", "visitors"], [["Pakistan", 502]])


SESSION_COLUMNS = ["session_id", "started_at", "duration", "entry_page", "pageviews", "visitor"]
SESSIONS = [
    ["01a153d7-0000-7000-8000-000000000001", "2026-10-19T11:06:32Z", 22.0, "/collections/kitchen", 1, "01a153d7-74d1-7e95-9000-aaaaaaaaaaaa"],
    ["01a153d7-0000-7000-8000-000000000002", "2026-10-19T10:00:00Z", 125.0, "/products/hoodie", 4, "ali@gmail.com"],
    ["01a153d7-0000-7000-8000-000000000003", "2026-10-18T10:00:00Z", 0, None, 1, None],
]


def spy_on_queries(monkeypatch):
    """Record (name, query text, values) of every analytics query, then run it normally (against the fake)."""
    seen = []
    original = PostHogClient.hogql

    async def spy(self, query, values=None, **kwargs):
        seen.append({"name": kwargs.get("name"), "query": query, "values": dict(values or {})})
        return await original(self, query, values, **kwargs)

    monkeypatch.setattr(PostHogClient, "hogql", spy)
    return seen


# ------------------------------------------------------------------ the trend and breakdowns


@pytest.mark.parametrize("key", BUILTIN_KEYS)
def test_every_built_in_tile_has_a_trend_and_breakdowns(api, world, fake_posthog, key):
    breakdown_keys, _ = tile_details.PLAN[key]
    answer_detail(fake_posthog, breakdown_keys)
    body = get_detail(api("alice@a.test"), world.site_a, key).json()
    days = 30 if key == "active_users_30d" else 7
    assert body["key"] == key and body["days"] == days
    assert body["period"] == {"start": (date.fromisoformat(TODAY) - timedelta(days=days - 1)).isoformat(), "end": TODAY}
    points = body["series"]["points"]
    assert len(points) == days and points[-1]["date"] == TODAY and [p["date"] for p in points] == sorted(p["date"] for p in points)
    by_day = {p["date"]: p["value"] for p in points}
    assert by_day["2026-10-19"] == 30 and by_day["2026-10-17"] == 10 and by_day["2026-10-18"] == 0  # a day without rows is a real zero
    assert body["series"]["label"] and body["series"]["kind"] in {"number", "decimal", "percent", "duration"}
    assert [b["key"] for b in body["breakdowns"]] == breakdown_keys
    for breakdown in body["breakdowns"]:
        assert breakdown["title"] and breakdown["unit"] and breakdown["rows"][0] == {"name": "/collections/kitchen", "value": 267}
        assert breakdown["rows"][2]["name"] == "(unknown)"  # a visit without that information still gets a readable row


def test_the_trend_of_a_quiet_website_is_all_zeros_not_an_error(api, world, fake_posthog):
    body = get_detail(api("alice@a.test"), world.site_a, "sessions_7d").json()  # (the fake answers nothing)
    assert [p["value"] for p in body["series"]["points"]] == [0] * 7 and all(b["rows"] == [] for b in body["breakdowns"])


def test_percent_duration_and_decimal_tiles_keep_one_decimal_or_whole_seconds(api, world, fake_posthog):
    fake_posthog.answer("tiles:detail:series", ["day", "value", "today"], [["2026-10-19", 17.19, TODAY]])
    assert get_detail(api("alice@a.test"), world.site_a, "bounce_rate_7d").json()["series"]["points"][-1]["value"] == 17.2
    fake_posthog.answer("tiles:detail:series", ["day", "value", "today"], [["2026-10-19", 92.6, TODAY]])
    assert get_detail(api("alice@a.test"), world.site_a, "avg_visit_7d").json()["series"]["points"][-1]["value"] == 93
    assert get_detail(api("alice@a.test"), world.site_a, "pages_per_visit_7d").json()["series"]["points"][-1]["value"] == 92.6


def test_the_providers_own_event_names_are_explained_in_plain_words(api, world, fake_posthog):
    fake_posthog.answer("tiles:detail:breakdown:events_by_name", ["name", "value"],
                        [["$autocapture", 1561], ["$web_vitals", 1205], ["$pageview", 994], ["$some_new_thing", 5], ["whatsapp_click", 33]])
    fake_posthog.answer("tiles:detail:breakdown:pages", ["name", "value"], [])
    rows = get_detail(api("alice@a.test"), world.site_a, "events_7d").json()["breakdowns"][0]["rows"]
    assert [r["name"] for r in rows] == ["Clicks and taps (recorded automatically)", "Page speed measurements", "Page views", "Some new thing", "whatsapp_click"]


def test_a_tracked_event_tile_has_its_own_story_and_the_name_only_travels_as_a_value(api, world, fake_posthog, monkeypatch):
    seen = spy_on_queries(monkeypatch)
    evil = "x') OR 1=1 --"
    answer_detail(fake_posthog, ["event_pages", "event_devices"])
    body = get_detail(api("alice@a.test"), world.site_a, f"event:{evil}:30").json()
    assert body["days"] == 30 and len(body["series"]["points"]) == 30 and body["series"]["label"] == f"“{evil}” per day"
    assert [b["key"] for b in body["breakdowns"]] == ["event_pages", "event_devices"]
    assert len(seen) == 3 and all(evil not in q["query"] and "{name}" in q["query"] and q["values"] == {"days": 30, "name": evil} for q in seen)


def test_the_top_page_and_top_country_tiles_follow_whatever_is_on_top_right_now(api, world, fake_posthog, monkeypatch):
    seen = spy_on_queries(monkeypatch)
    answer_detail(fake_posthog, ["pages", "page_countries"])
    body = get_detail(api("alice@a.test"), world.site_a, "top_page_7d").json()
    assert body["subject"] == "/collections/kitchen" and "/collections/kitchen" in body["series"]["label"]
    filtered = [q for q in seen if "{path}" in q["query"]]
    assert len(filtered) == 2 and all(q["values"]["path"] == "/collections/kitchen" for q in filtered)  # the trend and the countries
    assert not any("path" in q["values"] for q in seen if "{path}" not in q["query"])  # nobody gets a value it doesn't use

    answer_detail(fake_posthog, ["countries", "country_pages"])
    assert get_detail(api("alice@a.test"), world.site_a, "top_country_7d").json()["subject"] == "Pakistan"


def test_unknown_keys_are_refused_and_access_is_checked(api, world, fake_posthog):
    alice = api("alice@a.test")
    for bad in ["nope", "event:x:5", "sessions_7d;drop", "event::7"]:
        assert get_detail(alice, world.site_a, bad).status_code == 422 and get_recent(alice, world.site_a, bad).status_code == 422
    assert alice.get(f"/api/websites/{world.site_a.id}/dashboard/tiles/detail").status_code == 422  # key is required
    assert get_detail(alice, world.site_b, "sessions_7d").status_code == 404 and get_recent(alice, world.site_b, "sessions_7d").status_code == 404
    assert fake_posthog.calls == []
    assert get_detail(api(), world.site_a, "sessions_7d").status_code == 401 and get_recent(api(), world.site_a, "sessions_7d").status_code == 401


# ------------------------------------------------------------------ the latest rows and the Watch buttons


def test_latest_visits_say_which_ones_have_a_recording(api, world, fake_posthog, monkeypatch):
    seen = spy_on_queries(monkeypatch)
    fake_posthog.answer("tiles:detail:list", SESSION_COLUMNS, SESSIONS)
    fake_posthog.answer("tiles:detail:recordings", ["session_id"], [["01a153d7-0000-7000-8000-000000000002"]])
    body = get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()
    assert body["title"] == "Latest visits" and body["kind"] == "sessions" and body["locked"] is None
    assert body["recordings"] == {"locked": None, "checked": True}
    first, second, third = body["rows"]
    assert (first["has_recording"], second["has_recording"], third["has_recording"]) == (False, True, False)
    assert first["session_id"] == "01a153d7-0000-7000-8000-000000000001" and first["duration"] == 22 and first["visitor"] == "Visitor 01a153d7"
    assert second["visitor"] == "ali@gmail.com" and second["entry_page"] == "/products/hoodie" and second["pageviews"] == 4
    assert third["visitor"] == "Unknown visitor" and third["entry_page"] == "(unknown)"
    [recorded_query] = [q for q in seen if q["name"] == "tiles:detail:recordings"]  # one question for all the rows
    assert recorded_query["values"]["ids"] == sorted(r[0] for r in SESSIONS) and "{ids}" in recorded_query["query"]


def test_latest_events_link_to_their_visit_and_a_missing_visit_has_no_recording(api, world, fake_posthog):
    fake_posthog.answer("tiles:detail:list", ["uuid", "event", "timestamp", "path", "session_id", "visitor"], [
        ["e1", "$pageview", "2026-10-19T11:06:32Z", "/collections/kitchen", "01a153d7-0000-7000-8000-000000000001", "01a153d7-74d1"],
        ["e2", "$pageleave", "2026-10-19T11:07:00Z", None, None, None],
    ])
    fake_posthog.answer("tiles:detail:recordings", ["session_id"], [["01a153d7-0000-7000-8000-000000000001"]])
    body = get_recent(api("alice@a.test"), world.site_a, "pageviews_7d").json()
    assert body["title"] == "Latest page views" and body["kind"] == "events"
    first, second = body["rows"]
    assert first == {"id": "e1", "event": "Page views", "timestamp": "2026-10-19T11:06:32Z", "page": "/collections/kitchen", "visitor": "Visitor 01a153d7",
                     "session_id": "01a153d7-0000-7000-8000-000000000001", "has_recording": True}
    assert second["event"] == "People leaving a page" and second["page"] == "-" and second["session_id"] is None and second["has_recording"] is False


def test_with_no_rows_nothing_more_is_asked(api, world, fake_posthog):
    body = get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()
    assert body["rows"] == [] and body["recordings"]["checked"] is True
    assert [c["query_name"] for c in fake_posthog.calls] == ["tiles:detail:list"]  # no recordings question for zero rows


def test_when_the_recording_lookup_fails_the_list_still_shows_and_the_flags_stay_unknown(api, world, fake_posthog, monkeypatch):
    fake_posthog.answer("tiles:detail:list", SESSION_COLUMNS, SESSIONS)
    original = PostHogClient.hogql

    async def failing(self, query, values=None, **kwargs):
        if kwargs.get("name") == "tiles:detail:recordings":
            raise AnalyticsError(502, "not allowed", upstream_status=403, upstream_detail="missing scope")
        return await original(self, query, values, **kwargs)

    monkeypatch.setattr(PostHogClient, "hogql", failing)
    body = get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()
    assert len(body["rows"]) == 3 and all(r["has_recording"] is None for r in body["rows"]) and body["recordings"]["checked"] is False
    assert "missing scope" not in str(body)


@pytest.mark.parametrize("key, title, query_marker", [
    ("sessions_7d", "Latest visits", "ORDER BY $start_timestamp DESC"),
    ("bounce_rate_7d", "Latest visits where the person left after one page", "$is_bounce = 1"),
    ("avg_visit_7d", "Longest visits", "ORDER BY $session_duration DESC"),
    ("pages_per_visit_7d", "Visits with the most pages", "ORDER BY $pageview_count DESC"),
    ("mobile_visits", "Latest visits on a phone", "'Mobile', 'Tablet'"),
])
def test_each_tile_asks_for_the_rows_that_explain_it(api, world, fake_posthog, monkeypatch, key, title, query_marker):
    seen = spy_on_queries(monkeypatch)
    key = "mobile_share_7d" if key == "mobile_visits" else key
    assert get_recent(api("alice@a.test"), world.site_a, key).json()["title"] == title
    [listing] = [q for q in seen if q["name"] == "tiles:detail:list"]
    assert query_marker in listing["query"]


def test_titles_name_the_page_country_or_event(api, world, fake_posthog):
    fake_posthog.answer("tiles:top_page", ["path", "views"], [["/collections/kitchen", 267]])
    fake_posthog.answer("tiles:top_country", ["country", "visitors"], [["Pakistan", 502]])
    alice = api("alice@a.test")
    assert get_recent(alice, world.site_a, "top_page_7d").json()["title"] == "Latest visits that viewed /collections/kitchen"
    assert get_recent(alice, world.site_a, "top_country_7d").json()["title"] == "Latest visits from Pakistan"
    assert get_recent(alice, world.site_a, "event:cta_click:7").json()["title"] == "Latest times “cta_click” happened"


# ------------------------------------------------------------------ what the plan allows


def put_on_plan(db, world, **features):
    plan = Plan(name="Small", slug="small", features={**{k: True for k in FEATURES}, **features}, price_pkr=1, price_usd=1)
    db.add(plan)
    db.commit()
    db.add(Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=date(2026, 1, 1), billing_day=1))
    db.commit()


def test_without_the_recordings_feature_the_rows_show_but_nothing_can_be_watched(api, db, world, fake_posthog):
    put_on_plan(db, world, recordings=False)
    fake_posthog.answer("tiles:detail:list", SESSION_COLUMNS, SESSIONS)
    body = get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()
    assert len(body["rows"]) == 3 and all(r["has_recording"] is None for r in body["rows"])
    assert body["recordings"] == {"locked": "Your plan doesn't include Recordings. Please contact support to upgrade.", "checked": False}
    assert "tiles:detail:recordings" not in [c["query_name"] for c in fake_posthog.calls]  # (and no query was wasted on it)


def test_without_the_sessions_feature_the_visit_list_is_locked_and_never_asked_for(api, db, world, fake_posthog):
    put_on_plan(db, world, sessions=False)
    body = get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()
    assert body["rows"] == [] and body["locked"] == "Your plan doesn't include Sessions. Please contact support to upgrade."
    assert fake_posthog.calls == []
    # the trend and breakdowns are plain statistics: still there
    assert get_detail(api("alice@a.test"), world.site_a, "sessions_7d").status_code == 200


def test_without_the_live_events_feature_the_event_list_is_locked(api, db, world, fake_posthog):
    put_on_plan(db, world, live_events=False)
    body = get_recent(api("alice@a.test"), world.site_a, "events_7d").json()
    assert body["rows"] == [] and "Live events" in body["locked"]
    assert get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()["locked"] is None  # visits are a different feature


def test_admins_and_clients_without_a_plan_are_never_locked(api, db, world, fake_posthog):
    assert get_recent(api("alice@a.test"), world.site_a, "sessions_7d").json()["recordings"]["locked"] is None  # (no plan = unrestricted)
    put_on_plan(db, world, **{k: False for k in FEATURES})
    admin_body = get_recent(api("admin@agency.test"), world.site_a, "sessions_7d").json()
    assert admin_body["locked"] is None and admin_body["recordings"]["locked"] is None


def test_viewers_can_open_the_box_too(api, world, fake_posthog):
    assert get_detail(api("vera@a.test"), world.site_a, "sessions_7d").status_code == 200
    assert get_recent(api("vera@a.test"), world.site_a, "sessions_7d").status_code == 200


def test_the_tiles_list_says_how_many_days_each_tile_covers(api, world, fake_posthog):
    alice = api("alice@a.test")
    alice.put(f"/api/websites/{world.site_a.id}/dashboard/prefs", json={"tiles": ["active_users_30d", "sessions_7d", "event:cta_click:30"]})
    days = {t["key"]: t["days"] for t in alice.get(f"/api/websites/{world.site_a.id}/dashboard/tiles").json()["tiles"]}
    assert days == {"active_users_30d": 30, "sessions_7d": 7, "event:cta_click:30": 30}
