"""Job: keep the most-used dashboard pages fresh in the database, so they open at once even for the first visitor."""

import asyncio
import logging

from sqlalchemy import select

from app.config import WebsiteConfig
from app.db import get_sessionmaker
from app.deps import config_from_website
from app.jobs.registry import job
from app.models import Website
from app.posthog_client import PostHogClient
from app.services import devices, geo, overview, pages, sources, trends

log = logging.getLogger(__name__)

DAYS = 30  # the period a page opens with (the frontend's default)


def _load_sites() -> list[WebsiteConfig]:
    sites = []
    with get_sessionmaker()() as db:
        for website in db.scalars(select(Website).where(Website.is_active.is_(True)).order_by(Website.name)):
            try:
                sites.append(config_from_website(website))
            except RuntimeError:
                log.error("Skipping website %s: its API key can't be decrypted", website.id)
    return sites


async def refresh_website(config: WebsiteConfig) -> None:
    """Ask exactly what the Overview, Audience and Pages pages ask (same values, so the same saved answers)."""
    ph = PostHogClient(config, refresh=True)
    await overview.get_overview(ph, DAYS)
    await trends.get_trends(ph, DAYS)
    await pages.get_top_pages(ph, DAYS, 5)  # Overview page
    await pages.get_top_pages(ph, DAYS, 100)  # Pages page
    await sources.get_sources(ph, DAYS)
    await geo.get_geo(ph, DAYS)
    await devices.get_devices(ph, DAYS)


@job(
    "analytics_refresh",
    title="Keep dashboards fresh",
    description="Fetches each website's main numbers, charts and lists and saves them, so dashboard pages open at once.",
    schedule="Every 20 minutes",
    cron={"minute": "*/20"},
)
async def analytics_refresh() -> dict:
    sites = await asyncio.to_thread(_load_sites)
    failed = []
    for config in sites:
        try:
            await refresh_website(config)
        except Exception as exc:  # noqa: BLE001 - one broken website must not stop the others
            log.warning("Refreshing %s failed: %r", config.name, exc)
            failed.append(config.name)
    done = len(sites) - len(failed)
    message = f"Refreshed {done} of {len(sites)} websites." + (f" Failed: {', '.join(failed)}." if failed else "")
    return {"message": message, "websites": len(sites), "failed": failed}
