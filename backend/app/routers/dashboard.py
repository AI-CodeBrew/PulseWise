"""
"My dashboard" (the Dashboard page): the tiles a person chose, their numbers, and the box behind each tile.

  GET  /dashboard/tiles/catalog   everything that can be chosen (built-in tiles + this website's tracked events)
  GET  /dashboard/tiles           the person's chosen tiles WITH their numbers ("configured: false" = never chose: ask first)
  PUT  /dashboard/prefs           save the choice (one list of tile keys)
  GET  /dashboard/tiles/detail    the trend and breakdowns behind ONE tile (the box that opens when a tile is clicked)
  GET  /dashboard/tiles/recent    the latest visits / events behind it, and which of them can be watched as a recording

The choice belongs to one user on one website. The access check is the same as for every website endpoint.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.billing.service import FEATURES, has_feature
from app.config import WebsiteConfig
from app.deps import CurrentUser, DbSession, get_website_config
from app.models import DashboardPref
from app.posthog_client import PostHogClient
from app.services import tile_details, tiles

router = APIRouter(prefix="/api/websites/{website_id}/dashboard", tags=["dashboard"])

Site = Annotated[WebsiteConfig, Depends(get_website_config)]
TileKey = Annotated[str, Query(min_length=1, max_length=140, description="A tile key with its period: sessions_7d, sessions_30d... or event:<name>:<7 or 30>")]


def _checked(key: str) -> str:
    try:
        return tiles.validate_keys([key])[0]
    except tiles.TileKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _lock(site: WebsiteConfig, db, feature: str) -> str | None:
    """The message to show when the client's plan doesn't include `feature` (admins always have everything)."""
    if site.role == "admin" or has_feature(db, uuid.UUID(site.client_id), feature):
        return None
    return f"Your plan doesn't include {FEATURES[feature]}. Please contact support to upgrade."


class PrefsIn(BaseModel):
    tiles: list[str] = Field(max_length=100)  # tile keys, in the order to show them (may be empty: "show nothing")


def _saved(db, user_id: uuid.UUID, website_id: str) -> list[str] | None:
    row = db.get(DashboardPref, (user_id, uuid.UUID(website_id)))
    return None if row is None else list(row.tiles or [])


@router.get("/tiles/catalog", summary="Everything that can be put on the dashboard")
async def get_catalog(site: Site):
    return await tiles.get_catalog(PostHogClient(site))


@router.get("/tiles", summary="The tiles this person chose, with their numbers")
async def get_tiles(site: Site, user: CurrentUser, db: DbSession):
    keys = _saved(db, user.id, site.website_id)
    if keys is None:  # never chose: the page shows the chooser, and no analytics queries are spent
        return {"configured": False, "tiles": []}
    # (A saved key that no longer makes sense is skipped instead of breaking the page, and a tile saved once per period,
    # as older versions did, is shown once.)
    keys = tiles.usable_keys(keys)
    return {"configured": True, "tiles": await tiles.get_values(PostHogClient(site), keys) if keys else []}


@router.get("/tiles/detail", summary="The trend and breakdowns behind one tile")
async def get_tile_detail(site: Site, key: TileKey):
    return await tile_details.get_detail(PostHogClient(site), _checked(key))


@router.get("/tiles/recent", summary="The latest visits or events behind one tile, and which can be watched")
async def get_tile_recent(site: Site, db: DbSession, key: TileKey):
    locks = {"sessions": _lock(site, db, "sessions"), "events": _lock(site, db, "live_events"), "recordings": _lock(site, db, "recordings")}
    return await tile_details.get_recent(PostHogClient(site), _checked(key), locks=locks)


@router.put("/prefs", summary="Save which tiles this person wants")
def save_prefs(body: PrefsIn, site: Site, user: CurrentUser, db: DbSession):
    try:
        keys = tiles.validate_keys(body.tiles)
    except tiles.TileKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    website_id = uuid.UUID(site.website_id)
    row = db.get(DashboardPref, (user.id, website_id))
    if row is None:
        db.add(DashboardPref(user_id=user.id, website_id=website_id, tiles=keys))
    else:
        row.tiles = keys
    db.commit()
    return {"configured": True, "keys": keys}
