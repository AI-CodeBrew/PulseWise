"""
Talking to Shopify's GraphQL Admin API (docs: https://shopify.dev/docs/api/admin-graphql).

Two ways to log in to a store, because Shopify changed how apps are created:
  * "token"              a ready-made Admin API access token (an older "custom app" token, starts with shpat_)
  * "client_credentials" a Dev Dashboard app's Client ID + secret. We exchange them for a token that lasts about 24 hours
                         (POST https://<shop>.myshopify.com/admin/oauth/access_token) and renew it when needed.
Either way the app needs the `read_orders` access scope (and `read_all_orders` to read orders older than 60 days).

IMPORTANT: this code follows Shopify's documentation but has NOT been run against a real store (we had no store to test with).
The tests use a pretend Shopify (see tests/test_shopify.py). Please run "Test connection" in the admin panel with a real store.
"""

import asyncio
import hashlib
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_API_VERSION = "2026-10"
# Only real Shopify store addresses are accepted: this stops the server from being pointed at any other host.
SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com$")
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_RETRIES = 3

ORDERS_QUERY = """
query Orders($first: Int!, $after: String, $query: String, $items: Int!) {
  orders(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      updatedAt
      cancelledAt
      test
      sourceName
      displayFinancialStatus
      displayFulfillmentStatus
      currentTotalPriceSet { shopMoney { amount currencyCode } }
      totalRefundedSet { shopMoney { amount } }
      lineItems(first: $items) {
        nodes {
          title
          sku
          quantity
          currentQuantity
          product { id }
          discountedTotalSet { shopMoney { amount } }
        }
      }
    }
  }
}
"""

SHOP_QUERY = "{ shop { name currencyCode } }"


class ShopifyError(Exception):
    """Something went wrong talking to Shopify. The message is written for the ADMIN (never shown to clients)."""


def clean_shop_domain(value: str) -> str:
    """"https://My-Shop.myshopify.com/admin" -> "my-shop.myshopify.com". Anything that isn't a Shopify store is refused."""
    text = value.strip().lower()
    text = re.sub(r"^https?://", "", text).split("/")[0].split("?")[0]
    if not SHOP_DOMAIN_RE.match(text):
        raise ShopifyError("That doesn't look like a Shopify store address. It should end in .myshopify.com, for example my-shop.myshopify.com.")
    return text


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _when(value: Any) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def parse_order(node: dict[str, Any]) -> dict[str, Any]:
    """One Shopify order (as GraphQL returns it) -> the plain values we store. Missing pieces become safe defaults."""
    total_money = ((node.get("currentTotalPriceSet") or {}).get("shopMoney")) or {}
    items = []
    for line in ((node.get("lineItems") or {}).get("nodes")) or []:
        quantity = int(line.get("quantity") or 0)
        current = int(line.get("currentQuantity") if line.get("currentQuantity") is not None else quantity)
        amount = _money(((line.get("discountedTotalSet") or {}).get("shopMoney") or {}).get("amount"))
        if quantity > 0 and current != quantity:  # some units were refunded or removed: count only the part still sold
            amount = (amount * current / quantity).quantize(Decimal("0.01"))
        if current <= 0:
            continue
        items.append({
            "title": (line.get("title") or "(untitled product)")[:500],
            "sku": (line.get("sku") or None) and str(line["sku"])[:120],
            "product_id": ((line.get("product") or {}).get("id")),
            "quantity": current,
            "amount": amount,
        })
    return {
        "shopify_id": node["id"],
        "name": node.get("name") or node["id"],
        "created_at": _when(node["createdAt"]),
        "updated_at": _when(node.get("updatedAt")),
        "cancelled_at": _when(node.get("cancelledAt")),
        "financial_status": node.get("displayFinancialStatus"),
        "fulfillment_status": node.get("displayFulfillmentStatus"),
        "currency": total_money.get("currencyCode") or "",
        "total": _money(total_money.get("amount")),
        "refunded": _money((((node.get("totalRefundedSet") or {}).get("shopMoney")) or {}).get("amount")),
        "is_test": bool(node.get("test")),
        "source_name": node.get("sourceName"),
        "items": items,
    }


# Client-credentials tokens, kept in memory until shortly before they expire: (shop, hash of id+secret) -> (token, expires_at)
_token_cache: dict[tuple[str, str], tuple[str, float]] = {}


class ShopifyClient:
    def __init__(self, shop_domain: str, auth_mode: str, credentials: dict[str, str], api_version: str = DEFAULT_API_VERSION):
        self.shop = clean_shop_domain(shop_domain)
        self.auth_mode = auth_mode
        self.credentials = credentials
        self.api_version = api_version

    # -- the one place that really sends HTTP (tests replace it with a pretend Shopify) --------------------

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as http:
            return await http.request(method, url, **kwargs)

    async def _call(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._send(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ShopifyError(f"Couldn't reach {self.shop} ({type(exc).__name__}).") from None

    # -- login ---------------------------------------------------------------------------------------------

    async def _token(self, *, fresh: bool = False) -> str:
        if self.auth_mode == "token":
            return self.credentials["access_token"]
        # The secret is part of the key (as a hash), so a WRONG secret can never reuse the token of a right one.
        key = (self.shop, hashlib.sha256((self.credentials["client_id"] + ":" + self.credentials["client_secret"]).encode()).hexdigest())
        cached = _token_cache.get(key)
        if cached and not fresh and cached[1] - time.monotonic() > 300:  # renew when under 5 minutes are left
            return cached[0]
        response = await self._call(
            "POST",
            f"https://{self.shop}/admin/oauth/access_token",
            data={"grant_type": "client_credentials", "client_id": self.credentials["client_id"], "client_secret": self.credentials["client_secret"]},
        )
        body = _json(response)
        if response.status_code != 200 or not body.get("access_token"):
            reason = body.get("error_description") or body.get("error") or f"HTTP {response.status_code}"
            hint = " (the app and the store must be in the same Dev Dashboard organisation)" if body.get("error") == "shop_not_permitted" else ""
            raise ShopifyError(f"Shopify refused the Client ID / secret: {reason}{hint}.")
        _token_cache[key] = (body["access_token"], time.monotonic() + float(body.get("expires_in") or 86000))
        return body["access_token"]

    # -- GraphQL -------------------------------------------------------------------------------------------

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a GraphQL query and return its `data`. Retries when Shopify says "slow down" and renews an expired token once."""
        renewed = False
        for attempt in range(MAX_RETRIES + 1):
            token = await self._token(fresh=renewed)
            response = await self._call(
                "POST",
                f"https://{self.shop}/admin/api/{self.api_version}/graphql.json",
                headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}},
            )
            body = _json(response)
            errors = body.get("errors") if isinstance(body.get("errors"), list) else []
            codes = {(e.get("extensions") or {}).get("code") for e in errors if isinstance(e, dict)}

            throttled = response.status_code == 429 or "THROTTLED" in codes
            if throttled and attempt < MAX_RETRIES:
                wait = min(float(response.headers.get("Retry-After", "1") or 1), 10.0)
                await _pause(max(wait, 1.0))  # Shopify's advice: wait at least a second
                continue
            if throttled:
                raise ShopifyError("Shopify is rate-limiting us (too many requests). It will be retried at the next sync.")
            if response.status_code == 401:
                if self.auth_mode == "client_credentials" and not renewed:
                    renewed = True  # the cached token may have been revoked: get a new one and try once more
                    continue
                raise ShopifyError("Shopify rejected the access token (401). It may be wrong, revoked or from another store.")
            if response.status_code == 403 or "ACCESS_DENIED" in codes:
                raise ShopifyError("Shopify says this app isn't allowed to read orders. Give the app the read_orders access scope (and read_all_orders for orders older than 60 days).")
            if response.status_code == 404:
                raise ShopifyError(f"Shopify doesn't know the store {self.shop} or the API version {self.api_version}.")
            if response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    await _pause(1.5 * (attempt + 1))
                    continue
                raise ShopifyError(f"Shopify had a problem (HTTP {response.status_code}). It will be retried at the next sync.")
            if errors:
                if "MAX_COST_EXCEEDED" in codes:
                    raise QueryTooBig()
                raise ShopifyError("Shopify returned an error: " + "; ".join(str(e.get("message", e)) for e in errors[:3] if isinstance(e, dict))[:400])
            if response.status_code != 200 or "data" not in body:
                raise ShopifyError(f"Unexpected answer from Shopify (HTTP {response.status_code}).")
            return body["data"]
        raise ShopifyError("Shopify could not be reached.")  # (the loop always returns or raises; kept for completeness)

    async def shop_info(self) -> dict[str, str]:
        """The shop's name and currency. Doubles as the "test connection" call."""
        data = await self.graphql(SHOP_QUERY)
        shop = data.get("shop") or {}
        return {"name": shop.get("name") or self.shop, "currency": shop.get("currencyCode") or ""}

    async def iter_orders(self, updated_since: datetime, *, page_size: int = 25, items_per_order: int = 20, max_pages: int = 200) -> AsyncIterator[list[dict[str, Any]]]:
        """Pages of orders changed since `updated_since`, oldest change first. Each page is a list of parse_order() dicts."""
        since = updated_since.strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor: str | None = None
        for _ in range(max_pages):
            try:
                data = await self.graphql(ORDERS_QUERY, {"first": page_size, "after": cursor, "query": f"updated_at:>='{since}'", "items": items_per_order})
            except QueryTooBig:
                if page_size <= 5:
                    raise ShopifyError("Shopify says the orders query is too expensive even in the smallest size.") from None
                page_size = max(5, page_size // 2)  # ask for fewer orders at a time and try this page again
                continue
            block = (data.get("orders") or {})
            yield [parse_order(n) for n in block.get("nodes") or []]
            info = block.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return
            cursor = info.get("endCursor")
        raise TooManyPages()


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)  # (tests replace this so they don't really wait)


class QueryTooBig(Exception):
    """Shopify's cost limit for one query was exceeded: ask for less."""


class TooManyPages(Exception):
    """A single sync reached its page limit; the rest is picked up by the next sync."""


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
