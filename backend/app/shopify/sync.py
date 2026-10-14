"""
Copying a store's orders into our database, so the dashboard can show sales next to the website traffic.

How it works (kept simple on purpose):
  * Every sync asks Shopify for the orders CHANGED since the last sync (with a small overlap, so nothing is missed).
    The first sync reads the last 60 days: that is all Shopify allows without the special `read_all_orders` scope.
  * Every order is saved by its Shopify id, so syncing the same order again just updates it (never a duplicate).
  * No customer details are stored: only dates, money, status and the products bought.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import raise_alert, resolve_alerts
from app.db import get_sessionmaker
from app.models import ShopConnection, ShopOrder, ShopOrderItem, Website, utcnow
from app.security import decrypt_secret
from app.settings_store import get_setting
from app.shopify.client import ShopifyClient, ShopifyError, TooManyPages

log = logging.getLogger(__name__)

HISTORY_DAYS = 60  # what the first sync reads (Shopify's default limit without read_all_orders)
OVERLAP = timedelta(minutes=15)  # re-read a little before the last sync, in case an order changed while we were reading


def credentials_of(connection: ShopConnection) -> dict[str, str]:
    return json.loads(decrypt_secret(connection.credentials_encrypted))


def build_client(db: Session, connection: ShopConnection) -> ShopifyClient:
    return ShopifyClient(connection.shop_domain, connection.auth_mode, credentials_of(connection), str(get_setting(db, "shopify.api_version")))


def save_orders(website_id: uuid.UUID, orders: list[dict[str, Any]]) -> int:
    """Insert new orders and update known ones (with their products). Returns how many were written."""
    if not orders:
        return 0
    with get_sessionmaker()() as db:
        existing = {
            o.shopify_id: o
            for o in db.scalars(select(ShopOrder).where(ShopOrder.website_id == website_id, ShopOrder.shopify_id.in_([o["shopify_id"] for o in orders])))
        }
        for data in orders:
            order = existing.get(data["shopify_id"])
            if order is None:
                order = ShopOrder(website_id=website_id, shopify_id=data["shopify_id"], created_at=data["created_at"], name="", currency="", total=0)
                db.add(order)
            order.name, order.created_at, order.cancelled_at = data["name"], data["created_at"], data["cancelled_at"]
            order.financial_status, order.fulfillment_status = data["financial_status"], data["fulfillment_status"]
            order.currency, order.total, order.refunded = data["currency"], data["total"], data["refunded"]
            order.is_test, order.source_name, order.synced_at = data["is_test"], data["source_name"], utcnow()
            order.items = [ShopOrderItem(website_id=website_id, **item) for item in data["items"]]
        db.commit()
    return len(orders)


def _plan(website_id: uuid.UUID) -> tuple[ShopifyClient, datetime, str, uuid.UUID, ShopConnection] | None:
    with get_sessionmaker()() as db:
        connection = db.scalar(select(ShopConnection).where(ShopConnection.website_id == website_id))
        website = db.get(Website, website_id)
        if connection is None or website is None:
            return None
        since = connection.last_synced_at - OVERLAP if connection.last_synced_at else utcnow() - timedelta(days=HISTORY_DAYS)
        client = build_client(db, connection)
        db.expunge(connection)
        return client, since, website.name, website.client_id, connection


def _finish(website_id: uuid.UUID, *, watermark: datetime | None, currency: str | None, error: str | None, name: str, client_id: uuid.UUID) -> None:
    with get_sessionmaker()() as db:
        connection = db.scalar(select(ShopConnection).where(ShopConnection.website_id == website_id))
        if connection is None:
            return
        connection.last_error = error
        if error is None and watermark is not None:
            connection.last_synced_at = watermark
            connection.currency = currency or connection.currency
        db.commit()
        if error is None:
            resolve_alerts(db, dedupe_key=f"shopify:{website_id}")
        else:
            raise_alert(db, kind="shopify_sync", dedupe_key=f"shopify:{website_id}", severity="warning", website_id=website_id, client_id=client_id,
                        message=f"The Shopify order sync for {name} is failing: {error}")


async def sync_website(website_id: uuid.UUID) -> dict[str, Any]:
    """Sync one website's store. Returns {"orders": n}. Raises ShopifyError if Shopify refuses (and records why)."""
    plan = await asyncio.to_thread(_plan, website_id)
    if plan is None:
        raise ShopifyError("This website has no Shopify store connected.")
    client, since, name, client_id, connection = plan
    started = utcnow()
    saved, currency, newest = 0, None, None
    watermark = started
    try:
        async for page in client.iter_orders(since):
            saved += await asyncio.to_thread(save_orders, website_id, page)
            for order in page:
                currency = order["currency"] or currency
                if order["updated_at"] and (newest is None or order["updated_at"] > newest):
                    newest = order["updated_at"]
    except TooManyPages:
        watermark = newest or since  # big store: continue from where we got to at the next sync
    except ShopifyError as exc:
        await asyncio.to_thread(_finish, website_id, watermark=None, currency=None, error=str(exc), name=name, client_id=client_id)
        raise
    await asyncio.to_thread(_finish, website_id, watermark=watermark, currency=currency, error=None, name=name, client_id=client_id)
    return {"orders": saved}
