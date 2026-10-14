"""
Shopify: the API client, the order sync, the sales numbers, the admin connection and the hourly job.

ALL of this runs against a PRETEND Shopify (FakeShopify below), written from Shopify's documentation.
It proves our logic (idempotent sync, paging, retries, money maths, access rules). It cannot prove that real
Shopify answers exactly like the pretend one: that needs a real store (see docs/ROADMAP.md, Phase 9).
"""

import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select

from app.billing.service import FEATURES
from app.jobs import run_job
from app.models import Alert, AuditLog, Plan, ShopConnection, ShopOrder, ShopOrderItem, Subscription
from app.security import encrypt_secret
from app.shopify import client as shopify_client
from app.shopify import sales
from app.shopify.client import ShopifyClient, ShopifyError, clean_shop_domain, parse_order
from app.shopify.sync import sync_website

SHOP = "demo-shop.myshopify.com"
GOOD_TOKEN = "shpat_good_token_123"


# ------------------------------------------------------------------ a pretend Shopify


def ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def line(title, quantity=1, amount="1000.00", current=None, sku="SKU-1", product=None):
    return {"title": title, "sku": sku, "quantity": quantity, "currentQuantity": quantity if current is None else current,
            "product": {"id": product or f"gid://shopify/Product/{abs(hash(title)) % 10**6}"}, "discountedTotalSet": {"shopMoney": {"amount": amount}}}


def node(n, *, created=None, updated=None, total="1000.00", refunded="0.00", source="web", test=False, cancelled=None, status="PAID", lines=None):
    created = created or ago(days=1)
    return {
        "id": f"gid://shopify/Order/{n}", "name": f"#{1000 + n}", "createdAt": created, "updatedAt": updated or created, "cancelledAt": cancelled,
        "test": test, "sourceName": source, "displayFinancialStatus": status, "displayFulfillmentStatus": "UNFULFILLED",
        "currentTotalPriceSet": {"shopMoney": {"amount": total, "currencyCode": "PKR"}},
        "totalRefundedSet": {"shopMoney": {"amount": refunded}},
        "lineItems": {"nodes": lines if lines is not None else [line("T-shirt", 1, total)]},
    }


class FakeShopify:
    """Answers like Shopify's token endpoint and GraphQL Admin API (as documented on shopify.dev)."""

    def __init__(self):
        self.orders: list[dict] = []
        self.requests: list[dict] = []
        self.issued: set[str] = set()  # tokens handed out by the (pretend) token endpoint
        self.token_calls = 0
        self.throttle = 0  # answer "THROTTLED" this many times
        self.max_first = 100  # a bigger page than this is "too expensive"
        self.deny_orders = False  # the app lacks the read_orders scope
        self.status_override: int | None = None  # answer every GraphQL call with this HTTP status
        self.valid_client = ("client-id-1", "client-secret-1")

    def response(self, status, body, url="https://x", headers=None):
        return httpx.Response(status, json=body, headers=headers, request=httpx.Request("POST", url))

    async def send(self, client, method, url, **kwargs):
        host = httpx.URL(url).host
        assert host == client.shop and host.endswith(".myshopify.com"), f"request to an unexpected host: {host}"  # (only ever the store itself)
        path = httpx.URL(url).path
        if path == "/admin/oauth/access_token":
            self.token_calls += 1
            form = kwargs["data"]
            assert form["grant_type"] == "client_credentials"
            if (form["client_id"], form["client_secret"]) != self.valid_client:
                return self.response(400, {"error": "invalid_client", "error_description": "bad client"}, url)
            token = f"cc-token-{self.token_calls}"
            self.issued.add(token)
            return self.response(200, {"access_token": token, "scope": "read_orders", "expires_in": 86399}, url)

        assert re.fullmatch(r"/admin/api/[\d-]+/graphql\.json", path), path
        token = kwargs["headers"]["X-Shopify-Access-Token"]
        body = kwargs["json"]
        self.requests.append({"token": token, "variables": body["variables"], "query": body["query"], "api_path": path})
        if self.status_override:
            return self.response(self.status_override, {}, url)
        if token != GOOD_TOKEN and token not in self.issued:
            return self.response(401, {"errors": "[API] Invalid API key or access token"}, url)
        if self.throttle > 0:
            self.throttle -= 1
            return self.response(200, {"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]}, url)
        if "shop {" in body["query"]:
            return self.response(200, {"data": {"shop": {"name": "Demo Shop", "currencyCode": "PKR"}}}, url)
        if self.deny_orders:
            return self.response(200, {"errors": [{"message": "Access denied for orders field.", "extensions": {"code": "ACCESS_DENIED"}}]}, url)

        variables = body["variables"]
        if variables["first"] > self.max_first:
            return self.response(200, {"errors": [{"message": "Query cost is too high", "extensions": {"code": "MAX_COST_EXCEEDED"}}]}, url)
        since = re.search(r"updated_at:>='([^']+)'", variables["query"]).group(1)
        matching = sorted((o for o in self.orders if o["updatedAt"] >= since), key=lambda o: o["updatedAt"])
        start = int(variables["after"] or 0)
        page = matching[start : start + variables["first"]]
        more = start + len(page) < len(matching)
        return self.response(200, {"data": {"orders": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + len(page))}, "nodes": page}}}, url)


@pytest.fixture
def shop(monkeypatch):
    fake = FakeShopify()

    async def send(self, method, url, **kwargs):
        return await fake.send(self, method, url, **kwargs)

    async def no_wait(seconds):
        fake.waited = getattr(fake, "waited", []) + [seconds]

    monkeypatch.setattr(ShopifyClient, "_send", send)
    monkeypatch.setattr(shopify_client, "_pause", no_wait)
    shopify_client._token_cache.clear()
    yield fake
    shopify_client._token_cache.clear()


def connect_in_db(db, site, mode="token", **creds):
    credentials = creds or ({"access_token": GOOD_TOKEN} if mode == "token" else {"client_id": "client-id-1", "client_secret": "client-secret-1"})
    db.add(ShopConnection(website_id=site.id, shop_domain=SHOP, auth_mode=mode, credentials_encrypted=encrypt_secret(json.dumps(credentials)), shop_name="Demo Shop", currency="PKR"))
    db.commit()


def run_sync(site):
    return asyncio.run(sync_website(site.id))


def stored(db, site):
    db.expire_all()
    return db.scalars(select(ShopOrder).where(ShopOrder.website_id == site.id).order_by(ShopOrder.name)).all()


# ------------------------------------------------------------------ store addresses (nothing but Shopify is ever called)


@pytest.mark.parametrize("given, clean", [
    ("my-shop.myshopify.com", "my-shop.myshopify.com"),
    ("  HTTPS://My-Shop.myshopify.com/admin/orders?x=1  ", "my-shop.myshopify.com"),
    ("shop1.myshopify.com", "shop1.myshopify.com"),
])
def test_store_addresses_are_cleaned(given, clean):
    assert clean_shop_domain(given) == clean


@pytest.mark.parametrize("bad", [
    "", "example.com", "my-shop.myshopify.com.evil.com", "evil.com/my-shop.myshopify.com", "http://169.254.169.254/latest",
    "user@my-shop.myshopify.com", "my shop.myshopify.com", "-bad.myshopify.com", "localhost", "my-shop.myshopify.com:8080", "[::1]",
])
def test_anything_that_is_not_a_shopify_store_is_refused(bad):
    with pytest.raises(ShopifyError):
        clean_shop_domain(bad)
    with pytest.raises(ShopifyError):
        ShopifyClient(bad, "token", {"access_token": "x"})


# ------------------------------------------------------------------ reading an order


def test_an_order_is_turned_into_plain_values():
    order = parse_order(node(1, total="2500.50", refunded="500.00", lines=[line("Hoodie", 2, "2000.00", sku="H-1", product="gid://shopify/Product/9"), line("Cap", 1, "500.50")]))
    assert order["shopify_id"] == "gid://shopify/Order/1" and order["name"] == "#1001" and order["currency"] == "PKR"
    assert order["total"] == Decimal("2500.50") and order["refunded"] == Decimal("500.00") and order["source_name"] == "web"
    assert order["created_at"].tzinfo is not None and order["cancelled_at"] is None and order["is_test"] is False
    assert [(i["title"], i["quantity"], i["amount"], i["sku"]) for i in order["items"]] == [("Hoodie", 2, Decimal("2000.00"), "H-1"), ("Cap", 1, Decimal("500.50"), "SKU-1")]
    assert order["items"][0]["product_id"] == "gid://shopify/Product/9"


def test_refunded_units_are_not_counted_as_sold():
    order = parse_order(node(2, lines=[line("Hoodie", quantity=4, amount="4000.00", current=3), line("Gone", quantity=1, amount="900.00", current=0)]))
    assert [(i["title"], i["quantity"], i["amount"]) for i in order["items"]] == [("Hoodie", 3, Decimal("3000.00"))]  # a quarter refunded; the fully removed line disappears


def test_an_order_with_missing_pieces_still_reads():
    bare = {"id": "gid://shopify/Order/3", "createdAt": "2026-10-01T10:00:00Z", "lineItems": None, "currentTotalPriceSet": None}
    order = parse_order(bare)
    assert order["total"] == Decimal("0.00") and order["items"] == [] and order["name"] == "gid://shopify/Order/3" and order["refunded"] == Decimal("0.00")


# ------------------------------------------------------------------ logging in


def test_a_token_is_sent_as_given_and_the_shop_is_read(shop):
    info = asyncio.run(ShopifyClient(SHOP, "token", {"access_token": GOOD_TOKEN}).shop_info())
    assert info == {"name": "Demo Shop", "currency": "PKR"} and shop.requests[0]["token"] == GOOD_TOKEN and shop.token_calls == 0


def test_client_credentials_are_exchanged_once_and_reused(shop):
    client = ShopifyClient(SHOP, "client_credentials", {"client_id": "client-id-1", "client_secret": "client-secret-1"})
    asyncio.run(client.shop_info())
    asyncio.run(client.shop_info())
    assert shop.token_calls == 1 and {r["token"] for r in shop.requests} == {"cc-token-1"}


def test_an_expired_or_revoked_client_credentials_token_is_renewed_once(shop):
    client = ShopifyClient(SHOP, "client_credentials", {"client_id": "client-id-1", "client_secret": "client-secret-1"})
    asyncio.run(client.shop_info())
    shop.issued.clear()  # Shopify no longer accepts the old token
    asyncio.run(client.shop_info())
    assert shop.token_calls == 2 and shop.requests[-1]["token"] == "cc-token-2"


def test_wrong_credentials_give_a_clear_message(shop):
    with pytest.raises(ShopifyError, match="refused the Client ID"):
        asyncio.run(ShopifyClient(SHOP, "client_credentials", {"client_id": "nope", "client_secret": "nope"}).shop_info())
    with pytest.raises(ShopifyError, match="rejected the access token"):
        asyncio.run(ShopifyClient(SHOP, "token", {"access_token": "shpat_wrong"}).shop_info())


def test_a_token_that_can_not_read_orders_says_which_scope_is_missing(shop):
    shop.deny_orders = True
    with pytest.raises(ShopifyError, match="read_orders"):
        asyncio.run(_collect(ShopifyClient(SHOP, "token", {"access_token": GOOD_TOKEN}), datetime.now(timezone.utc) - timedelta(days=1)))


async def _collect(client, since, **kwargs):
    return [page async for page in client.iter_orders(since, **kwargs)]


@pytest.mark.parametrize("status, text", [(403, "read_orders"), (404, "doesn't know the store"), (500, "had a problem"), (418, "Unexpected answer")])
def test_other_http_failures_are_explained(shop, status, text):
    shop.status_override = status
    with pytest.raises(ShopifyError, match=text):
        asyncio.run(ShopifyClient(SHOP, "token", {"access_token": GOOD_TOKEN}).shop_info())


def test_when_shopify_says_slow_down_we_wait_and_try_again(shop):
    shop.throttle = 2
    info = asyncio.run(ShopifyClient(SHOP, "token", {"access_token": GOOD_TOKEN}).shop_info())
    assert info["name"] == "Demo Shop" and len(shop.waited) == 2 and min(shop.waited) >= 1.0  # never faster than once a second


def test_being_throttled_for_good_gives_up_with_a_message(shop):
    shop.throttle = 99
    with pytest.raises(ShopifyError, match="rate-limiting"):
        asyncio.run(ShopifyClient(SHOP, "token", {"access_token": GOOD_TOKEN}).shop_info())
    assert len(shop.requests) == shopify_client.MAX_RETRIES + 1


def test_an_unreachable_shopify_is_a_plain_error(monkeypatch):
    async def down(self, method, url, **kwargs):
        raise httpx.ConnectError("boom with a secret in it shpat_secret")

    monkeypatch.setattr(ShopifyClient, "_send", down)
    with pytest.raises(ShopifyError) as caught:
        asyncio.run(ShopifyClient(SHOP, "token", {"access_token": "shpat_secret"}).shop_info())
    assert "shpat_secret" not in str(caught.value)


# ------------------------------------------------------------------ syncing


def test_the_first_sync_reads_sixty_days_and_saves_orders_with_their_products(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [
        node(1, created=ago(days=2), total="3000.00", lines=[line("Hoodie", 2, "2000.00"), line("Cap", 1, "1000.00")]),
        node(2, created=ago(days=50), total="500.00"),
        node(3, created=ago(days=90), total="999.00"),  # older than the first sync reads
    ]
    assert run_sync(world.site_a) == {"orders": 2}
    orders = stored(db, world.site_a)
    assert [o.name for o in orders] == ["#1001", "#1002"] and orders[0].total == Decimal("3000.00") and orders[0].currency == "PKR"
    assert sorted((i.title, i.quantity) for i in orders[0].items) == [("Cap", 1), ("Hoodie", 2)]
    since = shop.requests[0]["variables"]["query"]
    assert since.startswith("updated_at:>='") and abs((datetime.now(timezone.utc) - datetime.fromisoformat(since.split("'")[1].replace("Z", "+00:00"))).days - 60) <= 1
    connection = db.scalar(select(ShopConnection))
    assert connection.last_synced_at is not None and connection.last_error is None


def test_syncing_again_never_duplicates_and_updates_changed_orders(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [node(1, created=ago(days=3), total="1000.00")]
    run_sync(world.site_a)
    run_sync(world.site_a)
    assert len(stored(db, world.site_a)) == 1
    # The order is edited: refunded, one product swapped, cancelled later.
    shop.orders = [node(1, created=ago(days=3), updated=ago(minutes=1), total="700.00", refunded="300.00", status="PARTIALLY_REFUNDED", lines=[line("Different", 1, "700.00")])]
    assert run_sync(world.site_a) == {"orders": 1}  # the second sync asked only for what changed since the first
    [order] = stored(db, world.site_a)
    assert order.total == Decimal("700.00") and order.refunded == Decimal("300.00") and order.financial_status == "PARTIALLY_REFUNDED"
    assert [i.title for i in order.items] == ["Different"]
    assert db.scalar(select(func.count()).select_from(ShopOrderItem)) == 1  # the old product row is gone, not orphaned


def test_a_later_sync_asks_only_for_recent_changes(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [node(1, created=ago(days=5))]
    run_sync(world.site_a)
    run_sync(world.site_a)
    first, second = (r["variables"]["query"] for r in shop.requests)
    stamp = lambda q: datetime.fromisoformat(q.split("'")[1].replace("Z", "+00:00"))  # noqa: E731
    assert stamp(second) > stamp(first) + timedelta(days=50)  # from "a few minutes ago", not from 60 days back
    assert stamp(second) > datetime.now(timezone.utc) - timedelta(hours=1)


def test_many_orders_are_read_page_by_page(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [node(n, created=ago(hours=n), updated=ago(hours=n)) for n in range(1, 61)]
    assert run_sync(world.site_a) == {"orders": 60}
    assert len(stored(db, world.site_a)) == 60 and len(shop.requests) == 3  # 25 + 25 + 10


def test_a_query_that_is_too_expensive_is_retried_with_smaller_pages(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.max_first = 10
    shop.orders = [node(n, created=ago(hours=n), updated=ago(hours=n)) for n in range(1, 31)]
    run_sync(world.site_a)
    assert len(stored(db, world.site_a)) == 30
    assert [r["variables"]["first"] for r in shop.requests][:3] == [25, 12, 6]  # 25 refused, 12 still too big, 6 fits: then it carries on with 6


def test_a_huge_store_continues_at_the_next_sync(db, world, shop, monkeypatch):
    connect_in_db(db, world.site_a)
    shop.orders = [node(n, created=ago(hours=n), updated=ago(hours=n)) for n in range(1, 21)]
    original = ShopifyClient.iter_orders

    def small_pages(self, since, **kwargs):
        return original(self, since, page_size=5, max_pages=2)  # at most 10 orders per sync

    monkeypatch.setattr(ShopifyClient, "iter_orders", small_pages)
    assert run_sync(world.site_a) == {"orders": 10}
    for _ in range(3):
        run_sync(world.site_a)
    assert len(stored(db, world.site_a)) == 20  # the oldest changes first, so every later sync picks up where the last stopped


def test_client_credentials_work_for_syncing_too(db, world, shop):
    connect_in_db(db, world.site_a, mode="client_credentials")
    shop.orders = [node(1)]
    assert run_sync(world.site_a) == {"orders": 1} and shop.token_calls == 1


def test_a_failing_sync_is_recorded_and_alerted_then_clears_itself(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.deny_orders = True
    with pytest.raises(ShopifyError):
        run_sync(world.site_a)
    db.expire_all()
    assert "read_orders" in db.scalar(select(ShopConnection)).last_error
    alert = db.scalar(select(Alert).where(Alert.dedupe_key == f"shopify:{world.site_a.id}", Alert.status == "open"))
    assert alert is not None and alert.client_id == world.client_a.id and "Client A site" in alert.message
    shop.deny_orders = False
    shop.orders = [node(1)]
    run_sync(world.site_a)
    db.expire_all()
    assert db.scalar(select(ShopConnection)).last_error is None
    assert db.scalar(select(Alert).where(Alert.dedupe_key == f"shopify:{world.site_a.id}", Alert.status == "open")) is None


def test_syncing_a_website_without_a_store_is_an_error(world, shop):
    with pytest.raises(ShopifyError, match="no Shopify store"):
        run_sync(world.site_a)


def test_two_clients_orders_stay_apart(db, world, shop):
    connect_in_db(db, world.site_a)
    connect_in_db(db, world.site_b)
    shop.orders = [node(1)]  # (both stores, in this pretend, hold the same order id)
    run_sync(world.site_a)
    run_sync(world.site_b)
    assert len(stored(db, world.site_a)) == 1 and len(stored(db, world.site_b)) == 1  # same Shopify id, two different websites


# ------------------------------------------------------------------ the money


def seed_orders(db, site, rows):
    """rows: (name, created_at, total, kwargs). Saved directly, so the maths is tested on its own."""
    for index, (created, total, extra) in enumerate(rows, start=1):
        items = extra.pop("items", [("T-shirt", 1, total)])
        order = ShopOrder(website_id=site.id, shopify_id=f"gid://shopify/Order/{index}", name=f"#{1000 + index}", created_at=created, currency="PKR",
                          total=Decimal(total), refunded=Decimal(extra.pop("refunded", "0")), source_name=extra.pop("source", "web"), **extra)
        order.items = [ShopOrderItem(website_id=site.id, title=t, quantity=q, amount=Decimal(a)) for t, q, a in items]
        db.add(order)
    db.commit()


def at(**delta):
    return datetime.now(timezone.utc) - timedelta(**delta)


def test_revenue_orders_and_average_order_with_the_previous_period(db, world, api, fake_posthog):
    connect_in_db(db, world.site_a)
    seed_orders(db, world.site_a, [
        (at(days=1), "1000.00", {}), (at(days=2), "3000.00", {"refunded": "200.00"}),
        (at(days=40), "1000.00", {}), (at(days=45), "1000.00", {}), (at(days=50), "2000.00", {}),  # the 30 days before
        (at(days=1, hours=1), "9999.00", {"is_test": True}),  # test order: never counted
        (at(days=1, hours=2), "8888.00", {"cancelled_at": at(days=1)}),  # cancelled: never counted
    ])
    fake_posthog.answer("sales:sessions", ["day", "sessions"], [])
    s = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales", params={"days": 30}).json()
    assert s["connected"] is True and s["shop_name"] == "Demo Shop" and s["currency"] == "PKR"
    assert s["revenue"] == {"current": 4000.0, "previous": 4000.0, "change_pct": 0.0}
    assert s["orders"] == {"current": 2, "previous": 3, "change_pct": -33.3}
    assert s["average_order_value"] == {"current": 2000.0, "previous": 1333.33, "change_pct": 50.0}
    assert s["units"]["current"] == 2 and s["refunded"] == 200.0
    assert s["period"]["days"] == 30 and len(s["daily"]) == 30
    assert sum(d["revenue"] for d in s["daily"]) == 4000.0 and sum(d["orders"] for d in s["daily"]) == 2


def test_conversion_joins_orders_with_website_sessions(db, world, api, fake_posthog):
    connect_in_db(db, world.site_a)
    today = datetime.now(ZoneInfo("Asia/Karachi")).date()
    seed_orders(db, world.site_a, [(at(hours=3), "1000.00", {}), (at(hours=4), "2000.00", {}), (at(hours=5), "500.00", {"source": "pos"})])
    fake_posthog.answer("sales:sessions", ["day", "sessions"], [[today.isoformat(), 100], [(today - timedelta(days=40)).isoformat(), 50]])
    s = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales", params={"days": 30}).json()
    assert s["traffic"]["sessions"]["current"] == 100
    assert s["traffic"]["conversion_rate"]["current"] == 2.0  # 2 online-store orders / 100 sessions (the till order isn't a website sale)
    assert s["traffic"]["revenue_per_session"]["current"] == 35.0  # 3500 revenue / 100 sessions (all channels)
    assert s["daily"][-1]["sessions"] == 100


def test_sales_still_work_when_the_analytics_are_unavailable(db, world, api, fake_posthog):
    from app.security import encrypt_secret as enc

    world.site_a.posthog_api_key_encrypted = enc("phx_bad_key")  # the fake PostHog refuses this key
    db.merge(world.site_a)
    connect_in_db(db, world.site_a)
    seed_orders(db, world.site_a, [(at(hours=3), "1000.00", {})])
    s = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales").json()
    assert s["traffic"] is None and s["revenue"]["current"] == 1000.0


def test_days_are_the_clients_days_not_utc_days():
    karachi = ZoneInfo("Asia/Karachi")  # UTC+5
    # 22:30 UTC on 10 Oct is 03:30 on 11 Oct in Karachi.
    orders = [(datetime(2026, 10, 10, 22, 30, tzinfo=timezone.utc), "100.00", {}), (datetime(2026, 10, 10, 18, 0, tzinfo=timezone.utc), "50.00", {})]
    from app.db import get_sessionmaker
    from tests.conftest import make_client, make_website

    with get_sessionmaker()() as db:
        client = make_client(db, "Tz")
        site = make_website(db, client, 1, "phx_x")
        db.commit()
        seed_orders(db, site, orders)
        series = sales.daily_series(db, site.id, karachi, date(2026, 10, 10), date(2026, 10, 11))
    assert [(d["date"], d["orders"], d["revenue"]) for d in series] == [("2026-10-10", 1, 50.0), ("2026-10-11", 1, 100.0)]


def test_top_products_by_revenue_with_units(db, world, api, fake_posthog):
    connect_in_db(db, world.site_a)
    seed_orders(db, world.site_a, [
        (at(days=1), "3000.00", {"items": [("Hoodie", 2, "2000.00"), ("Cap", 1, "1000.00")]}),
        (at(days=2), "2500.00", {"items": [("Hoodie", 1, "1000.00"), ("Socks", 5, "1500.00")]}),
        (at(days=3), "400.00", {"items": [("Cap", 1, "400.00")], "cancelled_at": at(days=3)}),  # cancelled: its products don't count
    ])
    s = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales").json()
    assert s["top_products"] == [
        {"title": "Hoodie", "units": 3, "revenue": 3000.0}, {"title": "Socks", "units": 5, "revenue": 1500.0}, {"title": "Cap", "units": 1, "revenue": 1000.0},
    ]


def test_an_unconnected_website_says_so_and_asks_nobody(world, api, fake_posthog):
    s = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales").json()
    assert s == {"connected": False} and fake_posthog.calls == []
    assert api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales/orders").json() == {"results": [], "next_cursor": None}


# ------------------------------------------------------------------ the orders list


def test_orders_are_listed_newest_first_with_a_cursor(db, world, api):
    connect_in_db(db, world.site_a)
    same_second = at(days=1).replace(microsecond=0)
    seed_orders(db, world.site_a, [(same_second, "10.00", {}), (same_second, "20.00", {}), (same_second, "30.00", {}), (at(days=5), "40.00", {}), (at(days=9), "50.00", {"is_test": True})])
    alice = api("alice@a.test")
    path = f"/api/websites/{world.site_a.id}/sales/orders"
    seen, cursor = [], None
    for _ in range(5):
        page = alice.get(path, params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [o["name"] for o in page["results"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5  # equal timestamps are neither skipped nor repeated
    first = alice.get(path, params={"limit": 1}).json()["results"][0]
    assert set(first) == {"id", "name", "created_at", "total", "currency", "financial_status", "fulfillment_status", "cancelled", "is_test", "items", "first_item"}
    assert alice.get(path, params={"cursor": "not-a-cursor"}).status_code == 400
    assert alice.get(path, params={"cursor": "AAAA"}).status_code == 400


# ------------------------------------------------------------------ who may see sales


def test_sales_are_private_to_each_client(db, world, api, fake_posthog):
    connect_in_db(db, world.site_a)
    connect_in_db(db, world.site_b)
    seed_orders(db, world.site_a, [(at(days=1), "1000.00", {})])
    seed_orders(db, world.site_b, [(at(days=1), "7777.00", {})])
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_b.id}/sales").status_code == 404
    assert alice.get(f"/api/websites/{world.site_b.id}/sales/orders").status_code == 404
    mine = alice.get(f"/api/websites/{world.site_a.id}/sales").json()
    assert mine["revenue"]["current"] == 1000.0 and "7777" not in json.dumps(mine)
    assert api("vera@a.test").get(f"/api/websites/{world.site_a.id}/sales").status_code == 200  # viewers may look
    assert api().get(f"/api/websites/{world.site_a.id}/sales").status_code == 401


def test_sales_need_a_plan_that_includes_shopify(db, world, api):
    connect_in_db(db, world.site_a)
    plan = Plan(name="Basic", slug="basic", features={k: False for k in FEATURES}, price_pkr=1, price_usd=1)
    db.add(plan)
    db.commit()
    db.add(Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=date(2026, 1, 1), billing_day=1))
    db.commit()
    alice = api("alice@a.test")
    for suffix in ("", "/orders"):
        response = alice.get(f"/api/websites/{world.site_a.id}/sales{suffix}")
        assert response.status_code == 403 and "Shopify sales" in response.json()["detail"]
    assert api("admin@agency.test").get(f"/api/websites/{world.site_a.id}/sales").status_code == 200


def test_clients_never_see_credentials_or_sync_errors(db, world, api, fake_posthog):
    connect_in_db(db, world.site_a)
    db.scalar(select(ShopConnection)).last_error = "secret internal reason shpat_leak"
    db.commit()
    text = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales").text
    assert GOOD_TOKEN not in text and "shpat" not in text and "secret internal reason" not in text
    assert api("alice@a.test").get(f"/api/websites/{world.site_a.id}/sales").json()["sync_failing"] is True
    assert "posthog" not in text.lower()


# ------------------------------------------------------------------ the admin connection


def connect(api, site, **body):
    return api("admin@agency.test").put(f"/api/admin/websites/{site.id}/shopify", json={"shop_domain": "https://Demo-Shop.myshopify.com/admin", **body})


def test_connecting_tests_the_login_stores_it_encrypted_and_starts_syncing(db, world, api, shop):
    shop.orders = [node(1)]
    response = connect(api, world.site_a, access_token=GOOD_TOKEN)
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] and body["shop_domain"] == SHOP and body["shop_name"] == "Demo Shop" and body["currency"] == "PKR" and body["auth_mode"] == "token"
    assert GOOD_TOKEN not in response.text and "credentials" not in response.text
    db.expire_all()
    connection = db.scalar(select(ShopConnection))
    assert GOOD_TOKEN not in connection.credentials_encrypted and connection.website_id == world.site_a.id
    assert len(stored(db, world.site_a)) == 1  # the first sync ran right after connecting
    assert api("admin@agency.test").get(f"/api/admin/websites/{world.site_a.id}/shopify").json()["orders_stored"] == 1
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "admin.shopify_connected")).one()
    assert GOOD_TOKEN not in json.dumps(entry.details)


def test_connecting_with_client_credentials(db, world, api, shop):
    assert connect(api, world.site_a, client_id="client-id-1", client_secret="client-secret-1").json()["auth_mode"] == "client_credentials"
    assert connect(api, world.site_a, client_id="client-id-1", client_secret="WRONG-SECRET").status_code == 400


@pytest.mark.parametrize("body, status", [
    ({}, 422), ({"access_token": GOOD_TOKEN, "client_id": "client-id-1", "client_secret": "client-secret-1"}, 422), ({"client_id": "client-id-1"}, 422),
    ({"access_token": "shpat_wrong_token"}, 400), ({"shop_domain": "evil.example.com", "access_token": GOOD_TOKEN}, 400),
])
def test_bad_connections_are_refused_and_nothing_is_saved(db, world, api, shop, body, status):
    payload = {"shop_domain": SHOP, **body}
    assert api("admin@agency.test").put(f"/api/admin/websites/{world.site_a.id}/shopify", json=payload).status_code == status
    assert db.scalar(select(func.count()).select_from(ShopConnection)) == 0


def test_a_refused_login_explains_why_to_the_admin(api, world, shop):
    detail = connect(api, world.site_a, access_token="shpat_wrong_token").json()["detail"]
    assert "rejected the access token" in detail


def test_only_admins_can_manage_connections(api, world, shop):
    url = f"/api/admin/websites/{world.site_a.id}/shopify"
    for who in ("alice@a.test", "vera@a.test"):
        client = api(who)
        assert client.get(url).status_code == 403
        assert client.put(url, json={"shop_domain": SHOP, "access_token": GOOD_TOKEN}).status_code == 403
        assert client.post(url + "/sync").status_code == 403
        assert client.delete(url).status_code == 403
    assert api().get(url).status_code == 401
    assert api("admin@agency.test").get("/api/admin/websites/00000000-0000-0000-0000-000000000000/shopify").status_code == 404


def test_the_admin_can_sync_now_and_sees_why_it_fails(db, world, api, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [node(1), node(2)]
    admin = api("admin@agency.test")
    done = admin.post(f"/api/admin/websites/{world.site_a.id}/shopify/sync").json()
    assert done["orders"] == 2 and done["orders_stored"] == 2 and done["last_error"] is None
    shop.deny_orders = True
    failed = admin.post(f"/api/admin/websites/{world.site_a.id}/shopify/sync")
    assert failed.status_code == 502 and "read_orders" in failed.json()["detail"]
    assert "read_orders" in admin.get(f"/api/admin/websites/{world.site_a.id}/shopify").json()["last_error"]


def test_reconnecting_to_a_different_store_clears_the_old_orders(db, world, api, shop):
    shop.orders = [node(1)]
    connect(api, world.site_a, access_token=GOOD_TOKEN)
    assert len(stored(db, world.site_a)) == 1
    # The same store again: the orders stay, and new changes are added.
    shop.orders = [node(7, updated=ago(minutes=1))]
    connect(api, world.site_a, access_token=GOOD_TOKEN)
    assert [o.name for o in stored(db, world.site_a)] == ["#1001", "#1007"]
    # A different store: the old orders must not stay mixed in with the new store's.
    shop.orders = [node(9)]
    api("admin@agency.test").put(f"/api/admin/websites/{world.site_a.id}/shopify", json={"shop_domain": "other-shop.myshopify.com", "access_token": GOOD_TOKEN})
    assert [o.name for o in stored(db, world.site_a)] == ["#1009"]


def test_disconnecting_deletes_the_copied_orders(db, world, api, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [node(1)]
    run_sync(world.site_a)
    admin = api("admin@agency.test")
    assert admin.delete(f"/api/admin/websites/{world.site_a.id}/shopify").json() == {"connected": False}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ShopOrder)) == 0 and db.scalar(select(func.count()).select_from(ShopOrderItem)) == 0
    assert db.scalar(select(func.count()).select_from(ShopConnection)) == 0
    assert admin.delete(f"/api/admin/websites/{world.site_a.id}/shopify").status_code == 404


def test_deleting_a_website_removes_its_shop_data(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.orders = [node(1)]
    run_sync(world.site_a)
    db.delete(db.get(type(world.site_a), world.site_a.id))
    db.commit()
    assert db.scalar(select(func.count()).select_from(ShopOrder)) == 0 and db.scalar(select(func.count()).select_from(ShopConnection)) == 0


# ------------------------------------------------------------------ the hourly job


def test_the_job_syncs_every_eligible_store_and_skips_the_rest(db, world, shop):
    connect_in_db(db, world.site_a)
    connect_in_db(db, world.site_b)
    world.client_b.status = "suspended"  # a suspended client's store isn't synced
    db.merge(world.client_b)
    db.commit()
    shop.orders = [node(1), node(2)]
    result = asyncio.run(run_job("shopify_sync", "test"))
    assert result["status"] == "ok" and "Synced 1 of 1 stores (2 orders read)" in result["message"]
    assert len(stored(db, world.site_a)) == 2 and stored(db, world.site_b) == []


def test_the_job_skips_plans_without_shopify(db, world, shop):
    connect_in_db(db, world.site_a)
    plan = Plan(name="Basic", slug="basic2", features={k: False for k in FEATURES}, price_pkr=1, price_usd=1)
    db.add(plan)
    db.commit()
    db.add(Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=date(2026, 1, 1), billing_day=1))
    db.commit()
    shop.orders = [node(1)]
    assert "Synced 0 of 0 stores" in asyncio.run(run_job("shopify_sync", "test"))["message"]
    assert shop.requests == []


def test_the_job_reports_failure_when_nothing_could_be_synced(db, world, shop):
    connect_in_db(db, world.site_a)
    shop.deny_orders = True
    result = asyncio.run(run_job("shopify_sync", "test"))
    assert result["status"] == "error" and "read_orders" in result["message"]


def test_one_broken_store_does_not_stop_the_others(db, world, shop):
    connect_in_db(db, world.site_a, mode="token", access_token="shpat_wrong_token")
    connect_in_db(db, world.site_b)
    shop.orders = [node(1)]
    result = asyncio.run(run_job("shopify_sync", "test"))
    assert result["status"] == "ok" and "Synced 1 of 2" in result["message"]
    assert len(stored(db, world.site_b)) == 1
