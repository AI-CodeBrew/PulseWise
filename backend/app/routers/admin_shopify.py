"""
Admin API, Shopify: connect a website to its Shopify store, test it, sync it, disconnect it.
The WHOLE router requires an admin. Credentials are encrypted and never sent back.
"""

import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select

from app.audit import audit
from app.deps import AdminUser, DbSession, client_ip, require_admin
from app.models import ShopConnection, ShopOrder, Website
from app.security import encrypt_secret
from app.settings_store import get_setting
from app.shopify.client import ShopifyClient, ShopifyError, clean_shop_domain
from app.shopify.sync import sync_website

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/websites/{website_id}/shopify", tags=["admin"], dependencies=[Depends(require_admin)])


class ConnectIn(BaseModel):
    shop_domain: str = Field(min_length=3, max_length=255)
    access_token: str | None = Field(default=None, min_length=8, max_length=500)  # a ready-made Admin API token
    client_id: str | None = Field(default=None, min_length=4, max_length=200)  # ...or a Dev Dashboard app's id and secret
    client_secret: str | None = Field(default=None, min_length=4, max_length=500)

    @model_validator(mode="after")
    def one_way_to_log_in(self):
        has_token, has_pair = bool(self.access_token), bool(self.client_id and self.client_secret)
        if has_token == has_pair:  # both, or neither
            raise ValueError("Give either an access token, or a Client ID and Client secret (not both).")
        return self


def _website(db, website_id: uuid.UUID) -> Website:
    website = db.get(Website, website_id)
    if website is None:
        raise HTTPException(status_code=404, detail="Website not found.")
    return website


def _info(db, website_id: uuid.UUID) -> dict:
    connection = db.scalar(select(ShopConnection).where(ShopConnection.website_id == website_id))
    if connection is None:
        return {"connected": False}
    return {
        "connected": True,
        "shop_domain": connection.shop_domain,
        "shop_name": connection.shop_name,
        "currency": connection.currency,
        "auth_mode": connection.auth_mode,
        "api_version": str(get_setting(db, "shopify.api_version")),
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        "last_error": connection.last_error,
        "orders_stored": db.scalar(select(func.count()).select_from(ShopOrder).where(ShopOrder.website_id == website_id)) or 0,
    }


@router.get("", summary="Is this website connected to a Shopify store?")
def get_connection(website_id: uuid.UUID, db: DbSession):
    _website(db, website_id)
    return _info(db, website_id)


async def _first_sync(website_id: uuid.UUID) -> None:
    try:
        await sync_website(website_id)
    except ShopifyError:
        pass  # saved on the connection (and raised as an alert) by the sync itself


@router.put("", summary="Connect (or reconnect) a Shopify store. The login is tested first.")
async def connect(website_id: uuid.UUID, body: ConnectIn, request: Request, background: BackgroundTasks, admin: AdminUser, db: DbSession):
    _website(db, website_id)
    try:
        domain = clean_shop_domain(body.shop_domain)
        credentials = {"access_token": body.access_token} if body.access_token else {"client_id": body.client_id, "client_secret": body.client_secret}
        mode = "token" if body.access_token else "client_credentials"
        shop = await ShopifyClient(domain, mode, credentials, str(get_setting(db, "shopify.api_version"))).shop_info()
    except ShopifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None  # admin-only text: fine to be specific

    connection = db.scalar(select(ShopConnection).where(ShopConnection.website_id == website_id))
    if connection is None:
        connection = ShopConnection(website_id=website_id, shop_domain=domain, auth_mode=mode, credentials_encrypted="")
        db.add(connection)
    elif connection.shop_domain != domain:  # a different store: the old orders must not stay mixed in
        db.execute(delete(ShopOrder).where(ShopOrder.website_id == website_id))
        connection.last_synced_at = None
    connection.shop_domain, connection.auth_mode = domain, mode
    connection.credentials_encrypted = encrypt_secret(json.dumps(credentials))
    connection.shop_name, connection.currency, connection.last_error = shop["name"], shop["currency"] or connection.currency, None
    audit(db, "admin.shopify_connected", actor_id=admin.id, target_type="website", target_id=website_id, ip=client_ip(request), details={"shop": domain, "mode": mode})
    db.commit()
    background.add_task(_first_sync, website_id)  # read the last 60 days of orders without making the admin wait
    return _info(db, website_id)


@router.post("/sync", summary="Read new orders from the store right now")
async def sync_now(website_id: uuid.UUID, db: DbSession):
    _website(db, website_id)
    try:
        result = await sync_website(website_id)
    except ShopifyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    db.expire_all()
    return {**result, **_info(db, website_id)}


@router.delete("", summary="Disconnect the store and delete its copied orders")
def disconnect(website_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession):
    _website(db, website_id)
    connection = db.scalar(select(ShopConnection).where(ShopConnection.website_id == website_id))
    if connection is None:
        raise HTTPException(status_code=404, detail="No Shopify store is connected.")
    db.execute(delete(ShopOrder).where(ShopOrder.website_id == website_id))  # items go with them (cascade)
    db.delete(connection)
    audit(db, "admin.shopify_disconnected", actor_id=admin.id, target_type="website", target_id=website_id, ip=client_ip(request))
    db.commit()
    return {"connected": False}
