"""Usage counting, the PostHog cost estimate, and the usage/cost admin endpoints."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import pricing
from app.jobs import run_job
from app.models import JobRun, UsageDaily

from .conftest import PASSWORD


def today():
    return datetime.now(timezone.utc).date()


# ------------------------------------------------------------------ the price tiers


@pytest.mark.parametrize(
    "events, expected",
    [
        (0, 0.0),
        (1_000_000, 0.0),  # the free allowance
        (1_500_000, 25.0),  # 500k x $0.00005
        (2_000_000, 50.0),
        (3_000_000, 50.0 + 1_000_000 * 0.0000343),  # the next tier is cheaper per event
        (20_000_000, 50.0 + 13_000_000 * 0.0000343 + 5_000_000 * 0.0000295),
    ],
)
def test_event_cost_follows_the_tiers(events, expected):
    assert pricing.event_cost(events) == pytest.approx(expected)


def test_recording_cost_follows_the_tiers():
    assert pricing.recording_cost(5_000) == 0
    assert pricing.recording_cost(10_000) == pytest.approx(5_000 * 0.005)


# ------------------------------------------------------------------ the hourly job


def sync(fake, rows, recordings=None):
    fake.answer("usage:events", ["day", "events", "pageviews"], rows)
    if recordings is not None:
        fake.answer("usage:recordings", ["day", "recordings"], recordings)
    return asyncio.run(run_job("usage_sync", "test"))


def test_usage_sync_saves_daily_counts_for_every_website(db, world, fake_posthog):
    d1, d2 = today() - timedelta(days=1), today()
    result = sync(fake_posthog, [[d1.isoformat(), 120, 40], [d2.isoformat(), 80, 30]], [[d1.isoformat(), 3]])
    assert result["status"] == "ok" and "Synced 2 of 2 websites" in result["message"]

    db.expire_all()
    rows = db.scalars(select(UsageDaily).where(UsageDaily.website_id == world.site_a.id).order_by(UsageDaily.day)).all()
    assert [(r.day, r.events, r.pageviews, r.recordings) for r in rows] == [(d1, 120, 40, 3), (d2, 80, 30, 0)]
    assert db.scalar(select(UsageDaily).where(UsageDaily.website_id == world.site_b.id)) is not None  # every website
    # Each website was read with ITS OWN project and key.
    assert fake_posthog.projects_called() == {7350981, 8462092}


def test_running_the_job_again_updates_instead_of_duplicating(db, world, fake_posthog):
    day = today().isoformat()
    sync(fake_posthog, [[day, 100, 10]])
    sync(fake_posthog, [[day, 150, 12]])  # late events arrived
    db.expire_all()
    rows = db.scalars(select(UsageDaily).where(UsageDaily.website_id == world.site_a.id)).all()
    assert len(rows) == 1 and rows[0].events == 150 and rows[0].pageviews == 12


def test_a_new_website_gets_the_whole_month_and_an_old_one_only_a_few_days(db, world, fake_posthog):
    seen = []
    original = fake_posthog.request

    async def spy(ph, method, path, **kwargs):
        body = kwargs.get("json") or {}
        if body.get("name") == "usage:events":
            seen.append((ph.website.project_id, body["query"]["values"]["days"]))
        return await original(ph, method, path, **kwargs)

    fake_posthog.request = spy
    sync(fake_posthog, [])  # first run: no rows yet
    first_days = {days for _, days in seen}
    assert max(first_days) == min((today() - today().replace(day=1)).days + 1, 45) or max(first_days) == 3

    db.add(UsageDaily(website_id=world.site_a.id, day=today(), events=1))
    db.add(UsageDaily(website_id=world.site_b.id, day=today(), events=1))
    db.commit()
    seen.clear()
    sync(fake_posthog, [])
    assert {days for _, days in seen} == {3}  # afterwards just the last 3 days


def test_missing_recording_permission_does_not_lose_the_event_counts(db, world, fake_posthog):
    from app.posthog_client import AnalyticsError

    original = fake_posthog.request

    async def no_recordings(ph, method, path, **kwargs):
        if (kwargs.get("json") or {}).get("name") == "usage:recordings":
            raise AnalyticsError(502, "forbidden", upstream_status=403, upstream_detail="missing scope")
        return await original(ph, method, path, **kwargs)

    fake_posthog.request = no_recordings
    result = sync(fake_posthog, [[today().isoformat(), 55, 5]])
    assert result["status"] == "ok"
    db.expire_all()
    assert db.scalar(select(UsageDaily.events).where(UsageDaily.website_id == world.site_a.id)) == 55


def test_recordings_that_cannot_be_read_do_not_reset_the_saved_recording_counts(db, world, fake_posthog):
    """Writing zeros would tell a client they still have all their recordings left."""
    from app.posthog_client import AnalyticsError

    day = today()
    sync(fake_posthog, [[day.isoformat(), 40, 4]], [[day.isoformat(), 7]])  # a normal run: 7 recordings today
    original = fake_posthog.request

    async def no_recordings(ph, method, path, **kwargs):
        if (kwargs.get("json") or {}).get("name") == "usage:recordings":
            raise AnalyticsError(502, "forbidden", upstream_status=403, upstream_detail="missing scope")
        return await original(ph, method, path, **kwargs)

    fake_posthog.request = no_recordings
    sync(fake_posthog, [[day.isoformat(), 55, 5]])  # events moved on, recordings unreadable this time
    db.expire_all()
    row = db.scalar(select(UsageDaily).where(UsageDaily.website_id == world.site_a.id, UsageDaily.day == day))
    assert (row.events, row.recordings) == (55, 7)


def test_one_broken_website_does_not_stop_the_others(db, world, fake_posthog):
    from app.models import Website
    from app.security import encrypt_secret

    world.site_b.posthog_api_key_encrypted = encrypt_secret("phx_bad_key")
    db.merge(world.site_b)
    db.commit()
    result = sync(fake_posthog, [[today().isoformat(), 10, 1]])
    assert result["status"] == "ok" and "Synced 1 of 2" in result["message"] and "Failed" in result["message"]
    db.expire_all()
    assert db.scalar(select(UsageDaily).where(UsageDaily.website_id == world.site_a.id)) is not None
    assert db.scalar(select(UsageDaily).where(UsageDaily.website_id == world.site_b.id)) is None
    assert Website  # (imported for clarity)


def test_if_every_website_fails_the_job_is_marked_failed_and_alerts(db, world, fake_posthog):
    from app.models import Alert
    from app.security import encrypt_secret

    for site in (world.site_a, world.site_b):
        site.posthog_api_key_encrypted = encrypt_secret("phx_bad_key")
        db.merge(site)
    db.commit()
    result = sync(fake_posthog, [])
    assert result["status"] == "error"
    db.expire_all()
    run = db.scalars(select(JobRun).where(JobRun.job == "usage_sync")).one()
    assert run.status == "error" and run.finished_at is not None
    alert = db.scalar(select(Alert).where(Alert.dedupe_key == "job_failed:usage_sync", Alert.status == "open"))
    assert alert is not None and alert.severity == "critical"
    # The next good run clears it.
    for site in (world.site_a, world.site_b):
        site.posthog_api_key_encrypted = encrypt_secret("phx_fine")
        db.merge(site)
    db.commit()
    assert sync(fake_posthog, [[today().isoformat(), 1, 1]])["status"] == "ok"
    db.expire_all()
    assert db.scalar(select(Alert).where(Alert.dedupe_key == "job_failed:usage_sync", Alert.status == "open")) is None


def test_inactive_websites_are_not_synced(db, world, fake_posthog):
    world.site_b.is_active = False
    db.merge(world.site_b)
    db.commit()
    result = sync(fake_posthog, [[today().isoformat(), 5, 1]])
    assert "Synced 1 of 1" in result["message"] and fake_posthog.projects_called() == {7350981}


# ------------------------------------------------------------------ the admin usage endpoints


def seed_usage(db, world, a_events, b_events, a_recordings=0):
    db.add(UsageDaily(website_id=world.site_a.id, day=today(), events=a_events, pageviews=a_events // 3, recordings=a_recordings))
    db.add(UsageDaily(website_id=world.site_b.id, day=today(), events=b_events, pageviews=b_events // 3))
    db.commit()


def test_usage_endpoint_totals_costs_and_shares(api, db, world):
    seed_usage(db, world, a_events=1_200_000, b_events=300_000)  # 1.5M events in total
    body = api("admin@agency.test").get("/api/admin/usage").json()

    assert body["totals"]["events"] == 1_500_000
    assert body["cost"]["events_usd"] == pytest.approx(25.0)  # 500k over the free million x $0.00005
    sites = {w["website_name"]: w for w in body["websites"]}
    assert sites["Client A site"]["events"] == 1_200_000 and sites["Client A site"]["share_of_events"] == 0.8
    # The organization-wide bill is split by each website's share of the events.
    assert sites["Client A site"]["estimated_cost_usd"] == pytest.approx(20.0)
    assert sites["Client B site"]["estimated_cost_usd"] == pytest.approx(5.0)
    assert sum(w["estimated_cost_usd"] for w in body["websites"]) == pytest.approx(body["cost"]["total_usd"])
    assert {c["client_name"] for c in body["clients"]} == {"Client A", "Client B"}
    assert body["websites"][0]["website_name"] == "Client A site"  # biggest spender first


def test_usage_projection_for_the_running_month(api, db, world):
    seed_usage(db, world, a_events=1000, b_events=0)
    body = api("admin@agency.test").get("/api/admin/usage").json()
    assert body["in_progress"] is True and 1 <= body["days_elapsed"] <= body["days_in_month"]
    expected = round(1000 * body["days_in_month"] / body["days_elapsed"])
    assert body["totals"]["projected_events"] == expected


def test_usage_for_an_earlier_month_has_no_projection(api, db, world):
    last_month = (today().replace(day=1) - timedelta(days=1))
    db.add(UsageDaily(website_id=world.site_a.id, day=last_month, events=777, pageviews=1))
    db.commit()
    body = api("admin@agency.test").get("/api/admin/usage", params={"month": last_month.strftime("%Y-%m")}).json()
    assert body["in_progress"] is False and body["totals"]["events"] == 777 and body["totals"]["projected_events"] == 777


@pytest.mark.parametrize("month", ["2026-13", "26-10", "2026-1", "'; DROP TABLE users;--", "2026-00"])
def test_usage_rejects_a_bad_month(month, api, world):
    assert api("admin@agency.test").get("/api/admin/usage", params={"month": month}).status_code == 422


def test_website_usage_series_fills_in_zero_days(api, db, world):
    db.add(UsageDaily(website_id=world.site_a.id, day=today() - timedelta(days=2), events=40, pageviews=10))
    db.commit()
    body = api("admin@agency.test").get(f"/api/admin/usage/websites/{world.site_a.id}", params={"days": 7}).json()
    assert len(body["series"]) == 7
    assert [p["events"] for p in body["series"]][-3:] == [40, 0, 0]
    assert api("admin@agency.test").get("/api/admin/usage/websites/00000000-0000-0000-0000-000000000000").status_code == 404


def test_usage_is_admin_only(api, world):
    assert api("alice@a.test").get("/api/admin/usage").status_code == 403
    assert api().get("/api/admin/usage").status_code == 401
    _ = PASSWORD
