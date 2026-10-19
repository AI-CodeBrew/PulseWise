"""
"My dashboard" on the Overview page: the tiles a person chose, and their numbers.

  GET  /dashboard/tiles/catalog   everything that can be chosen (built-in tiles + this website's tracked events)
  GET  /dashboard/tiles           the person's chosen tiles WITH their numbers ("configured: false" = never chose: ask first)
  PUT  /dashboard/prefs           save the choice (one list of tile keys)

The choice belongs to one user on one website. The access check is the same as for every website endpoint.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import WebsiteConfig
from app.deps import CurrentUser, DbSession, get_website_config
from app.models import DashboardPref
from app.posthog_client import PostHogClient
from app.services import tiles

router = APIRouter(prefix="/api/websites/{website_id}/dashboard", tags=["dashboard"])

Site = Annotated[WebsiteConfig, Depends(get_website_config)]


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
    # (A saved key that no longer makes sense, e.g. after a code change, is skipped instead of breaking the page.)
    keys = [k for k in keys if k in tiles.BUILTIN_BY_KEY or tiles.parse_event_key(k)]
    return {"configured": True, "tiles": await tiles.get_values(PostHogClient(site), keys) if keys else []}


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
