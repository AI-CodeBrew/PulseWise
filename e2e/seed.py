"""
Seeds a THROWAWAY database for the browser tests (e2e/run.ps1 sets DATABASE_URL to a SQLite file first).
Prints the ids it created as JSON on the last line.

Needs the PostHog connection in backend/.env (POSTHOG_HOST / POSTHOG_PROJECT_ID / POSTHOG_PERSONAL_API_KEY)
so the test websites can show real data.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402

assert settings.database_url.startswith("sqlite"), "e2e/seed.py must only run against a throwaway SQLite database"

from datetime import datetime, timedelta, timezone  # noqa: E402

from decimal import Decimal  # noqa: E402

from app.models import Client, ClientMember, Invoice, ShopConnection, ShopOrder, ShopOrderItem, User, Website  # noqa: E402
from app.security import encrypt_secret, hash_password  # noqa: E402

host = os.getenv("POSTHOG_HOST", "https://us.posthog.com")
project_id = int(os.getenv("POSTHOG_PROJECT_ID", "0") or 0)
api_key = os.getenv("POSTHOG_PERSONAL_API_KEY", "")
if not (project_id and api_key):
    sys.exit("Set POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY in backend/.env (or the environment) to run the browser tests.")


def user(db, email, password, name, admin=False):
    u = User(email=email, name=name, password_hash=hash_password(password), is_admin=admin)
    db.add(u)
    db.flush()
    return u


def client_with_site(db, name, site_name, domain):
    c = Client(name=name, contact_email=f"hello@{domain}")
    db.add(c)
    db.flush()
    # Created "10 days ago", so the daily health check treats them as established (new sites get a grace period).
    w = Website(client_id=c.id, name=site_name, domain=domain, posthog_host=host, posthog_project_id=project_id,
                posthog_project_token="phc_e2e_public_token", posthog_api_key_encrypted=encrypt_secret(api_key),
                created_at=datetime.now(timezone.utc) - timedelta(days=10))
    db.add(w)
    db.flush()
    return c, w


with get_sessionmaker()() as db:
    admin = user(db, "admin@e2e.test", "Admin-E2E-Pass-1", "E2E Admin", admin=True)
    demo, demo_site = client_with_site(db, "Demo Shop", "demo-shop.pk", "demo-shop.pk")
    other, other_site = client_with_site(db, "Other Co", "other.example", "other.example")
    owner = user(db, "owner@demo.test", "Owner-E2E-Pass-1", "Demo Owner")
    viewer = user(db, "viewer@demo.test", "Viewer-E2E-Pass-1", "Demo Viewer")
    other_owner = user(db, "other@other.test", "Other-E2E-Pass-1", "Other Owner")
    resetme = user(db, "resetme@demo.test", "Reset-E2E-Pass-1", "Password Reset Test")  # only for the password-reset test
    db.add_all([
        ClientMember(client_id=demo.id, user_id=owner.id, role="owner"),
        ClientMember(client_id=demo.id, user_id=viewer.id, role="viewer"),
        ClientMember(client_id=demo.id, user_id=resetme.id, role="viewer"),
        ClientMember(client_id=other.id, user_id=other_owner.id, role="owner"),
    ])
    db.add(Invoice(
        number="INV-2020-0001", client_id=other.id, source="manual", issue_date=datetime(2020, 1, 1).date(), due_date=datetime(2020, 1, 8).date(),
        currency="PKR", amount=Decimal("5000.00"), line_items=[{"description": "Old unpaid set-up fee", "amount": "5000.00"}],
    ))

    # A pretend Shopify store for Demo Shop: the browser tests can't call the real Shopify, so the orders are put in directly.
    db.add(ShopConnection(website_id=demo_site.id, shop_domain="e2e-shop.myshopify.com", auth_mode="token", shop_name="E2E Shop", currency="PKR",
                          credentials_encrypted=encrypt_secret(json.dumps({"access_token": "shpat_e2e_not_a_real_token"})),
                          last_synced_at=datetime.now(timezone.utc) - timedelta(minutes=20)))
    now = datetime.now(timezone.utc)
    for n in range(1, 31):
        product, price = ("E2E Hoodie", Decimal("2500.00")) if n % 3 else ("E2E Cap", Decimal("900.00"))
        order = ShopOrder(website_id=demo_site.id, shopify_id=f"gid://shopify/Order/{n}", name=f"#{1000 + n}", created_at=now - timedelta(days=n % 25, hours=n),
                          financial_status="PAID", fulfillment_status="UNFULFILLED", currency="PKR", total=price, source_name="pos" if n % 7 == 0 else "web")
        order.items = [ShopOrderItem(website_id=demo_site.id, title=product, quantity=1, amount=price)]
        db.add(order)
    db.commit()
    result = {"demoClient": str(demo.id), "demoSite": str(demo_site.id), "otherClient": str(other.id), "otherSite": str(other_site.id),
              "posthog": {"host": host, "projectId": project_id}}

get_engine().dispose()
print(json.dumps(result))
