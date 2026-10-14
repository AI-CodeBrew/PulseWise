"""Sales as clients see them: revenue, orders and best sellers next to the website's traffic. (Data comes from Shopify.)"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.config import WebsiteConfig
from app.deps import DbSession, require_feature
from app.models import Client, Website
from app.params import CursorParam, DaysParam, LimitParam
from app.posthog_client import PostHogClient
from app.shopify.sales import order_page, sales_summary

router = APIRouter(prefix="/api/websites/{website_id}/sales", tags=["sales"])

# The Sales pages need the plan to include "shopify" (admins always pass).
SalesAccess = Annotated[WebsiteConfig, Depends(require_feature("shopify"))]


@router.get("", summary="Revenue, orders, average order, conversion and best sellers")
async def get_sales(site: SalesAccess, db: DbSession, days: DaysParam = 30):
    website = db.get(Website, uuid.UUID(site.website_id))
    client = db.get(Client, website.client_id)
    return await sales_summary(db, PostHogClient(site), website.id, client, days)


@router.get("/orders", summary="The store's orders, newest first")
def get_orders(site: SalesAccess, db: DbSession, limit: LimitParam = 25, cursor: CursorParam = None):
    try:
        return order_page(db, uuid.UUID(site.website_id), limit, cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
