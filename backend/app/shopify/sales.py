"""
The sales numbers: what the store sold, put next to what the website's traffic did.

Rules (so the numbers can be trusted and explained):
  * Revenue = the current total of each order (after edits and refunds), in the shop's own currency.
  * Test orders and cancelled orders are never counted.
  * A "day" is the client's own day (their time zone setting).
  * Conversion = online-store orders ÷ website sessions. (Orders from other channels, such as a shop till or
    a draft order, are in revenue but not in conversion, because they didn't come through the website.)
"""

import base64
import binascii
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Client, ShopConnection, ShopOrder, ShopOrderItem
from app.posthog_client import AnalyticsError, PostHogClient
from app.reports.service import client_zone
from app.services.common import change_pct

ONLINE_STORE = "web"  # Shopify's `sourceName` for orders placed on the online store

# Sessions per day (real website visits only), for both the period and the one before it.
SESSIONS_QUERY = """
SELECT toString(toDate($start_timestamp)) AS day, count() AS sessions
FROM sessions
WHERE $start_timestamp >= toStartOfDay(now()) - toIntervalDay(2 * {days} - 1)
  AND $pageview_count > 0
GROUP BY day
ORDER BY day
"""


def _money(value: Decimal | float | int | None) -> float:
    return float(round(Decimal(value or 0), 2))


def windows(zone: ZoneInfo, days: int, today: date | None = None) -> tuple[date, date, date]:
    """(previous start, current start, last day) in the client's time zone. The period is `days` days ending today."""
    today = today or datetime.now(zone).date()
    start = today - timedelta(days=days - 1)
    return start - timedelta(days=days), start, today


def _bounds(zone: ZoneInfo, first: date, last: date) -> tuple[datetime, datetime]:
    return datetime.combine(first, time.min, zone), datetime.combine(last + timedelta(days=1), time.min, zone)


def counted(query):
    """Only orders that count as sales."""
    return query.where(ShopOrder.is_test.is_(False), ShopOrder.cancelled_at.is_(None))


def connection_info(db: Session, website_id) -> dict[str, Any] | None:
    connection = db.scalar(select(ShopConnection).where(ShopConnection.website_id == website_id))
    if connection is None:
        return None
    return {
        "shop_name": connection.shop_name or connection.shop_domain,
        "currency": connection.currency,
        "last_synced_at": connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        "sync_failing": connection.last_error is not None,  # the reason itself is for admins only
    }


def period_numbers(db: Session, website_id, zone: ZoneInfo, first: date, last: date) -> dict[str, Any]:
    """Orders, revenue, refunds, units and online-store orders between two days (both included)."""
    begin, end = _bounds(zone, first, last)
    rows = db.execute(
        counted(select(ShopOrder.total, ShopOrder.refunded, ShopOrder.source_name, ShopOrder.currency).where(
            ShopOrder.website_id == website_id, ShopOrder.created_at >= begin, ShopOrder.created_at < end))
    ).all()
    revenue = sum((r.total for r in rows), Decimal("0"))
    units = db.scalar(
        counted(select(func.coalesce(func.sum(ShopOrderItem.quantity), 0)).join(ShopOrder, ShopOrder.id == ShopOrderItem.order_id).where(
            ShopOrder.website_id == website_id, ShopOrder.created_at >= begin, ShopOrder.created_at < end))
    )
    return {
        "orders": len(rows),
        "revenue": revenue,
        "refunded": sum((r.refunded for r in rows), Decimal("0")),
        "units": int(units or 0),
        "online_orders": sum(1 for r in rows if r.source_name == ONLINE_STORE),
    }


def _kpi(current: Decimal | int | float, previous: Decimal | int | float, digits: int = 2) -> dict[str, Any]:
    cur, prev = round(float(current), digits), round(float(previous), digits)
    return {"current": int(cur) if digits == 0 else cur, "previous": int(prev) if digits == 0 else prev, "change_pct": change_pct(cur, prev)}


def daily_series(db: Session, website_id, zone: ZoneInfo, first: date, last: date) -> list[dict[str, Any]]:
    begin, end = _bounds(zone, first, last)
    per_day: dict[date, list[Decimal]] = {}
    for created_at, total in db.execute(counted(select(ShopOrder.created_at, ShopOrder.total).where(
            ShopOrder.website_id == website_id, ShopOrder.created_at >= begin, ShopOrder.created_at < end))):
        local_day = (created_at if created_at.tzinfo else created_at.replace(tzinfo=ZoneInfo("UTC"))).astimezone(zone).date()
        per_day.setdefault(local_day, []).append(total)
    series = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        totals = per_day.get(day, [])
        series.append({"date": day.isoformat(), "orders": len(totals), "revenue": _money(sum(totals, Decimal("0")))})
    return series


def top_products(db: Session, website_id, zone: ZoneInfo, first: date, last: date, limit: int = 10) -> list[dict[str, Any]]:
    begin, end = _bounds(zone, first, last)
    revenue = func.sum(ShopOrderItem.amount)
    rows = db.execute(
        counted(select(ShopOrderItem.title, func.sum(ShopOrderItem.quantity), revenue).join(ShopOrder, ShopOrder.id == ShopOrderItem.order_id).where(
            ShopOrder.website_id == website_id, ShopOrder.created_at >= begin, ShopOrder.created_at < end))
        .group_by(ShopOrderItem.title).order_by(revenue.desc(), ShopOrderItem.title).limit(limit)
    ).all()
    return [{"title": title, "units": int(units or 0), "revenue": _money(amount)} for title, units, amount in rows]


async def _sessions_by_day(ph: PostHogClient, days: int) -> dict[str, int] | None:
    """Website sessions per day, or None when the analytics are unavailable (the sales numbers still work)."""
    try:
        rows = await ph.hogql(SESSIONS_QUERY, {"days": days}, name="sales:sessions")
    except AnalyticsError:
        return None
    return {str(r["day"]): int(r["sessions"] or 0) for r in rows}


async def sales_summary(db: Session, ph: PostHogClient, website_id, client: Client, days: int) -> dict[str, Any]:
    info = connection_info(db, website_id)
    if info is None:
        return {"connected": False}
    zone = client_zone(client)
    prev_first, first, last = windows(zone, days)
    now_n = period_numbers(db, website_id, zone, first, last)
    prev_n = period_numbers(db, website_id, zone, prev_first, first - timedelta(days=1))
    daily = daily_series(db, website_id, zone, first, last)

    sessions = await _sessions_by_day(ph, days)
    traffic = None
    if sessions is not None:
        cur_sessions = sum(v for k, v in sessions.items() if first.isoformat() <= k <= last.isoformat())
        prev_sessions = sum(v for k, v in sessions.items() if prev_first.isoformat() <= k < first.isoformat())
        for point in daily:
            point["sessions"] = sessions.get(point["date"], 0)
        traffic = {
            "sessions": _kpi(cur_sessions, prev_sessions, 0),
            "conversion_rate": _kpi(now_n["online_orders"] / cur_sessions * 100 if cur_sessions else 0, prev_n["online_orders"] / prev_sessions * 100 if prev_sessions else 0),
            "revenue_per_session": _kpi(now_n["revenue"] / cur_sessions if cur_sessions else 0, prev_n["revenue"] / prev_sessions if prev_sessions else 0),
        }

    def aov(n: dict[str, Any]) -> Decimal:
        return n["revenue"] / n["orders"] if n["orders"] else Decimal("0")

    return {
        "connected": True,
        **info,
        "period": {"start": first.isoformat(), "end": last.isoformat(), "days": days},
        "revenue": _kpi(now_n["revenue"], prev_n["revenue"]),
        "orders": _kpi(now_n["orders"], prev_n["orders"], 0),
        "average_order_value": _kpi(aov(now_n), aov(prev_n)),
        "units": _kpi(now_n["units"], prev_n["units"], 0),
        "refunded": _money(now_n["refunded"]),
        "traffic": traffic,
        "daily": daily,
        "top_products": top_products(db, website_id, zone, first, last),
    }


def week_sales(db: Session, website_id, client: Client, start: date, end: date) -> dict[str, Any] | None:
    """The sales block of a weekly report (no website traffic needed: the report already has it). None = no store."""
    info = connection_info(db, website_id)
    if info is None:
        return None
    zone = client_zone(client)
    span = (end - start).days + 1
    now_n = period_numbers(db, website_id, zone, start, end)
    prev_n = period_numbers(db, website_id, zone, start - timedelta(days=span), start - timedelta(days=1))
    products = top_products(db, website_id, zone, start, end, limit=1)
    return {
        "currency": info["currency"] or "",
        "orders": _kpi(now_n["orders"], prev_n["orders"], 0),
        "revenue": _kpi(now_n["revenue"], prev_n["revenue"]),
        "average_order_value": _kpi(now_n["revenue"] / now_n["orders"] if now_n["orders"] else 0, prev_n["revenue"] / prev_n["orders"] if prev_n["orders"] else 0),
        "top_product": products[0] if products else None,
    }


def order_page(db: Session, website_id, limit: int, cursor: str | None) -> dict[str, Any]:
    """Orders newest first, with a (time, id) cursor so orders placed in the same second are never skipped."""
    query = select(ShopOrder).where(ShopOrder.website_id == website_id)
    if cursor:
        try:
            stamp, _, order_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
            at, order_id = datetime.fromisoformat(stamp), uuid.UUID(order_id)
        except (ValueError, binascii.Error):
            raise ValueError("That page marker isn't valid.") from None
        query = query.where((ShopOrder.created_at < at) | ((ShopOrder.created_at == at) & (ShopOrder.id < order_id)))
    rows = db.scalars(query.order_by(ShopOrder.created_at.desc(), ShopOrder.id.desc()).limit(limit + 1)).all()
    page, more = rows[:limit], len(rows) > limit
    return {
        "results": [
            {
                "id": str(o.id), "name": o.name, "created_at": o.created_at.isoformat(), "total": _money(o.total), "currency": o.currency,
                "financial_status": o.financial_status, "fulfillment_status": o.fulfillment_status,
                "cancelled": o.cancelled_at is not None, "is_test": o.is_test,
                "items": sum(i.quantity for i in o.items), "first_item": o.items[0].title if o.items else None,
            }
            for o in page
        ],
        "next_cursor": base64.urlsafe_b64encode(f"{page[-1].created_at.isoformat()}|{page[-1].id}".encode()).decode() if more and page else None,
    }
