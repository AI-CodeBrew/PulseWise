"""
The analytics endpoints: URL -> check access -> validate input -> call a service -> JSON.

Every URL starts with /api/websites/{website_id}/. Before any endpoint runs,
`get_ph` -> deps.get_website_config() checks that the logged-in user may see that
website (404 if not), and builds a PostHog client for THAT website only.

No analytics logic lives here; that is in app/services/.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.config import WebsiteConfig
from app.deps import get_website_config, require_feature
from app.params import (
    CursorParam,
    DaysParam,
    LimitParam,
    PersonIdPath,
    RecordingIdPath,
    SessionIdPath,
)
from app.posthog_client import PostHogClient
from app.services import (
    devices,
    events,
    geo,
    overview,
    pages,
    persons,
    recordings,
    sessions,
    sources,
    trends,
)

router = APIRouter(prefix="/api/websites/{website_id}", tags=["analytics"])


def get_ph(website: Annotated[WebsiteConfig, Depends(get_website_config)]) -> PostHogClient:
    """A PostHog client for the website in the URL (only after the access check passed)."""
    return PostHogClient(website)


PH = Annotated[PostHogClient, Depends(get_ph)]


def _ph_with(feature: str):
    """Like get_ph, but the client's plan must include `feature` (e.g. "recordings")."""

    def dependency(website: Annotated[WebsiteConfig, Depends(require_feature(feature))]) -> PostHogClient:
        return PostHogClient(website)

    return dependency


# Parts of the dashboard that a plan can switch off:
PH_SESSIONS = Annotated[PostHogClient, Depends(_ph_with("sessions"))]
PH_PEOPLE = Annotated[PostHogClient, Depends(_ph_with("people"))]
PH_LIVE = Annotated[PostHogClient, Depends(_ph_with("live_events"))]
PH_RECORDINGS = Annotated[PostHogClient, Depends(_ph_with("recordings"))]


@router.get("/overview", summary="KPI cards with previous-period comparison")
async def get_overview(ph: PH, days: DaysParam = 30):
    return await overview.get_overview(ph, days)


@router.get("/trends", summary="Daily pageviews and unique visitors")
async def get_trends(ph: PH, days: DaysParam = 30):
    return await trends.get_trends(ph, days)


@router.get("/top-pages", summary="Top pages by views and unique visitors")
async def get_top_pages(ph: PH, days: DaysParam = 30, limit: LimitParam = 50):
    return await pages.get_top_pages(ph, days, limit)


@router.get("/sources", summary="Referrers, UTM sources and channels")
async def get_sources(ph: PH, days: DaysParam = 30):
    return await sources.get_sources(ph, days)


@router.get("/geo", summary="Countries and cities")
async def get_geo(ph: PH, days: DaysParam = 30):
    return await geo.get_geo(ph, days)


@router.get("/devices", summary="Device types, browsers and operating systems")
async def get_devices(ph: PH, days: DaysParam = 30):
    return await devices.get_devices(ph, days)


@router.get("/sessions", summary="Recent sessions (paginated)")
async def list_sessions(ph: PH_SESSIONS, days: DaysParam = 30, limit: LimitParam = 25, cursor: CursorParam = None):
    return await sessions.list_sessions(ph, days, limit, cursor)


@router.get("/sessions/{session_id}", summary="All events of one session, in time order")
async def get_session(ph: PH_SESSIONS, session_id: SessionIdPath):
    return await sessions.get_session(ph, session_id)


@router.get("/persons", summary="People seen in the period (paginated)")
async def list_persons(ph: PH_PEOPLE, days: DaysParam = 30, limit: LimitParam = 25, cursor: CursorParam = None):
    return await persons.list_persons(ph, days, limit, cursor)


@router.get("/persons/{person_id}", summary="One person: properties and recent events")
async def get_person(ph: PH_PEOPLE, person_id: PersonIdPath):
    return await persons.get_person(ph, person_id)


@router.get("/events/live", summary="Latest 50 events")
async def live_events(ph: PH_LIVE):
    return await events.get_live_events(ph)


@router.get("/events/custom", summary="Custom (non-$) event names with counts")
async def custom_events(ph: PH_LIVE, days: DaysParam = 30):
    return await events.get_custom_events(ph, days)


@router.get("/recordings", summary="Session recordings (paginated list)")
async def list_recordings(ph: PH_RECORDINGS, days: DaysParam = 30, limit: LimitParam = 25, cursor: CursorParam = None):
    return await recordings.list_recordings(ph, days, limit, cursor)


@router.get("/recordings/{recording_id}", summary="One recording: details and the blocks to load")
async def get_recording(ph: PH_RECORDINGS, recording_id: RecordingIdPath):
    return await recordings.get_recording(ph, recording_id)


@router.get("/recordings/{recording_id}/events", summary="The replay events of some blocks")
async def get_recording_events(
    ph: PH_RECORDINGS,
    recording_id: RecordingIdPath,
    start: Annotated[int, Query(ge=0, le=100_000, description="first block")],
    end: Annotated[int, Query(ge=0, le=100_000, description="last block (at most 4 blocks per request)")],
):
    return await recordings.get_recording_events(ph, recording_id, start, end)
