"""Alerts, the daily health job, PostHog errors turning into alerts, the job runner, jobs API, settings."""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import alerts as alerts_module
from app import posthog_client
from app.alerts import raise_alert, record_posthog_error, resolve_alerts
from app.jobs import JOBS, run_job
from app.jobs.registry import JobLock
from app.models import Alert, AppSetting, JobRun
from app.posthog_client import PostHogClient

from .conftest import FakeNetwork

REAL_REQUEST = PostHogClient._request  # captured BEFORE the autouse fake replaces it


@pytest.fixture
def emails(monkeypatch):
    """Capture the emails the app would send."""
    sent = []
    monkeypatch.setattr(alerts_module, "send_email", lambda to, subject, body: sent.append((to, subject, body)))
    return sent


def open_alerts(db, kind=None):
    db.expire_all()
    query = select(Alert).where(Alert.status == "open")
    if kind:
        query = query.where(Alert.kind == kind)
    return db.scalars(query).all()


# ------------------------------------------------------------------ raising and resolving


def test_the_same_problem_raises_one_alert_that_counts_up(db, world):
    first, created = raise_alert(db, kind="no_events", dedupe_key="k1", message="quiet", website_id=world.site_a.id)
    second, created_again = raise_alert(db, kind="no_events", dedupe_key="k1", message="still quiet", website_id=world.site_a.id)
    assert created and not created_again and first.id == second.id
    assert second.occurrences == 2 and second.message == "still quiet"
    assert len(open_alerts(db)) == 1


def test_after_resolving_a_new_problem_opens_a_new_alert(db, world):
    raise_alert(db, kind="no_events", dedupe_key="k2", message="quiet")
    assert resolve_alerts(db, dedupe_key="k2") == 1
    assert resolve_alerts(db, dedupe_key="k2") == 0
    _, created = raise_alert(db, kind="no_events", dedupe_key="k2", message="quiet again")
    assert created
    db.expire_all()
    assert len(db.scalars(select(Alert).where(Alert.dedupe_key == "k2")).all()) == 2  # history is kept


def test_resolving_by_website_and_kind(db, world):
    raise_alert(db, kind="posthog_error", dedupe_key="a", message="x", website_id=world.site_a.id)
    raise_alert(db, kind="posthog_error", dedupe_key="b", message="y", website_id=world.site_b.id)
    raise_alert(db, kind="no_events", dedupe_key="c", message="z", website_id=world.site_a.id)
    assert resolve_alerts(db, website_id=world.site_a.id, kind="posthog_error") == 1
    assert {a.dedupe_key for a in open_alerts(db)} == {"b", "c"}


# ------------------------------------------------------------------ PostHog errors become alerts (real client code, fake network)


@pytest.fixture
def real_client(monkeypatch):
    """Use the REAL PostHogClient._request with a pretend network, and report errors like the live app does."""
    monkeypatch.setattr(PostHogClient, "_request", REAL_REQUEST)

    def install(handler):
        FakeNetwork.handler = handler  # (the app's startup, replaced in conftest, uses this pretend network)
        return FakeNetwork.paths

    async def no_sleep(_):  # don't wait during retries
        return None

    monkeypatch.setattr(posthog_client.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(posthog_client, "error_listeners", [record_posthog_error])
    return install


def ask_posthog(world, site="a", path="overview"):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        login = "alice@a.test" if site == "a" else "bob@b.test"
        client.post("/api/auth/login", json={"email": login, "password": "correct-horse-battery-staple"})
        site_id = world.site_a.id if site == "a" else world.site_b.id
        return client.get(f"/api/websites/{site_id}/{path}")


def test_a_refused_key_becomes_a_critical_alert_for_admins_only(db, world, real_client, emails):
    real_client(lambda r: httpx.Response(401, json={"detail": "Invalid API key"}))
    response = ask_posthog(world)
    assert response.status_code == 502
    assert "posthog" not in response.text.lower()  # the CLIENT's message stays white-label

    [alert] = open_alerts(db, "posthog_error")
    assert alert.severity == "critical" and alert.website_id == world.site_a.id and alert.client_id == world.client_a.id
    assert "refused the API key" in alert.message and "Invalid API key" in alert.message  # the ADMIN gets the real reason
    assert [e[0] for e in emails] == ["admin@agency.test"]  # emailed once, to the admin


def test_repeated_errors_do_not_pile_up_alerts_or_emails(db, world, real_client, emails):
    real_client(lambda r: httpx.Response(401, json={"detail": "Invalid API key"}))
    for _ in range(3):
        ask_posthog(world, path="trends")
    [alert] = open_alerts(db, "posthog_error")
    assert alert.occurrences >= 3 and len(emails) == 1


def test_a_busy_posthog_is_retried_and_then_works_without_any_alert(db, world, real_client):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503, json={"detail": "Queries are a little too busy right now."})
        return httpx.Response(200, json={"columns": [], "results": []})

    real_client(handler)
    assert ask_posthog(world).status_code == 200
    assert attempts["n"] >= 3 and open_alerts(db) == []


def test_posthog_staying_busy_raises_a_warning(db, world, real_client):
    real_client(lambda r: httpx.Response(503, json={"detail": "busy"}))
    assert ask_posthog(world, path="trends").status_code == 503
    [alert] = open_alerts(db, "posthog_error")
    assert alert.severity == "warning" and "503" in alert.message


def test_a_missing_recording_is_not_a_connection_problem(db, world, real_client):
    real_client(lambda r: httpx.Response(404, json={"detail": "Not found."}))
    response = ask_posthog(world, path="recordings/01a0eebd-1729-7069-8fc2-8cff61d875e4")
    assert response.status_code == 404 and "Recording not found" in response.json()["detail"]
    assert open_alerts(db) == []  # a 404 about ONE recording must not look like "the project is gone"


def test_a_missing_project_is_a_critical_alert(db, world, real_client):
    real_client(lambda r: httpx.Response(404, json={"detail": "Not found."}))
    ask_posthog(world, path="overview")
    [alert] = open_alerts(db, "posthog_error")
    assert alert.severity == "critical" and "could not find the project" in alert.message


def test_connection_checks_never_create_alerts(db, world, real_client):
    from app.posthog_admin import check_connection

    real_client(lambda r: httpx.Response(401, json={"detail": "Invalid API key"}))

    async def go():
        await posthog_client.startup()  # (the pretend network, see conftest)
        return await check_connection("https://us.posthog.com", 123, "phx_wrong")

    result = asyncio.run(go())
    assert result["ok"] is False and "Invalid API key" in result["message"]
    assert open_alerts(db) == []


# ------------------------------------------------------------------ the daily health job


def health(fake, events, last_event):
    fake.answer("health:24h", ["events", "pageviews", "last_event_at"], [[events, events // 2, last_event]])
    if events == 0:
        fake.answer("health:last", ["last_event_at"], [[last_event]])


def run_health():
    return asyncio.run(run_job("daily_health", "test"))


def age_websites(db, world, days=10):
    for site in (world.site_a, world.site_b):
        site.created_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.merge(site)
    db.commit()


def test_a_silent_website_raises_one_alert_and_emails_the_admin(db, world, fake_posthog, emails):
    age_websites(db, world)
    health(fake_posthog, 0, (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat())
    result = run_health()
    assert result["status"] == "ok" and "2 silent" in result["message"]
    alerts = open_alerts(db, "no_events")
    assert len(alerts) == 2 and {a.website_id for a in alerts} == {world.site_a.id, world.site_b.id}
    assert all("72 hours" in a.message for a in alerts)
    assert len(emails) == 2 and {e[0] for e in emails} == {"admin@agency.test"}

    run_health()  # the next day, still silent: same alerts, no new emails
    assert len(open_alerts(db, "no_events")) == 2 and len(emails) == 2


def test_data_coming_back_resolves_the_alert(db, world, fake_posthog, emails):
    age_websites(db, world)
    health(fake_posthog, 0, (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat())
    run_health()
    assert len(open_alerts(db, "no_events")) == 2
    from app.cache import cache

    cache.clear()
    health(fake_posthog, 250, datetime.now(timezone.utc).isoformat())
    run_health()
    assert open_alerts(db, "no_events") == []


def test_a_brand_new_website_is_given_time_before_alerting(db, world, fake_posthog, emails):
    health(fake_posthog, 0, None)  # never any data, but the websites were created just now
    run_health()
    assert open_alerts(db, "no_events") == [] and emails == []


def test_a_website_that_never_sent_anything_alerts_once_old_enough(db, world, fake_posthog, emails):
    age_websites(db, world)
    health(fake_posthog, 0, None)
    run_health()
    assert all("never sent an event" in a.message for a in open_alerts(db, "no_events"))


def test_a_quiet_day_is_not_an_alert(db, world, fake_posthog, emails):
    age_websites(db, world)
    health(fake_posthog, 0, (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())  # 30h < the 48h threshold
    run_health()
    assert open_alerts(db, "no_events") == []


def test_the_threshold_can_be_changed_in_settings(db, world, fake_posthog, api):
    age_websites(db, world)
    health(fake_posthog, 0, (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat())
    assert api("admin@agency.test").patch("/api/admin/settings", json={"values": {"alerts.no_events_hours": 24}}).status_code == 200
    run_health()
    assert len(open_alerts(db, "no_events")) == 2


def test_a_working_connection_clears_old_posthog_error_alerts(db, world, fake_posthog):
    age_websites(db, world)
    raise_alert(db, kind="posthog_error", dedupe_key=f"posthog_error:{world.site_a.id}:401", message="refused", website_id=world.site_a.id)
    health(fake_posthog, 100, datetime.now(timezone.utc).isoformat())
    run_health()
    assert open_alerts(db, "posthog_error") == []


# ------------------------------------------------------------------ the job runner


def test_a_job_that_crashes_is_recorded_and_alerted_not_propagated(db, monkeypatch):
    async def boom():
        raise ValueError("kaboom")

    monkeypatch.setitem(JOBS, "usage_sync", JOBS["usage_sync"].__class__(**{**JOBS["usage_sync"].__dict__, "func": boom}))
    result = asyncio.run(run_job("usage_sync", "test"))
    assert result["status"] == "error" and "kaboom" in result["message"]
    db.expire_all()
    run = db.scalars(select(JobRun).where(JobRun.job == "usage_sync")).one()
    assert run.status == "error" and "ValueError" in run.message
    [alert] = open_alerts(db, "job_failed")
    assert alert.severity == "critical" and "kaboom" in alert.message


def test_a_job_already_running_elsewhere_is_skipped(db, monkeypatch):
    monkeypatch.setattr(JobLock, "acquire", lambda self: False)
    result = asyncio.run(run_job("usage_sync", "test"))
    assert result["status"] == "skipped"
    db.expire_all()
    assert db.scalars(select(JobRun)).one().status == "skipped"


def test_every_job_has_a_valid_schedule():
    from apscheduler.triggers.cron import CronTrigger

    assert set(JOBS) >= {"usage_sync", "daily_health"}
    for spec in JOBS.values():
        CronTrigger(**spec.cron, timezone="UTC")  # raises if the schedule is invalid
        assert spec.title and spec.description and spec.schedule


def test_the_scheduler_registers_every_job(monkeypatch):
    from app import scheduler
    from app.config import settings

    monkeypatch.setattr(type(settings), "scheduler_enabled", True, raising=False) if False else None
    object.__setattr__(settings, "scheduler_enabled", True)

    async def go():
        scheduler.start()
        try:
            return {job.id for job in scheduler._scheduler.get_jobs()}
        finally:
            scheduler.stop()
            object.__setattr__(settings, "scheduler_enabled", False)

    assert asyncio.run(go()) == set(JOBS)


# ------------------------------------------------------------------ admin API: alerts, jobs, settings


def test_alerts_api_lists_and_resolves(api, db, world):
    raise_alert(db, kind="no_events", dedupe_key="x", message="Quiet", website_id=world.site_a.id, client_id=world.client_a.id)
    admin = api("admin@agency.test")
    body = admin.get("/api/admin/alerts").json()
    assert body["open_count"] == 1
    assert body["results"][0]["website_name"] == "Client A site" and body["results"][0]["client_name"] == "Client A"
    assert admin.post(f"/api/admin/alerts/{body['results'][0]['id']}/resolve").status_code == 200
    assert admin.get("/api/admin/alerts").json()["results"] == []
    assert len(admin.get("/api/admin/alerts", params={"status": "resolved"}).json()["results"]) == 1
    assert admin.get("/api/admin/alerts", params={"status": "bogus"}).status_code == 422
    assert admin.post("/api/admin/alerts/00000000-0000-0000-0000-000000000000/resolve").status_code == 404


def test_jobs_api_shows_the_jobs_and_runs_them(api, db, world, fake_posthog):
    admin = api("admin@agency.test")
    jobs = {j["name"]: j for j in admin.get("/api/admin/jobs").json()["results"]}
    assert set(jobs) >= {"usage_sync", "daily_health"} and jobs["usage_sync"]["last_run"] is None

    assert admin.post("/api/admin/jobs/usage_sync/run").status_code == 202
    for _ in range(40):  # it runs in the background
        last = {j["name"]: j for j in admin.get("/api/admin/jobs").json()["results"]}["usage_sync"]["last_run"]
        if last and last["status"] != "running":
            break
        time.sleep(0.25)
    assert last["status"] == "ok" and last["triggered_by"] == "admin"
    assert admin.post("/api/admin/jobs/nonexistent/run").status_code == 404


def test_a_job_that_is_already_running_cannot_be_started_again(api, db, world):
    db.add(JobRun(job="usage_sync", status="running"))
    db.commit()
    assert api("admin@agency.test").post("/api/admin/jobs/usage_sync/run").status_code == 409


def test_settings_api(api, db, world):
    admin = api("admin@agency.test")
    listing = {s["key"]: s for s in admin.get("/api/admin/settings").json()["results"]}
    assert listing["alerts.no_events_hours"]["value"] == 48 and listing["alerts.no_events_hours"]["default"] == 48

    assert admin.patch("/api/admin/settings", json={"values": {"alerts.no_events_hours": 72, "usage.warn_percent": 90}}).json()["changed"] == ["alerts.no_events_hours", "usage.warn_percent"]
    assert {s["key"]: s["value"] for s in admin.get("/api/admin/settings").json()["results"]}["alerts.no_events_hours"] == 72

    # Putting the default back removes the stored row.
    admin.patch("/api/admin/settings", json={"values": {"alerts.no_events_hours": 48}})
    db.expire_all()
    assert db.get(AppSetting, "alerts.no_events_hours") is None

    for bad in ({"alerts.no_events_hours": 1}, {"alerts.no_events_hours": "soon"}, {"alerts.no_events_hours": True}, {"nope": 1}, {"usage.warn_percent": 500}):
        response = admin.patch("/api/admin/settings", json={"values": bad})
        assert response.status_code == 400, bad
    # All or nothing: one bad value means nothing is saved.
    admin.patch("/api/admin/settings", json={"values": {"usage.warn_percent": 60, "alerts.no_events_hours": 1}})
    assert {s["key"]: s["value"] for s in admin.get("/api/admin/settings").json()["results"]}["usage.warn_percent"] == 90


def test_changes_to_settings_are_audited(api, db, world):
    from app.models import AuditLog

    api("admin@agency.test").patch("/api/admin/settings", json={"values": {"usage.warn_percent": 70}})
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "admin.settings_changed")).one()
    assert entry.details == {"settings": ["usage.warn_percent"]}


def test_overview_counts_open_alerts(api, db, world):
    raise_alert(db, kind="x", dedupe_key="o1", message="m")
    assert api("admin@agency.test").get("/api/admin/overview").json()["open_alerts"] == 1
