"""Plans with a recordings ("videos") limit, a first-month price, usage left, and prices worked out from PostHog's price + our commission."""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from app import pricing
from app.billing.limits import evaluate_usage_limits
from app.billing.service import (
    billed_month_number,
    first_billing_date,
    generate_due_invoices,
    invoice_price_for,
    next_invoice_start,
    void_invoice,
)
from app.models import Alert, AuditLog, Invoice, Subscription, UsageDaily

from .test_billing import ALL_FEATURES, NO_FEATURES, invoices_of, make_plan, subscribe

BACKEND_DIR = Path(__file__).resolve().parent.parent


def today():
    return datetime.now(timezone.utc).date()


def add_usage(db, website, *, events=0, recordings=0, day=None):
    db.add(UsageDaily(website_id=website.id, day=day or today(), events=events, recordings=recordings))
    db.commit()


def set_currency(db, client, currency):
    client.currency = currency
    db.merge(client)
    db.commit()


# ------------------------------------------------------------------ the price formula (PostHog's price + our commission)


def quote(events, recordings, *, base=30.0, commission=30.0, rate=280.0):
    return pricing.suggest_price(events, recordings, base_usd=base, commission_percent=commission, usd_to_pkr=rate)


def test_a_plan_inside_the_free_allowance_costs_just_the_base_price():
    q = quote(1_000_000, 5_000)
    assert q["provider_usd"] == 0 and q["commission_usd"] == 0
    assert (q["suggested_usd"], q["suggested_pkr"]) == (30, 8400)


@pytest.mark.parametrize("events, recordings, provider, usd, pkr", [
    (2_000_000, 5_000, 50.0, 95, 26_600),       # 1M extra events: $50, +30% = $65, + $30 base
    (1_500_000, 10_000, 50.0, 95, 26_600),      # $25 of events + $25 of recordings
    (1_000_000, 15_000, 50.0, 95, 26_600),      # 10,000 extra recordings x $0.005
    (3_000_000, 25_000, 169.3, 251, 70_300),    # 250.09 is rounded UP to a whole dollar; 70,280 rupees up to the next 100
])
def test_the_suggested_price_adds_posthogs_price_above_the_free_part_plus_the_commission(events, recordings, provider, usd, pkr):
    q = quote(events, recordings)
    assert q["provider_usd"] == pytest.approx(provider) and q["suggested_usd"] == usd and q["suggested_pkr"] == pkr


def test_the_commission_and_the_base_price_change_the_suggestion():
    assert quote(2_000_000, 5_000, commission=0)["suggested_usd"] == 80      # 30 + 50
    assert quote(2_000_000, 5_000, commission=100)["suggested_usd"] == 130   # 30 + 50 x 2
    assert quote(1_000_000, 5_000, base=45)["suggested_usd"] == 45
    assert quote(2_000_000, 5_000, commission=30)["commission_usd"] == pytest.approx(15.0)


def test_extra_usage_is_priced_from_where_the_plan_ends():
    assert pricing.overage_cost(1_400_000, 1_000_000, pricing.EVENT_TIERS) == pytest.approx(400_000 * 0.00005)
    assert pricing.overage_cost(6_000, 5_000, pricing.RECORDING_TIERS) == pytest.approx(1_000 * 0.005)
    assert pricing.overage_cost(900_000, 1_000_000, pricing.EVENT_TIERS) == 0          # under the limit
    assert pricing.overage_cost(5_000_000, None, pricing.EVENT_TIERS) == 0             # an unlimited plan has no "extra"
    assert pricing.overage_cost(150_000, 100_000, pricing.EVENT_TIERS) == 0            # still inside PostHog's free million
    # a bigger bite is cheaper per event, like at PostHog (tier 3 starts after 2M events)
    assert pricing.overage_cost(3_000_000, 2_000_000, pricing.EVENT_TIERS) == pytest.approx(1_000_000 * 0.0000343)


def test_the_example_plans_that_come_with_the_app_follow_the_formula(tmp_path):
    """Migration 0010 rebuilds Starter / Growth / Pro: their prices must be what the formula suggests (30% commission, $30 base, 280 rupees a dollar)."""
    url = f"sqlite:///{(tmp_path / 'examples.db').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT slug, price_usd, price_pkr, intro_price_usd, intro_price_pkr, monthly_event_limit, monthly_recording_limit, features FROM plans ORDER BY sort_order"
        )).all()
    engine.dispose()
    assert [r[0] for r in rows] == ["starter", "growth", "pro"]
    for slug, usd, pkr, _intro_usd, _intro_pkr, events, recordings, _features in rows:
        suggested = quote(events, recordings)
        assert (float(usd), float(pkr)) == (suggested["suggested_usd"], suggested["suggested_pkr"]), slug
    starter = rows[0]
    assert (float(starter[3]), float(starter[4])) == (20.0, 5600.0)  # first month $20, then $30
    assert (starter[5], starter[6]) == (pricing.FREE_EVENTS, pricing.FREE_RECORDINGS)  # what PostHog gives away free
    assert json.loads(starter[7])["recordings"] is True  # a plan with 5,000 videos must be allowed to show them
    assert json.loads(starter[7])["team_members"] is True  # ...and Starter clients can add a teammate


# ------------------------------------------------------------------ dollars by default


def test_new_clients_are_billed_in_dollars_by_default(api, db, world):
    admin = api("admin@agency.test")
    made = admin.post("/api/admin/clients", json={"name": "Fresh Shop"})
    assert made.status_code == 201 and made.json()["currency"] == "USD"
    assert admin.patch(f"/api/admin/clients/{made.json()['id']}", json={"currency": "PKR"}).json()["currency"] == "PKR"  # rupees stay possible, per client


def _run_migrations(tmp_path, *, until, then=None, setup=None):
    """Build a throwaway database up to revision `until`, let `setup` put rows in, then upgrade to `then`. Returns the engine."""
    url = f"sqlite:///{(tmp_path / 'steps.db').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, until)
    engine = create_engine(url)
    if setup:
        with engine.begin() as connection:
            setup(connection)
    if then:
        command.upgrade(config, then)
    return engine


@pytest.mark.parametrize("customised", [False, True])
def test_migration_0011_only_switches_clients_that_can_safely_change_currency_and_untouched_examples(tmp_path, customised):
    ids = {key: uuid.uuid4().hex for key in ("free", "billed", "special", "invoice", "subscription")}

    def setup(connection):
        plan_id = connection.execute(text("SELECT id FROM plans WHERE slug = 'starter'")).scalar()
        for name, key in (("No invoices yet", "free"), ("Has an invoice", "billed"), ("Has a special price", "special")):
            connection.execute(text("INSERT INTO clients (id, name, currency) VALUES (:id, :name, 'PKR')"), {"id": ids[key], "name": name})
        connection.execute(
            text("INSERT INTO invoices (id, number, client_id, issue_date, due_date, currency, amount, line_items) VALUES (:id, 'INV-2026-0001', :client, '2026-10-01', '2026-10-08', 'PKR', 100, '[]')"),
            {"id": ids["invoice"], "client": ids["billed"]},
        )
        connection.execute(
            text("INSERT INTO subscriptions (id, client_id, plan_id, started_at, price_override) VALUES (:id, :client, :plan, '2026-10-01', 5500)"),
            {"id": ids["subscription"], "client": ids["special"], "plan": plan_id},
        )
        if customised:  # the admin already made Starter their own
            connection.execute(text("UPDATE plans SET description = 'My own Starter' WHERE slug = 'starter'"))

    engine = _run_migrations(tmp_path, until="0010", then="0011", setup=setup)
    with engine.connect() as connection:
        currencies = dict(connection.execute(text("SELECT name, currency FROM clients")).all())
        features = json.loads(connection.execute(text("SELECT features FROM plans WHERE slug = 'starter'")).scalar())
        growth = json.loads(connection.execute(text("SELECT features FROM plans WHERE slug = 'growth'")).scalar())
    engine.dispose()
    # a client with an invoice can't change currency; a special price is an amount IN the client's currency, so it must not silently change meaning
    assert currencies == {"No invoices yet": "USD", "Has an invoice": "PKR", "Has a special price": "PKR"}
    assert features["team_members"] is (False if customised else True) and features["recordings"] is True
    assert growth["team_members"] is True  # (the other examples are not touched)


# ------------------------------------------------------------------ first month price


def test_the_first_month_costs_the_introductory_price_then_the_normal_price(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600")
    set_currency(db, world.client_a, "USD")
    subscribe(db, world.client_a, plan)
    [first] = generate_due_invoices(db, date(2026, 10, 14))
    assert first.amount == Decimal("20.00") and first.currency == "USD"
    assert "first month price" in first.line_items[0]["description"] and first.line_items[0]["amount"] == "20.00"
    [second] = generate_due_invoices(db, date(2026, 11, 14))
    assert second.amount == Decimal("30.00") and "first month" not in second.line_items[0]["description"]
    [third] = generate_due_invoices(db, date(2026, 12, 14))
    assert third.amount == Decimal("30.00")


def test_each_currency_has_its_own_introductory_price(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600")
    subscribe(db, world.client_a, plan)  # PKR
    [pkr] = generate_due_invoices(db, date(2026, 10, 14))
    assert (pkr.currency, pkr.amount) == ("PKR", Decimal("5600.00"))

    only_usd = make_plan(db, name="Only USD", usd="30", pkr="8400", intro_usd="20")  # no PKR intro price: PKR clients pay the normal price
    subscribe(db, world.client_b, only_usd)
    [other] = generate_due_invoices(db, date(2026, 10, 14))
    assert (other.currency, other.amount) == ("PKR", Decimal("8400.00"))


def test_the_introductory_price_can_last_more_than_one_month(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600", intro_months=2)
    subscribe(db, world.client_a, plan)
    amounts = [generate_due_invoices(db, date(2026, m, 14))[0] for m in (10, 11, 12)]
    assert [i.amount for i in amounts] == [Decimal("5600.00"), Decimal("5600.00"), Decimal("8400.00")]
    assert "introductory price" in amounts[0].line_items[0]["description"] and "introductory" not in amounts[2].line_items[0]["description"]


def test_a_special_price_for_one_client_beats_the_introductory_price(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600")
    subscribe(db, world.client_a, plan, override="4000")
    [invoice] = generate_due_invoices(db, date(2026, 10, 14))
    assert invoice.amount == Decimal("4000.00") and "first month" not in invoice.line_items[0]["description"]


def test_a_free_first_month_is_not_free_forever(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="0", intro_pkr="0")
    subscribe(db, world.client_a, plan)
    assert generate_due_invoices(db, date(2026, 10, 14)) == []  # nothing to pay in the first month, so no invoice
    [second] = generate_due_invoices(db, date(2026, 11, 14))
    assert second.amount == Decimal("8400.00")  # the second month is counted by the calendar, not by invoices


def test_cancelling_the_first_invoice_does_not_give_another_cheap_month(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600")
    subscribe(db, world.client_a, plan)
    [first] = generate_due_invoices(db, date(2026, 10, 14))
    void_invoice(db, first)
    [second] = generate_due_invoices(db, date(2026, 11, 14))
    assert second.amount == Decimal("8400.00")


def test_changing_plans_later_does_not_start_a_new_introductory_month(db, world):
    old, new = make_plan(db, name="Old", usd="30", pkr="8400"), make_plan(db, name="New", usd="95", pkr="26600", intro_usd="50", intro_pkr="14000")
    sub = subscribe(db, world.client_a, old)
    generate_due_invoices(db, date(2026, 10, 14))
    generate_due_invoices(db, date(2026, 11, 14))
    sub.plan = new
    db.commit()
    [third] = generate_due_invoices(db, date(2026, 12, 14))
    assert third.amount == Decimal("26600.00")  # an upgrade in month 3 pays the new plan's normal price


def test_billed_months_are_counted_from_the_first_invoice_day(db, world):
    plan = make_plan(db)
    for started, day, first in [
        (date(2026, 10, 14), 14, date(2026, 10, 14)),   # starts on the billing day
        (date(2026, 10, 3), 14, date(2026, 10, 14)),    # starts before it
        (date(2026, 10, 20), 14, date(2026, 11, 14)),   # starts after it: the first invoice is next month
        (date(2026, 12, 20), 14, date(2027, 1, 14)),    # ...across the year
    ]:
        sub = Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=started, billing_day=day, status="cancelled")
        assert first_billing_date(sub) == first
        assert billed_month_number(sub, first) == 1
        assert billed_month_number(sub, date(first.year + (first.month // 12), first.month % 12 + 1, day)) == 2


def test_the_next_invoice_is_known_in_advance(db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600")
    sub = subscribe(db, world.client_a, plan)  # started 14 Oct, billing day 14
    assert next_invoice_start(db, sub, date(2026, 10, 10)) == date(2026, 10, 14)   # billing hasn't begun
    assert next_invoice_start(db, sub, date(2026, 10, 14)) == date(2026, 10, 14)   # due today, the daily job just hasn't run yet
    assert invoice_price_for(world.client_a, sub, date(2026, 10, 14)) == (Decimal("5600.00"), True)
    generate_due_invoices(db, date(2026, 10, 14))
    assert next_invoice_start(db, sub, date(2026, 10, 14)) == date(2026, 11, 14)
    assert next_invoice_start(db, sub, date(2026, 10, 25)) == date(2026, 11, 14)
    assert invoice_price_for(world.client_a, sub, date(2026, 11, 14)) == (Decimal("8400.00"), False)


def test_the_billing_page_tells_the_client_what_the_next_invoice_costs(api, db, world):
    plan = make_plan(db, usd="30", pkr="8400", intro_usd="20", intro_pkr="5600")
    set_currency(db, world.client_a, "USD")
    subscribe(db, world.client_a, plan, started=today() + timedelta(days=40), billing_day=5)  # billing starts in the future
    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()
    assert body["plan"]["price"] == 30.0 and body["plan"]["intro_price"] == 20.0 and body["plan"]["intro_months"] == 1
    assert body["subscription"]["next_invoice_amount"] == 20.0 and body["subscription"]["next_invoice_is_intro"] is True
    assert date.fromisoformat(body["subscription"]["next_invoice_date"]) >= today() + timedelta(days=40)

    old = db.scalar(select(Subscription).where(Subscription.client_id == world.client_a.id))
    old.started_at, old.billing_day = date(2025, 1, 1), 1  # an old customer: long past the introductory month
    db.commit()
    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()
    assert body["subscription"]["next_invoice_amount"] == 30.0 and body["subscription"]["next_invoice_is_intro"] is False

    old.price_override = Decimal("12")
    db.commit()
    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()
    assert body["plan"]["intro_price"] is None and body["subscription"]["next_invoice_amount"] == 12.0  # a special price replaces the intro


# ------------------------------------------------------------------ how much is left (events and recordings)


def test_the_billing_page_shows_total_used_and_left_for_events_and_recordings(api, db, world):
    plan = make_plan(db, events=1_000_000, recordings=5_000)
    subscribe(db, world.client_a, plan)
    add_usage(db, world.site_a, events=250_000, recordings=1_200)
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]
    assert (usage["events"], usage["event_limit"], usage["event_remaining"], usage["event_over"], usage["percent"]) == (250_000, 1_000_000, 750_000, 0, 25.0)
    assert (usage["recordings"], usage["recording_limit"], usage["recording_remaining"], usage["recording_over"], usage["recording_percent"]) == (1_200, 5_000, 3_800, 0, 24.0)
    assert usage["updated_at"] is not None  # when the counts were last refreshed


def test_over_the_limit_shows_how_far_over_and_nothing_left(api, db, world):
    plan = make_plan(db, events=1_000, recordings=100)
    subscribe(db, world.client_a, plan)
    add_usage(db, world.site_a, events=1_200, recordings=140)
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]
    assert (usage["event_remaining"], usage["event_over"]) == (0, 200) and (usage["recording_remaining"], usage["recording_over"]) == (0, 40)


def test_unlimited_and_no_plan_have_no_remaining_amount(api, db, world):
    add_usage(db, world.site_a, events=300, recordings=9)
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]  # no plan at all
    assert (usage["events"], usage["recordings"]) == (300, 9)
    assert usage["event_limit"] is None and usage["event_remaining"] is None and usage["recording_limit"] is None and usage["recording_remaining"] is None
    subscribe(db, world.client_a, make_plan(db, events=None, recordings=None))
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]
    assert usage["event_remaining"] is None and usage["recording_remaining"] is None and usage["recording_over"] == 0


def test_usage_of_all_the_clients_websites_is_added_up_and_other_clients_are_not_mixed_in(api, db, world):
    from .conftest import make_website

    subscribe(db, world.client_a, make_plan(db, events=1_000, recordings=100))
    second = make_website(db, world.client_a, project_id=1111, api_key="phx_second")
    db.commit()
    add_usage(db, world.site_a, events=100, recordings=10)
    add_usage(db, second, events=50, recordings=5)
    add_usage(db, world.site_b, events=9_999, recordings=999)
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]
    assert (usage["events"], usage["recordings"]) == (150, 15)


def test_only_this_month_counts(api, db, world):
    subscribe(db, world.client_a, make_plan(db, events=1_000, recordings=100))
    last_month = today().replace(day=1) - timedelta(days=1)
    add_usage(db, world.site_a, events=700, recordings=70, day=last_month)
    add_usage(db, world.site_a, events=30, recordings=3)
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]
    assert (usage["events"], usage["recordings"]) == (30, 3)


def test_a_client_never_sees_the_providers_price_or_your_commission(api, db, world):
    plan = make_plan(db, events=1_000_000, recordings=5_000, intro_pkr="5600")
    subscribe(db, world.client_a, plan)
    add_usage(db, world.site_a, events=2_000_000, recordings=9_000)
    text_ = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").text.lower()
    for word in ("posthog", "commission", "provider", "quote", "suggested"):
        assert word not in text_, word


# ------------------------------------------------------------------ the plans a client can choose from (their Billing page)


def test_the_billing_page_lists_the_plans_on_offer_in_the_clients_currency(api, db, world):
    starter = make_plan(db, name="Starter", usd="30", pkr="8400", intro_usd="20", intro_pkr="5600", events=1_000_000, recordings=5_000,
                        websites=1, members=2, features={**NO_FEATURES, "recordings": True})
    make_plan(db, name="Big", usd="95", pkr="26600", events=None, recordings=None, websites=None, members=None, features=dict(ALL_FEATURES))
    make_plan(db, name="Retired", active=False)
    starter.description = "Best for a small shop"
    db.commit()
    subscribe(db, world.client_a, starter)

    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()
    plans = {p["name"]: p for p in body["available_plans"]}
    assert list(plans) == ["Big", "Starter"]  # only plans that are for sale, in the plans' order
    assert body["plan"]["id"] == plans["Starter"]["id"]  # the page marks the one the client is on
    assert plans["Starter"] == {
        "id": plans["Starter"]["id"], "name": "Starter", "description": "Best for a small shop", "price": 8400.0, "intro_price": 5600.0, "intro_months": 1,
        "monthly_event_limit": 1_000_000, "monthly_recording_limit": 5_000, "max_websites": 1, "max_team_members": 2,
        "features": {**NO_FEATURES, "recordings": True},
    }
    assert plans["Big"]["price"] == 26600.0 and plans["Big"]["intro_price"] is None
    assert plans["Big"]["monthly_event_limit"] is None and plans["Big"]["max_websites"] is None and plans["Big"]["features"] == ALL_FEATURES  # unlimited

    set_currency(db, world.client_a, "USD")
    usd = {p["name"]: p for p in api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["available_plans"]}
    assert (usd["Starter"]["price"], usd["Starter"]["intro_price"], usd["Big"]["price"]) == (30.0, 20.0, 95.0)


def test_a_client_without_a_plan_still_sees_what_they_could_choose(api, db, world):
    make_plan(db, name="Starter")
    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()
    assert body["plan"] is None and [p["name"] for p in body["available_plans"]] == ["Starter"]


def test_the_note_that_marks_an_example_plan_is_never_shown_to_clients(api, db, world):
    plan = make_plan(db, name="Starter")
    plan.description = "EXAMPLE plan (edit the price): everything the free allowance covers"
    db.commit()
    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing")
    assert body.json()["available_plans"][0]["description"] is None and "EXAMPLE" not in body.text


def test_the_plans_a_client_sees_carry_no_internal_numbers(api, db, world):
    make_plan(db, name="Starter", events=1_000_000, recordings=5_000, intro_pkr="5600")
    make_plan(db, name="Big", events=3_000_000, recordings=25_000)
    text_ = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").text.lower()
    for word in ("posthog", "commission", "provider", "quote", "suggested", "base_usd", "price_usd", "price_pkr", "clients"):
        assert word not in text_, word


def test_only_the_account_owner_sees_the_plans(api, db, world):
    make_plan(db, name="Starter")
    path = f"/api/clients/{world.client_a.id}/billing"
    assert api("vera@a.test").get(path).status_code == 403 and api("bob@b.test").get(path).status_code == 404 and api().get(path).status_code == 401
    admin_view = api("admin@agency.test").get(f"/api/admin/clients/{world.client_a.id}/billing").json()
    assert "available_plans" not in admin_view  # the admin has the Plans page; only the client's own answer carries the list


# ------------------------------------------------------------------ alerts for recordings


def test_recording_alerts_warn_then_escalate_then_clear_on_their_own(db, world):
    subscribe(db, world.client_a, make_plan(db, events=1_000_000, recordings=100))

    def put(events, recordings):
        db.query(UsageDaily).delete()
        db.add(UsageDaily(website_id=world.site_a.id, day=today(), events=events, recordings=recordings))
        db.commit()

    def open_alerts():
        db.expire_all()
        return {a.dedupe_key.split(":", 2)[2]: (a.severity, a.message) for a in db.scalars(select(Alert).where(Alert.kind == "usage_limit", Alert.status == "open"))}

    put(10, 50)
    assert evaluate_usage_limits(db) == {"warning": [], "over": []} and open_alerts() == {}
    put(10, 85)
    assert evaluate_usage_limits(db)["warning"] == ["Client A (recordings)"]
    [(key, (severity, message))] = open_alerts().items()
    assert key == "rec:warn" and severity == "warning" and "85 of the 100 recordings (videos)" in message
    put(10, 130)
    assert evaluate_usage_limits(db)["over"] == ["Client A (recordings)"]
    assert list(open_alerts()) == ["rec:over"] and "extra-usage invoice" in open_alerts()["rec:over"][1]
    put(10, 5)
    evaluate_usage_limits(db)
    assert open_alerts() == {}


def test_event_and_recording_alerts_do_not_hide_each_other(db, world):
    subscribe(db, world.client_a, make_plan(db, events=1_000, recordings=100))
    add_usage(db, world.site_a, events=1_500, recordings=90)
    result = evaluate_usage_limits(db)
    assert result["over"] == ["Client A"] and result["warning"] == ["Client A (recordings)"]
    assert {a.dedupe_key.split(":", 2)[2] for a in db.scalars(select(Alert).where(Alert.status == "open"))} == {"over", "rec:warn"}


def test_a_plan_without_a_recording_limit_never_raises_a_recording_alert(db, world):
    subscribe(db, world.client_a, make_plan(db, events=1_000, recordings=None))
    add_usage(db, world.site_a, events=10, recordings=50_000)
    assert evaluate_usage_limits(db) == {"warning": [], "over": []}


# ------------------------------------------------------------------ the Plans page (admin)


def test_a_plan_can_have_a_recording_limit_and_a_first_month_price(api, db, world):
    admin = api("admin@agency.test")
    made = admin.post("/api/admin/plans", json={
        "name": "Starter 2", "price_usd": 30, "price_pkr": 8400, "intro_price_usd": 20, "intro_price_pkr": 5600,
        "monthly_event_limit": 1_000_000, "monthly_recording_limit": 5_000, "features": {"recordings": True},
    })
    assert made.status_code == 201
    plan = made.json()
    assert plan["monthly_recording_limit"] == 5_000 and plan["intro_price_usd"] == 20.0 and plan["intro_price_pkr"] == 5600.0 and plan["intro_months"] == 1
    assert plan["quote"]["suggested_usd"] == 30 and plan["quote"]["provider_usd"] == 0  # the free allowance: the base price

    changed = admin.patch(f"/api/admin/plans/{plan['id']}", json={"monthly_recording_limit": 15_000, "intro_months": 3}).json()
    assert changed["monthly_recording_limit"] == 15_000 and changed["intro_months"] == 3
    assert changed["quote"]["provider_recordings_usd"] == 50.0 and changed["quote"]["suggested_usd"] == 95  # 10,000 extra recordings
    assert changed["intro_price_usd"] == 20.0  # not mentioned, so untouched

    cleared = admin.patch(f"/api/admin/plans/{plan['id']}", json={"intro_price_usd": None, "intro_price_pkr": None, "monthly_recording_limit": None}).json()
    assert cleared["intro_price_usd"] is None and cleared["intro_price_pkr"] is None and cleared["monthly_recording_limit"] is None
    assert cleared["quote"] is None  # unlimited: nothing to price
    listed = {p["slug"]: p for p in admin.get("/api/admin/plans").json()["results"]}
    assert listed[plan["slug"]]["quote"] is None


def test_a_first_month_price_above_the_normal_price_is_refused(api, db, world):
    admin = api("admin@agency.test")
    assert admin.post("/api/admin/plans", json={"name": "Typo", "price_usd": 30, "intro_price_usd": 200}).status_code == 400
    assert admin.post("/api/admin/plans", json={"name": "Typo", "price_pkr": 8400, "intro_price_pkr": 9000}).status_code == 400
    plan = admin.post("/api/admin/plans", json={"name": "Fine", "price_usd": 30, "price_pkr": 8400, "intro_price_usd": 30}).json()  # equal is allowed
    bad = admin.patch(f"/api/admin/plans/{plan['id']}", json={"intro_price_usd": 31})
    assert bad.status_code == 400 and "can't be higher" in bad.json()["detail"]
    admin.patch(f"/api/admin/plans/{plan['id']}", json={"price_usd": 10, "name": "Renamed"})  # lowering the normal price below the intro price
    again = {p["slug"]: p for p in admin.get("/api/admin/plans").json()["results"]}
    assert again["fine"]["name"] == "Fine" and again["fine"]["price_usd"] == 30.0  # the refused edit changed nothing


@pytest.mark.parametrize("body", [
    {"intro_months": 0}, {"intro_months": 13}, {"monthly_recording_limit": 0}, {"monthly_recording_limit": -5}, {"intro_price_usd": -1},
])
def test_nonsense_plan_numbers_are_refused(body, api, db, world):
    assert api("admin@agency.test").post("/api/admin/plans", json={"name": "Odd", **body}).status_code == 422


def test_the_price_calculator_uses_your_commission_and_base_price(api, db, world):
    admin = api("admin@agency.test")
    q = admin.get("/api/admin/pricing/quote", params={"events": 2_000_000, "recordings": 5_000}).json()
    assert q["provider_usd"] == 50.0 and q["commission_percent"] == 30.0 and q["commission_usd"] == 15.0 and q["suggested_usd"] == 95 and q["suggested_pkr"] == 26_600
    assert admin.patch("/api/admin/settings", json={"values": {"billing.commission_percent": 50, "billing.base_price_usd": 40, "billing.usd_to_pkr": 300}}).status_code == 200
    q = admin.get("/api/admin/pricing/quote", params={"events": 2_000_000, "recordings": 5_000}).json()
    assert q["commission_usd"] == 25.0 and q["suggested_usd"] == 115 and q["suggested_pkr"] == 34_500 and q["usd_to_pkr"] == 300.0
    assert admin.patch("/api/admin/settings", json={"values": {"billing.commission_percent": -1}}).status_code == 400
    assert admin.patch("/api/admin/settings", json={"values": {"billing.commission_percent": "lots"}}).status_code == 400


def test_the_price_calculator_needs_both_amounts_and_an_admin(api, db, world):
    admin = api("admin@agency.test")
    assert admin.get("/api/admin/pricing/quote", params={"events": 1_000_000}).status_code == 422
    assert admin.get("/api/admin/pricing/quote", params={"events": 0, "recordings": 5}).status_code == 422
    path = "/api/admin/pricing/quote?events=1000000&recordings=5000"
    assert api("alice@a.test").get(path).status_code == 403 and api().get(path).status_code == 401


# ------------------------------------------------------------------ extra usage: over the plan, priced at PostHog + commission


def extra_url(client, suffix="extra-usage"):
    return f"/api/admin/clients/{client.id}/{suffix}"


def over_the_limit(db, world, *, currency="PKR"):
    """Starter: 1,000,000 events and 5,000 recordings. This month: 400,000 events and 1,000 recordings too many."""
    set_currency(db, world.client_a, currency)
    subscribe(db, world.client_a, make_plan(db, name="Starter", events=1_000_000, recordings=5_000))
    add_usage(db, world.site_a, events=1_400_000, recordings=6_000)


def test_extra_usage_is_priced_at_the_providers_price_plus_the_commission(api, db, world):
    over_the_limit(db, world, currency="USD")
    info = api("admin@agency.test").get(extra_url(world.client_a)).json()
    assert info["month"] == today().strftime("%Y-%m") and info["plan"] == "Starter" and info["commission_percent"] == 30.0
    assert info["events"] == {"used": 1_400_000, "included": 1_000_000, "over": 400_000, "provider_usd": 20.0, "amount": 26.0}      # 400,000 x $0.00005 = $20, +30%
    assert info["recordings"] == {"used": 6_000, "included": 5_000, "over": 1_000, "provider_usd": 5.0, "amount": 6.5}              # 1,000 x $0.005 = $5, +30%
    assert info["provider_usd"] == 25.0 and info["amount"] == 32.5 and info["can_invoice"] is True and info["already_invoiced"] is None
    assert [line["amount"] for line in info["lines"]] == ["26.00", "6.50"]
    assert "Extra events" in info["lines"][0]["description"] and "400,000 above the 1,000,000" in info["lines"][0]["description"]


def test_extra_usage_for_a_rupee_client_uses_the_dollar_rate(api, db, world):
    over_the_limit(db, world, currency="PKR")
    info = api("admin@agency.test").get(extra_url(world.client_a)).json()
    assert info["currency"] == "PKR" and info["events"]["amount"] == 7_280.0 and info["recordings"]["amount"] == 1_820.0 and info["amount"] == 9_100.0  # x 280


def test_one_click_creates_the_extra_usage_invoice_once_per_month(api, db, world):
    over_the_limit(db, world)
    admin = api("admin@agency.test")
    made = admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={})
    assert made.status_code == 201
    invoice = made.json()
    assert invoice["amount"] == 9_100.0 and invoice["currency"] == "PKR" and invoice["source"] == "usage" and invoice["status"] == "open"
    assert sum(float(line["amount"]) for line in invoice["line_items"]) == invoice["amount"]  # the lines add up to the total
    first = today().replace(day=1)
    assert invoice["period_start"] == first.isoformat() and date.fromisoformat(invoice["period_end"]).month == first.month
    assert admin.get("/api/admin/invoices", params={"client_id": str(world.client_a.id)}).json()["results"][0]["number"] == invoice["number"]

    again = admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={})
    assert again.status_code == 409 and invoice["number"] in again.json()["detail"]
    info = admin.get(extra_url(world.client_a)).json()
    assert info["can_invoice"] is False and info["already_invoiced"]["number"] == invoice["number"]

    admin.post(f"/api/admin/invoices/{invoice['id']}/void")  # a cancelled one doesn't count: it can be made again
    assert admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={}).status_code == 201

    db.expire_all()
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "admin.invoice_created").order_by(AuditLog.created_at.desc())).first()
    assert entry.details["source"] == "usage"


def test_the_client_sees_the_extra_usage_invoice_without_any_mention_of_posthog_or_commission(api, db, world):
    over_the_limit(db, world)
    api("admin@agency.test").post(extra_url(world.client_a, "extra-usage-invoice"), json={})
    body = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").text.lower()
    assert "extra events" in body and "posthog" not in body and "commission" not in body


def test_no_invoice_without_extra_usage(api, db, world):
    subscribe(db, world.client_a, make_plan(db, name="Starter", events=1_000_000, recordings=5_000))
    add_usage(db, world.site_a, events=900_000, recordings=4_000)
    admin = api("admin@agency.test")
    info = admin.get(extra_url(world.client_a)).json()
    assert info["can_invoice"] is False and info["lines"] == [] and info["amount"] == 0 and info["events"]["over"] == 0
    refused = admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={})
    assert refused.status_code == 409 and "no extra usage" in refused.json()["detail"]
    assert invoices_of(db, world.client_a) == []


def test_extra_usage_inside_the_providers_free_allowance_costs_nothing(api, db, world):
    subscribe(db, world.client_a, make_plan(db, name="Small", events=100_000, recordings=1_000))
    add_usage(db, world.site_a, events=150_000, recordings=1_000)  # over THIS plan, but PostHog's free million still covers it
    admin = api("admin@agency.test")
    info = admin.get(extra_url(world.client_a)).json()
    assert info["events"]["over"] == 50_000 and info["events"]["amount"] == 0 and info["can_invoice"] is False
    assert admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={}).status_code == 409


def test_a_client_with_no_plan_or_an_unlimited_plan_has_no_extra_usage(api, db, world):
    add_usage(db, world.site_a, events=5_000_000, recordings=90_000)
    admin = api("admin@agency.test")
    assert admin.get(extra_url(world.client_a)).json()["plan"] is None
    assert admin.get(extra_url(world.client_a)).json()["can_invoice"] is False
    subscribe(db, world.client_a, make_plan(db, events=None, recordings=None))
    info = admin.get(extra_url(world.client_a)).json()
    assert info["plan"] == "Growth" and info["amount"] == 0 and info["can_invoice"] is False


def test_extra_usage_of_last_month_can_still_be_invoiced(api, db, world):
    subscribe(db, world.client_a, make_plan(db, name="Starter", events=1_000_000, recordings=5_000))
    last_month = today().replace(day=1) - timedelta(days=1)
    add_usage(db, world.site_a, events=1_200_000, recordings=5_000, day=last_month)
    admin = api("admin@agency.test")
    month = last_month.strftime("%Y-%m")
    assert admin.get(extra_url(world.client_a)).json()["can_invoice"] is False  # this month is fine
    info = admin.get(extra_url(world.client_a), params={"month": month}).json()
    assert info["month"] == month and info["events"]["over"] == 200_000 and info["amount"] == pytest.approx(200_000 * 0.00005 * 1.3 * 280)
    made = admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={"month": month})
    assert made.status_code == 201 and made.json()["period_start"] == last_month.replace(day=1).isoformat()
    assert admin.post(extra_url(world.client_a, "extra-usage-invoice"), json={"month": "2026-13"}).status_code == 422
    assert admin.get(extra_url(world.client_a), params={"month": "nope"}).status_code == 422


def test_extra_usage_is_admin_only_and_never_crosses_clients(api, db, world):
    over_the_limit(db, world)
    for method, suffix in (("get", "extra-usage"), ("post", "extra-usage-invoice")):
        for who in ("alice@a.test", "bob@b.test", "vera@a.test"):  # the client's own owner and viewer, and another client's owner
            response = getattr(api(who), method)(extra_url(world.client_a, suffix), **({"json": {}} if method == "post" else {}))
            assert response.status_code == 403, (who, suffix)
        assert getattr(api(), method)(extra_url(world.client_a, suffix), **({"json": {}} if method == "post" else {})).status_code == 401
    assert api("admin@agency.test").get(f"/api/admin/clients/{uuid.UUID(int=0)}/extra-usage").status_code == 404
    assert invoices_of(db, world.client_a) == []


def test_extra_usage_only_counts_the_clients_own_websites(api, db, world):
    over_the_limit(db, world)
    add_usage(db, world.site_b, events=50_000_000, recordings=900_000)  # someone else's traffic
    info = api("admin@agency.test").get(extra_url(world.client_a)).json()
    assert info["events"]["used"] == 1_400_000 and info["recordings"]["used"] == 6_000
    assert Invoice  # (imported for clarity)
