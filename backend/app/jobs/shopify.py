"""Job: copy new and changed Shopify orders into our database, for every connected store."""

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.billing.service import has_feature
from app.db import get_sessionmaker
from app.jobs.registry import job
from app.models import Client, ShopConnection, Website
from app.shopify.client import ShopifyError
from app.shopify.sync import sync_website

log = logging.getLogger(__name__)


def _connected_websites() -> list[uuid.UUID]:
    """Stores worth syncing: the website is active, the client isn't suspended and their plan includes Shopify sales."""
    with get_sessionmaker()() as db:
        rows = db.execute(
            select(Website.id, Client.id)
            .join(ShopConnection, ShopConnection.website_id == Website.id)
            .join(Client, Client.id == Website.client_id)
            .where(Website.is_active.is_(True), Client.status == "active")
            .order_by(Website.name)
        ).all()
        return [website_id for website_id, client_id in rows if has_feature(db, client_id, "shopify")]


@job(
    "shopify_sync",
    title="Shopify orders",
    description="Copies new and changed orders from every connected Shopify store, so the Sales page stays up to date. Safe to run any time: orders are saved by their Shopify id, never twice.",
    schedule="Every hour, at 35 past",
    cron={"minute": 35},
)
async def shopify_sync() -> dict[str, Any]:
    websites = await asyncio.to_thread(_connected_websites)
    synced, orders, failed = 0, 0, []
    for website_id in websites:  # one store at a time: kind to Shopify's rate limits
        try:
            orders += (await sync_website(website_id))["orders"]
            synced += 1
        except ShopifyError as exc:  # already saved on the connection and raised as an alert
            failed.append(f"{website_id}: {exc}")
    message = f"Synced {synced} of {len(websites)} stores ({orders} orders read)."
    if failed:
        message += " Failed: " + "; ".join(failed[:3])
    if websites and not synced:
        raise RuntimeError(message)
    return {"message": message, "stores": len(websites), "orders": orders, "failed": failed}
