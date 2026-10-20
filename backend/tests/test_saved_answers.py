"""Saved answers: dashboard pages open at once, from the database (app/saved_answers.py, app/posthog_client.py)."""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.cache import cache
from app.config import settings
from app.jobs import run_job
from app.models import AnalyticsCache


@pytest.fixture
def saving():
    """Switch the database copy on (the other tests keep answers in memory only)."""
    object.__setattr__(settings, "saved_answers", True)
    yield
    object.__setattr__(settings, "saved_answers", False)


def overview_url(world) -> str:
    return f"/api/websites/{world.site_a.id}/overview"


def test_an_answer_is_saved_and_then_served_from_the_database(api, db, world, fake_posthog, saving):
    alice = api("alice@a.test")
    first = alice.get(overview_url(world))
    assert first.status_code == 200
    asked = len(fake_posthog.calls)
    assert asked > 0
    assert {row.website_id for row in db.scalars(select(AnalyticsCache))} == {world.site_a.id}

    cache.clear()  # like a server restart: the memory is gone, the database is not
    second = alice.get(overview_url(world))
    assert second.json() == first.json()
    assert len(fake_posthog.calls) == asked  # nothing was asked again


def test_an_old_answer_is_shown_at_once_and_refreshed_in_the_background(api, db, world, fake_posthog, saving):
    alice = api("alice@a.test")
    alice.get(overview_url(world))
    asked = len(fake_posthog.calls)
    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    for row in db.scalars(select(AnalyticsCache)):
        row.refreshed_at = ten_minutes_ago
    db.commit()
    cache.clear()

    assert alice.get(overview_url(world)).status_code == 200  # answered from the database...
    deadline = time.monotonic() + 5
    while len(fake_posthog.calls) < 2 * asked and time.monotonic() < deadline:  # ...while the fresh one is fetched
        time.sleep(0.05)
    assert len(fake_posthog.calls) == 2 * asked
    time.sleep(0.2)  # (the save happens right after the answer arrives)
    db.expire_all()
    assert all(row.refreshed_at.replace(tzinfo=timezone.utc) > ten_minutes_ago for row in db.scalars(select(AnalyticsCache)))


def test_a_very_old_answer_is_not_shown(api, db, world, fake_posthog, saving):
    alice = api("alice@a.test")
    alice.get(overview_url(world))
    asked = len(fake_posthog.calls)
    for row in db.scalars(select(AnalyticsCache)):
        row.refreshed_at = datetime.now(timezone.utc) - timedelta(days=8)
    db.commit()
    cache.clear()
    assert alice.get(overview_url(world)).status_code == 200
    assert len(fake_posthog.calls) == 2 * asked  # asked again while the visitor waited


def test_live_events_are_never_saved(api, db, world, saving):
    assert api("alice@a.test").get(f"/api/websites/{world.site_a.id}/events/live").status_code == 200
    assert db.scalars(select(AnalyticsCache)).all() == []


def test_the_refresh_job_saves_the_main_pages_of_every_website(db, world, fake_posthog, saving):
    result = asyncio.run(run_job("analytics_refresh", "test"))
    assert result["status"] == "ok" and result["message"] == "Refreshed 2 of 2 websites."
    assert {row.website_id for row in db.scalars(select(AnalyticsCache))} == {world.site_a.id, world.site_b.id}
    # each website was asked with its own key, never another one's
    assert {(call["project_id"], call["api_key"]) for call in fake_posthog.calls} == {(7350981, "phx_secret_key_of_A"), (8462092, "phx_secret_key_of_B")}
