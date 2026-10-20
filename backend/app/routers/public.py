"""
Open endpoints for the public landing page (no login needed). They return only what may be shown to anybody.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.billing.summary import plans_for_sale, support_info
from app.deps import DbSession

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/plans", summary="The plans for sale, for the pricing part of the landing page (no login needed)")
def public_plans(db: DbSession, currency: Annotated[Literal["USD", "PKR"], Query()] = "USD"):
    # support: the WhatsApp / email from Admin -> Settings, so a visitor can ask for a plan.
    return {"currency": currency, "plans": plans_for_sale(db, currency), "support": support_info(db)}
