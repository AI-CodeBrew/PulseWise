"""Plans, subscriptions, invoices, payments, overdue handling, plan features and limits, payment gateway plug."""

import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import emailer
from app.billing import notifications, providers
from app.billing.limits import evaluate_usage_limits
from app.billing.service import (
    BillingError,
    apply_overdue_rules,
    balance,
    create_invoice,
    generate_due_invoices,
    latest_billing_date,
    money,
    next_billing_date,
    record_payment,
    void_invoice,
)
from app.jobs import run_job
from app.models import Alert, AuditLog, Client, Invoice, Payment, Plan, Subscription, UsageDaily

from .conftest import PASSWORD, make_client, make_user

ALL_FEATURES = {"sessions": True, "people": True, "live_events": True, "recordings": True, "weekly_reports": True, "shopify": True, "team_members": True}
NO_FEATURES = {k: False for k in ALL_FEATURES}


def make_plan(db, name="Growth", pkr="8000", usd="29", events=500_000, websites=3, members=3, features=None, active=True,
              recordings=None, intro_usd=None, intro_pkr=None, intro_months=1):
    plan = Plan(name=name, slug=name.lower(), price_pkr=Decimal(pkr), price_usd=Decimal(usd), monthly_event_limit=events, monthly_recording_limit=recordings,
                intro_price_usd=Decimal(intro_usd) if intro_usd is not None else None, intro_price_pkr=Decimal(intro_pkr) if intro_pkr is not None else None,
                intro_months=intro_months, max_websites=websites, max_team_members=members,
                features=features if features is not None else dict(ALL_FEATURES), is_active=active)
    db.add(plan)
    db.commit()
    return plan


def subscribe(db, client, plan, started=date(2026, 10, 14), billing_day=14, override=None):
    sub = Subscription(client_id=client.id, plan_id=plan.id, started_at=started, billing_day=billing_day,
                       price_override=Decimal(override) if override is not None else None)
    db.add(sub)
    db.commit()
    return sub


def invoices_of(db, client):
    db.expire_all()
    return db.scalars(select(Invoice).where(Invoice.client_id == client.id).order_by(Invoice.number)).all()


@pytest.fixture
def emails(monkeypatch):
    """Email sending is 'configured' and every email is captured."""
    sent = []
    monkeypatch.setattr(emailer, "email_configured", lambda: True)

    def capture(to, subject, body, *, html=None, attachments=None):
        sent.append({"to": to, "subject": subject, "body": body, "attachments": attachments or []})
        return True

    monkeypatch.setattr(emailer, "send_email", capture)
    monkeypatch.setattr("app.alerts.send_email", lambda *a, **k: True)
    return sent


# ------------------------------------------------------------------ billing dates and money


@pytest.mark.parametrize("today, day, expected", [
    (date(2026, 10, 14), 14, date(2026, 10, 14)),
    (date(2026, 10, 20), 14, date(2026, 10, 14)),
    (date(2026, 10, 13), 14, date(2026, 9, 14)),
    (date(2026, 1, 5), 20, date(2025, 12, 20)),  # across the year
    (date(2026, 3, 1), 28, date(2026, 2, 28)),  # short month
])
def test_latest_billing_date(today, day, expected):
    assert latest_billing_date(day, today) == expected


def test_next_billing_date_wraps_the_year():
    assert next_billing_date(14, date(2026, 12, 20)) == date(2027, 1, 14)
    assert next_billing_date(28, date(2026, 1, 31)) == date(2026, 2, 28)


def test_money_rounds_to_cents_exactly():
    assert money("10.005") == Decimal("10.01") and money(0.1 + 0.2) == Decimal("0.30") and money(5) == Decimal("5.00")


# ------------------------------------------------------------------ generating invoices


def test_an_invoice_is_issued_on_the_billing_day_and_only_once(db, world):
    plan = make_plan(db)
    subscribe(db, world.client_a, plan)
    assert generate_due_invoices(db, date(2026, 10, 13)) == []  # not yet
    [invoice] = generate_due_invoices(db, date(2026, 10, 14))
    assert invoice.number == "INV-2026-0001" and invoice.amount == Decimal("8000.00") and invoice.currency == "PKR"
    assert (invoice.period_start, invoice.period_end) == (date(2026, 10, 14), date(2026, 11, 13))
    assert invoice.issue_date == date(2026, 10, 14) and invoice.due_date == date(2026, 10, 21)  # 7 days to pay
    assert invoice.line_items[0]["description"].startswith("Growth plan") and invoice.status == "open" and invoice.source == "auto"

    assert generate_due_invoices(db, date(2026, 10, 14)) == [] and generate_due_invoices(db, date(2026, 10, 20)) == []  # no duplicates
    [second] = generate_due_invoices(db, date(2026, 11, 14))
    assert second.number == "INV-2026-0002" and second.period_start == date(2026, 11, 14)
    assert len(invoices_of(db, world.client_a)) == 2


def test_invoices_use_the_clients_currency_and_special_price(db, world):
    plan = make_plan(db)
    world.client_a.currency = "USD"
    db.merge(world.client_a)
    subscribe(db, world.client_a, plan)
    subscribe(db, world.client_b, plan, override="5500")  # a friend's price, in PKR
    db.commit()
    generate_due_invoices(db, date(2026, 10, 14))
    [usd] = invoices_of(db, world.client_a)
    [special] = invoices_of(db, world.client_b)
    assert (usd.currency, usd.amount) == ("USD", Decimal("29.00")) and (special.currency, special.amount) == ("PKR", Decimal("5500.00"))


def test_nothing_is_billed_before_the_start_date_for_free_plans_or_cancelled_subscriptions(db, world):
    plan = make_plan(db)
    free = make_plan(db, name="Free", pkr="0", usd="0")
    subscribe(db, world.client_a, plan, started=date(2026, 10, 14), billing_day=1)  # billing starts on the 1st AFTER the start
    subscribe(db, world.client_b, free)
    assert generate_due_invoices(db, date(2026, 10, 14)) == []
    assert [i.period_start for i in generate_due_invoices(db, date(2026, 11, 1))] == [date(2026, 11, 1)]
    sub = db.scalar(select(Subscription).where(Subscription.client_id == world.client_a.id))
    sub.status = "cancelled"
    db.commit()
    assert generate_due_invoices(db, date(2026, 12, 1)) == []


def test_a_client_without_a_plan_is_never_invoiced(db, world):
    assert generate_due_invoices(db, date(2026, 10, 14)) == []


def test_invoice_numbers_keep_counting_within_a_year_and_restart_each_year(db, world):
    plan = make_plan(db)
    subscribe(db, world.client_a, plan, started=date(2026, 12, 14))
    subscribe(db, world.client_b, plan, started=date(2026, 12, 14))
    numbers = sorted(i.number for i in generate_due_invoices(db, date(2026, 12, 14)))
    assert numbers == ["INV-2026-0001", "INV-2026-0002"]
    assert [i.number for i in generate_due_invoices(db, date(2027, 1, 14))] == ["INV-2027-0001", "INV-2027-0002"]


def test_a_manual_invoice_must_make_sense(db, world):
    with pytest.raises(BillingError):
        create_invoice(db, world.client_a, amount=Decimal("0"), line_items=[], issue_date=date(2026, 10, 1), due_date=date(2026, 10, 8))
    with pytest.raises(BillingError):
        create_invoice(db, world.client_a, amount=Decimal("5"), line_items=[], issue_date=date(2026, 10, 9), due_date=date(2026, 10, 8))


# ------------------------------------------------------------------ payments


def open_invoice(db, client, amount="8000", due=date(2026, 10, 21)):
    return create_invoice(db, client, amount=Decimal(amount), issue_date=due - timedelta(days=7), due_date=due,
                          line_items=[{"description": "Test", "amount": amount}], source="manual")


def test_partial_and_full_payments(db, world):
    invoice = open_invoice(db, world.client_a)
    record_payment(db, invoice, method="bank_transfer", amount=Decimal("3000"), reference="TX1")
    db.refresh(invoice)
    assert invoice.status == "open" and balance(invoice) == Decimal("5000.00")
    record_payment(db, invoice, method="jazzcash", reference="JC9")  # no amount = the rest
    db.refresh(invoice)
    assert invoice.status == "paid" and invoice.paid_at is not None and balance(invoice) == 0
    assert [(p.amount, p.method) for p in invoice.payments] == [(Decimal("3000.00"), "bank_transfer"), (Decimal("5000.00"), "jazzcash")]


def test_bad_payments_are_refused(db, world):
    invoice = open_invoice(db, world.client_a)
    for bad in (Decimal("0"), Decimal("-5"), Decimal("8000.01")):
        with pytest.raises(BillingError):
            record_payment(db, invoice, method="other", amount=bad)
    record_payment(db, invoice, method="other")
    with pytest.raises(BillingError, match="already paid"):
        record_payment(db, invoice, method="other")


def test_a_gateway_repeating_a_notification_is_recorded_once(db, world):
    invoice = open_invoice(db, world.client_a)
    first = record_payment(db, invoice, method="card", amount=Decimal("1000"), provider="fake", provider_payment_id="pay_1")
    again = record_payment(db, invoice, method="card", amount=Decimal("1000"), provider="fake", provider_payment_id="pay_1")
    assert first.id == again.id and db.scalars(select(Payment)).all().__len__() == 1


def test_only_unpaid_invoices_can_be_cancelled(db, world):
    plain = open_invoice(db, world.client_a)
    void_invoice(db, plain)
    assert plain.status == "void"
    with pytest.raises(BillingError, match="already|cancelled"):
        record_payment(db, plain, method="other")

    part_paid = open_invoice(db, world.client_a)
    record_payment(db, part_paid, method="other", amount=Decimal("100"))
    with pytest.raises(BillingError, match="payments"):
        void_invoice(db, part_paid)


# ------------------------------------------------------------------ overdue invoices and suspension


def test_unpaid_past_the_grace_period_suspends_and_paying_lifts_it(db, world, emails):
    invoice = open_invoice(db, world.client_a, due=date(2026, 10, 21))
    # Due 21 Oct + 7 days grace = suspended from 29 Oct.
    summary = apply_overdue_rules(db, date(2026, 10, 25))
    assert summary["overdue"] == 1 and summary["suspended"] == []
    db.refresh(world.client_a)
    assert world.client_a.status == "active"
    [alert] = db.scalars(select(Alert).where(Alert.kind == "invoice_overdue")).all()
    assert alert.severity == "warning" and "4 days overdue" in alert.message

    summary = apply_overdue_rules(db, date(2026, 10, 29))
    assert summary["suspended"] == ["Client A"]
    db.expire_all()
    assert world.client_a.status == "suspended" and world.client_a.suspended_reason == "overdue"
    assert db.scalars(select(Alert).where(Alert.kind == "invoice_overdue", Alert.status == "open")).one().severity == "critical"

    record_payment(db, invoice, method="bank_transfer", reference="TX")
    db.expire_all()
    assert world.client_a.status == "active" and world.client_a.suspended_reason is None
    assert db.scalars(select(Alert).where(Alert.kind == "invoice_overdue", Alert.status == "open")).all() == []


def test_a_manual_suspension_is_not_lifted_by_a_payment(db, world):
    world.client_a.status, world.client_a.suspended_reason = "suspended", "manual"
    db.merge(world.client_a)
    db.commit()
    invoice = open_invoice(db, world.client_a)
    record_payment(db, invoice, method="other")
    db.expire_all()
    assert world.client_a.status == "suspended"


def test_the_grace_period_is_a_setting(db, world, api):
    open_invoice(db, world.client_a, due=date(2026, 10, 21))
    api("admin@agency.test").patch("/api/admin/settings", json={"values": {"billing.grace_days": 0}})
    assert apply_overdue_rules(db, date(2026, 10, 22))["suspended"] == ["Client A"]


def test_other_clients_are_not_touched(db, world):
    open_invoice(db, world.client_a, due=date(2026, 10, 1))
    apply_overdue_rules(db, date(2026, 11, 20))
    db.expire_all()
    assert world.client_a.status == "suspended" and world.client_b.status == "active"


def test_voiding_an_overdue_invoice_lifts_the_suspension(db, world):
    invoice = open_invoice(db, world.client_a, due=date(2026, 10, 1))
    apply_overdue_rules(db, date(2026, 11, 20))
    void_invoice(db, invoice)
    db.expire_all()
    assert world.client_a.status == "active"


def test_a_suspended_client_cannot_open_the_dashboard_but_can_see_billing(api, db, world):
    plan = make_plan(db)
    subscribe(db, world.client_a, plan)
    invoice = open_invoice(db, world.client_a, due=date(2026, 10, 1))
    apply_overdue_rules(db, date(2026, 11, 20))
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/overview").status_code == 403
    billing = alice.get(f"/api/clients/{world.client_a.id}/billing")
    assert billing.status_code == 200
    body = billing.json()
    assert body["client"]["status"] == "suspended" and body["client"]["suspended_reason"] == "overdue"
    assert body["outstanding"]["overdue_count"] == 1 and body["invoices"][0]["number"] == invoice.number


# ------------------------------------------------------------------ emails


def test_new_invoices_are_emailed_with_a_pdf_to_the_contact_and_the_owners(db, world, emails):
    world.client_a.contact_email = "boss@a.test"
    db.merge(world.client_a)
    db.commit()
    invoice = open_invoice(db, world.client_a)
    assert notifications.send_invoice_email(db, invoice, world.client_a) is True
    assert sorted(e["to"] for e in emails) == ["alice@a.test", "boss@a.test"]  # the owner and the contact, not the viewer
    first = emails[0]
    assert invoice.number in first["subject"] and first["attachments"][0][0] == f"{invoice.number}.pdf"
    assert first["attachments"][0][1].startswith(b"%PDF-")
    db.refresh(invoice)
    assert invoice.emailed_at is not None


def test_without_email_set_up_nothing_is_marked_as_sent(db, world, monkeypatch):
    monkeypatch.setattr(emailer, "email_configured", lambda: False)
    invoice = open_invoice(db, world.client_a)
    assert notifications.send_invoice_email(db, invoice, world.client_a) is False
    db.refresh(invoice)
    assert invoice.emailed_at is None


def test_reminders_and_overdue_notices_go_out_once(db, world, emails):
    open_invoice(db, world.client_a, due=date(2026, 10, 21))
    apply_overdue_rules(db, date(2026, 10, 20))  # due tomorrow -> reminder
    apply_overdue_rules(db, date(2026, 10, 20))
    reminders = [e for e in emails if e["subject"].startswith("Reminder")]
    assert len(reminders) == 1 and reminders[0]["to"] == "alice@a.test"  # run twice, but sent once (to the one owner)
    emails.clear()
    apply_overdue_rules(db, date(2026, 10, 23))
    apply_overdue_rules(db, date(2026, 10, 24))
    assert len([e for e in emails if "overdue" in e["subject"]]) == 1


# ------------------------------------------------------------------ the daily job


def test_the_daily_job_issues_invoices_emails_them_and_is_repeatable(db, world, emails):
    import asyncio

    plan = make_plan(db)
    today = datetime.now(timezone.utc).date()
    subscribe(db, world.client_a, plan, started=today - timedelta(days=60), billing_day=min(today.day, 28))
    result = asyncio.run(run_job("billing_daily", "test"))
    assert result["status"] == "ok" and "Issued 1 invoice" in result["message"] and "1 emailed" in result["message"] or "emailed" in result["message"]
    assert len(invoices_of(db, world.client_a)) == 1
    again = asyncio.run(run_job("billing_daily", "test"))
    assert "Issued 0 invoices" in again["message"] and len(invoices_of(db, world.client_a)) == 1


def test_the_email_switch_in_settings_is_respected(db, world, emails, api):
    import asyncio

    api("admin@agency.test").patch("/api/admin/settings", json={"values": {"billing.email_invoices": False}})
    plan = make_plan(db)
    today = datetime.now(timezone.utc).date()
    subscribe(db, world.client_a, plan, started=today - timedelta(days=60), billing_day=min(today.day, 28))
    asyncio.run(run_job("billing_daily", "test"))
    assert [e for e in emails if e["subject"].startswith("Invoice")] == []


# ------------------------------------------------------------------ plan features and limits


def test_plan_features_hide_parts_of_the_dashboard(api, db, world):
    starter = make_plan(db, name="Starter", features=dict(NO_FEATURES))
    subscribe(db, world.client_a, starter)
    alice = api("alice@a.test")
    site = f"/api/websites/{world.site_a.id}"
    assert alice.get(f"{site}/overview").status_code == 200  # the basic dashboard is always there
    for path in ("/sessions", "/persons", "/events/live", "/events/custom", "/recordings"):
        response = alice.get(site + path)
        assert response.status_code == 403, path
        assert "doesn't include" in response.json()["detail"] and "upgrade" in response.json()["detail"].lower()
    me = alice.get("/api/auth/me").json()["websites"][0]["features"]
    assert me["recordings"] is False and me["sessions"] is False
    # Client B has no plan: nothing is restricted.
    assert api("bob@b.test").get(f"/api/websites/{world.site_b.id}/recordings").status_code == 200


def test_each_feature_switch_controls_its_own_endpoints(api, db, world):
    growth = make_plan(db, features={**NO_FEATURES, "sessions": True, "people": True, "live_events": True})
    subscribe(db, world.client_a, growth)
    alice = api("alice@a.test")
    site = f"/api/websites/{world.site_a.id}"
    assert alice.get(f"{site}/sessions").status_code == 200
    assert alice.get(f"{site}/persons").status_code == 200
    assert alice.get(f"{site}/events/live").status_code == 200
    assert alice.get(f"{site}/recordings").status_code == 403


def test_admins_see_everything_but_view_as_follows_the_plan(api, db, world):
    starter = make_plan(db, name="Starter", features=dict(NO_FEATURES))
    subscribe(db, world.client_a, starter)
    admin = api("admin@agency.test")
    site = f"/api/websites/{world.site_a.id}"
    assert admin.get(f"{site}/recordings").status_code == 200  # an admin is never restricted
    assert all(admin.get("/api/auth/me").json()["websites"][0]["features"].values())
    admin.post("/api/admin/view-as", json={"client_id": str(world.client_a.id)})
    assert admin.get(f"{site}/recordings").status_code == 403  # exactly what the client sees


def test_changing_the_plan_changes_access_immediately(api, db, world):
    starter = make_plan(db, name="Starter", features=dict(NO_FEATURES))
    pro = make_plan(db, name="Pro", features=dict(ALL_FEATURES))
    sub = subscribe(db, world.client_a, starter)
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/recordings").status_code == 403
    sub.plan_id = pro.id
    db.commit()
    assert alice.get(f"/api/websites/{world.site_a.id}/recordings").status_code == 200


def test_website_and_member_limits_can_be_overridden_by_the_admin(api, db, world):
    one = make_plan(db, name="One", websites=1, members=2)
    subscribe(db, world.client_a, one)  # client A already has 1 website and 2 people (alice, vera)
    admin = api("admin@agency.test")
    body = {"name": "second.test", "posthog_host": "https://us.posthog.com", "posthog_project_id": 999001, "posthog_api_key": "phx_second_key_123"}
    refused = admin.post(f"/api/admin/clients/{world.client_a.id}/websites", json=body)
    assert refused.status_code == 409 and "allows 1 website" in refused.json()["detail"]
    assert admin.post(f"/api/admin/clients/{world.client_a.id}/websites", json={**body, "ignore_plan_limit": True}).status_code == 201

    person = {"email": "third@a.test", "role": "viewer", "password": "A-Valid-Password-1"}  # (a new person always needs one)
    assert admin.post(f"/api/admin/clients/{world.client_a.id}/members", json=person).status_code == 409
    assert db.scalar(select(Client.id).where(Client.id == world.client_a.id)) is not None
    from app.models import User

    db.expire_all()
    assert db.scalar(select(User).where(User.email == "third@a.test")) is None  # the refused person was not created
    assert admin.post(f"/api/admin/clients/{world.client_a.id}/members", json={**person, "ignore_plan_limit": True}).status_code == 201


def test_usage_limit_alerts_warn_then_escalate_then_clear(db, world):
    plan = make_plan(db, events=1000)
    subscribe(db, world.client_a, plan)
    today = datetime.now(timezone.utc).date()

    def set_events(n):
        db.query(UsageDaily).delete()
        db.add(UsageDaily(website_id=world.site_a.id, day=today, events=n))
        db.commit()

    def state():
        db.expire_all()
        return {a.dedupe_key.split(":")[-1]: a.severity for a in db.scalars(select(Alert).where(Alert.kind == "usage_limit", Alert.status == "open"))}

    set_events(500)
    evaluate_usage_limits(db)
    assert state() == {}
    set_events(850)
    assert evaluate_usage_limits(db)["warning"] == ["Client A"] and state() == {"warn": "warning"}
    set_events(1200)
    assert evaluate_usage_limits(db)["over"] == ["Client A"] and state() == {"over": "critical"}  # warning replaced by the bigger alert
    set_events(100)
    evaluate_usage_limits(db)
    assert state() == {}


def test_the_billing_page_reports_usage_against_the_plan(api, db, world):
    plan = make_plan(db, events=1000, websites=2, members=5)
    subscribe(db, world.client_a, plan)
    db.add(UsageDaily(website_id=world.site_a.id, day=datetime.now(timezone.utc).date(), events=250))
    db.commit()
    usage = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["usage"]
    assert usage["events"] == 250 and usage["event_limit"] == 1000 and usage["percent"] == 25.0
    assert (usage["websites"], usage["max_websites"], usage["members"], usage["max_members"]) == (1, 2, 2, 5)


# ------------------------------------------------------------------ client-facing billing access


def test_only_account_owners_see_billing(api, db, world):
    plan = make_plan(db)
    subscribe(db, world.client_a, plan)
    path = f"/api/clients/{world.client_a.id}/billing"
    assert api("alice@a.test").get(path).status_code == 200  # owner
    viewer = api("vera@a.test").get(path)
    assert viewer.status_code == 403 and "account owner" in viewer.json()["detail"]
    assert api("bob@b.test").get(path).status_code == 404  # another client's owner: indistinguishable from "doesn't exist"
    assert api().get(path).status_code == 401
    assert api("admin@agency.test").get(path).status_code == 200


def test_a_client_can_download_only_their_own_invoices(api, db, world):
    mine = open_invoice(db, world.client_a)
    theirs = open_invoice(db, world.client_b)
    alice = api("alice@a.test")
    pdf = alice.get(f"/api/clients/{world.client_a.id}/invoices/{mine.id}/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF-")
    assert mine.number in pdf.headers["content-disposition"]
    assert alice.get(f"/api/clients/{world.client_a.id}/invoices/{theirs.id}/pdf").status_code == 404  # B's invoice, through A's URL
    assert alice.get(f"/api/clients/{world.client_b.id}/invoices/{theirs.id}/pdf").status_code == 404


def test_billing_data_never_leaks_secrets_or_posthog(api, db, world):
    plan = make_plan(db)
    subscribe(db, world.client_a, plan)
    open_invoice(db, world.client_a)
    text = api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").text
    assert "phx_" not in text and "posthog" not in text.lower()


# ------------------------------------------------------------------ admin API


def test_plans_api(api, db, world):
    admin = api("admin@agency.test")
    created = admin.post("/api/admin/plans", json={"name": "Pro Plus", "price_pkr": "25000.50", "price_usd": 90, "monthly_event_limit": 5_000_000,
                                                    "features": {"recordings": True}, "max_websites": 20}).json()
    assert created["slug"] == "pro-plus" and created["price_pkr"] == 25000.5 and created["features"]["recordings"] is True and created["features"]["shopify"] is False
    assert admin.post("/api/admin/plans", json={"name": "Pro Plus"}).json()["slug"] == "pro-plus-2"
    assert admin.post("/api/admin/plans", json={"name": "X", "features": {"teleport": True}}).status_code == 400
    assert admin.post("/api/admin/plans", json={"name": "X", "features": {"recordings": "yes"}}).status_code == 400
    assert admin.post("/api/admin/plans", json={"name": "X", "price_pkr": -1}).status_code == 422

    edited = admin.patch(f"/api/admin/plans/{created['id']}", json={"price_pkr": "30000", "features": {"shopify": True}}).json()
    assert edited["price_pkr"] == 30000.0 and edited["features"]["shopify"] is True and edited["features"]["recordings"] is False
    assert any(p["id"] == created["id"] for p in admin.get("/api/admin/plans").json()["results"])
    assert admin.delete(f"/api/admin/plans/{created['id']}").status_code == 200


def test_new_prices_only_affect_future_invoices(api, db, world):
    plan = make_plan(db)
    subscribe(db, world.client_a, plan)
    [first] = generate_due_invoices(db, date(2026, 10, 14))
    api("admin@agency.test").patch(f"/api/admin/plans/{plan.id}", json={"price_pkr": "9000"})
    db.expire_all()
    assert db.get(Invoice, first.id).amount == Decimal("8000.00")
    [second] = generate_due_invoices(db, date(2026, 11, 14))
    assert second.amount == Decimal("9000.00")


def test_a_plan_in_use_cannot_be_deleted_and_an_inactive_plan_cannot_be_sold(api, db, world):
    plan = make_plan(db)
    admin = api("admin@agency.test")
    admin.put(f"/api/admin/clients/{world.client_a.id}/subscription", json={"plan_id": str(plan.id)})
    assert admin.delete(f"/api/admin/plans/{plan.id}").status_code == 409
    off = make_plan(db, name="Retired", active=False)
    assert admin.put(f"/api/admin/clients/{world.client_b.id}/subscription", json={"plan_id": str(off.id)}).status_code == 400


def test_subscription_api(api, db, world):
    plan, bigger = make_plan(db), make_plan(db, name="Bigger", pkr="20000")
    admin = api("admin@agency.test")
    body = admin.put(f"/api/admin/clients/{world.client_a.id}/subscription", json={"plan_id": str(plan.id), "started_at": "2026-10-30"}).json()
    assert body["subscription"]["billing_day"] == 28 and body["plan"]["name"] == "Growth" and body["plan"]["price"] == 8000.0  # day 30 -> 28
    changed = admin.put(f"/api/admin/clients/{world.client_a.id}/subscription", json={"plan_id": str(bigger.id), "billing_day": 5, "price_override": "15000"}).json()
    assert changed["plan"]["name"] == "Bigger" and changed["plan"]["price"] == 15000.0 and changed["subscription"]["billing_day"] == 5
    assert admin.put(f"/api/admin/clients/{world.client_a.id}/subscription", json={"plan_id": str(bigger.id), "billing_day": 31}).status_code == 422
    assert admin.delete(f"/api/admin/clients/{world.client_a.id}/subscription").json()["plan"] is None
    assert admin.delete(f"/api/admin/clients/{world.client_a.id}/subscription").status_code == 404
    db.expire_all()
    assert len(db.scalars(select(Subscription).where(Subscription.client_id == world.client_a.id)).all()) == 1  # kept as history


def test_invoices_api_manual_invoice_payment_void_and_pdf(api, db, world):
    admin = api("admin@agency.test")
    created = admin.post(f"/api/admin/clients/{world.client_a.id}/invoices", json={"description": "Set-up fee", "amount": "2500.50"})
    assert created.status_code == 201
    invoice = created.json()
    assert invoice["amount"] == 2500.5 and invoice["status"] == "open" and invoice["source"] == "manual" and invoice["line_items"][0]["description"] == "Set-up fee"
    assert admin.post(f"/api/admin/clients/{world.client_a.id}/invoices", json={"description": "x", "amount": "0"}).status_code == 422

    partial = admin.post(f"/api/admin/invoices/{invoice['id']}/payments", json={"method": "easypaisa", "amount": "1000", "reference": "EP-1"}).json()
    assert partial["status"] == "open" and partial["balance"] == 1500.5 and partial["payments"][0]["reference"] == "EP-1"
    assert admin.post(f"/api/admin/invoices/{invoice['id']}/payments", json={"method": "other", "amount": "9999"}).status_code == 409
    assert admin.post(f"/api/admin/invoices/{invoice['id']}/payments", json={"method": "crypto"}).status_code == 422
    assert admin.post(f"/api/admin/invoices/{invoice['id']}/void").status_code == 409  # has a payment
    paid = admin.post(f"/api/admin/invoices/{invoice['id']}/payments", json={"method": "bank_transfer", "paid_on": "2026-10-20"}).json()
    assert paid["status"] == "paid" and paid["balance"] == 0 and paid["paid_at"].startswith("2026-10-20")

    pdf = admin.get(f"/api/admin/invoices/{invoice['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-") and len(pdf.content) > 1500

    other = admin.post(f"/api/admin/clients/{world.client_b.id}/invoices", json={"description": "Mistake", "amount": "100"}).json()
    assert admin.post(f"/api/admin/invoices/{other['id']}/void").json()["status"] == "void"


def test_the_invoice_list_filters_and_pages(api, db, world):
    admin = api("admin@agency.test")
    for i in range(5):
        admin.post(f"/api/admin/clients/{world.client_a.id}/invoices", json={"description": f"Fee {i}", "amount": "100"})
    overdue = open_invoice(db, world.client_b, due=date(2020, 1, 1))
    paid = open_invoice(db, world.client_b)
    record_payment(db, paid, method="other")

    assert len(admin.get("/api/admin/invoices", params={"status": "open"}).json()["results"]) == 6
    assert [i["number"] for i in admin.get("/api/admin/invoices", params={"status": "overdue"}).json()["results"]] == [overdue.number]
    assert [i["number"] for i in admin.get("/api/admin/invoices", params={"status": "paid"}).json()["results"]] == [paid.number]
    assert len(admin.get("/api/admin/invoices", params={"client_id": str(world.client_b.id)}).json()["results"]) == 2
    first = admin.get("/api/admin/invoices", params={"limit": 4}).json()
    second = admin.get("/api/admin/invoices", params={"limit": 4, "cursor": first["next_cursor"]}).json()
    assert len(first["results"]) == 4 and len(second["results"]) == 3 and second["next_cursor"] is None
    assert not {i["id"] for i in first["results"]} & {i["id"] for i in second["results"]}
    assert admin.get("/api/admin/invoices", params={"status": "bogus"}).status_code == 422


def test_sending_an_invoice_needs_email_to_be_set_up(api, db, world, monkeypatch):
    invoice = open_invoice(db, world.client_a)
    admin = api("admin@agency.test")
    monkeypatch.setattr(emailer, "email_configured", lambda: False)
    assert admin.post(f"/api/admin/invoices/{invoice.id}/send").status_code == 409
    monkeypatch.setattr(emailer, "email_configured", lambda: True)
    monkeypatch.setattr(emailer, "send_email", lambda *a, **k: True)
    body = admin.post(f"/api/admin/invoices/{invoice.id}/send").json()
    assert body["sent"] is True and body["to"] == ["alice@a.test"]


def test_currency_is_locked_once_there_are_invoices_and_such_clients_cannot_be_deleted(api, db, world):
    admin = api("admin@agency.test")
    assert admin.patch(f"/api/admin/clients/{world.client_a.id}", json={"currency": "USD"}).json()["currency"] == "USD"
    open_invoice(db, world.client_a)
    assert admin.patch(f"/api/admin/clients/{world.client_a.id}", json={"currency": "PKR"}).status_code == 409
    deletion = admin.request("DELETE", f"/api/admin/clients/{world.client_a.id}", json={"confirm": "Client A"})
    assert deletion.status_code == 409 and "invoices" in deletion.json()["detail"]
    assert admin.patch(f"/api/admin/clients/{world.client_a.id}", json={"currency": "EUR"}).status_code == 422


def test_business_overview(api, db, world):
    plan = make_plan(db)
    world.client_b.currency = "USD"
    db.merge(world.client_b)
    db.commit()
    subscribe(db, world.client_a, plan)  # 8000 PKR / month
    subscribe(db, world.client_b, plan)  # 29 USD / month
    db.add(UsageDaily(website_id=world.site_a.id, day=datetime.now(timezone.utc).date(), events=1_500_000))
    db.commit()
    unpaid = open_invoice(db, world.client_a, amount="8000", due=date(2020, 1, 1))
    paid = open_invoice(db, world.client_a, amount="500")
    record_payment(db, paid, method="other")
    admin = api("admin@agency.test")
    admin.patch("/api/admin/settings", json={"values": {"billing.usd_to_pkr": 300}})

    body = admin.get("/api/admin/business").json()
    assert body["clients"] == {"total": 2, "active": 2, "suspended": 0, "paying": 2, "without_plan": 0}
    assert body["mrr"]["PKR"] == 8000.0 and body["mrr"]["USD"] == 29.0 and body["mrr"]["total_pkr"] == 8000 + 29 * 300
    assert body["unpaid"]["PKR"] == 8000.0 and body["unpaid"]["count"] == 1 and body["unpaid"]["overdue_count"] == 1 and body["unpaid"]["overdue"]["PKR"] == 8000.0
    assert body["received_this_month"]["PKR"] == 500.0
    assert body["posthog_cost_usd"]["so_far"] == pytest.approx(25.0)  # 1.5M events: 500k over the free million
    assert body["estimated_margin_pkr"] < body["mrr"]["total_pkr"]
    assert unpaid.status == "open"


# ------------------------------------------------------------------ invoice PDFs


def test_pdfs_survive_unusual_names_and_all_statuses(db, world):
    world.client_a.name = "شاپ Ali’s “Shop” ✓ — café"
    db.merge(world.client_a)
    db.commit()
    invoice = open_invoice(db, world.client_a)
    open_pdf = notifications.render_pdf(db, invoice, world.client_a)
    record_payment(db, invoice, method="other", amount=Decimal("1000"))
    db.refresh(invoice)
    partial = notifications.render_pdf(db, invoice, world.client_a)
    record_payment(db, invoice, method="other")
    db.refresh(invoice)
    paid = notifications.render_pdf(db, invoice, world.client_a)
    assert all(p.startswith(b"%PDF-") and len(p) > 1500 for p in (open_pdf, partial, paid))


# ------------------------------------------------------------------ the payment gateway plug


class PretendGateway(providers.PaymentProvider):
    """A made-up gateway that signs its notifications with a shared secret (like real ones do)."""

    name = "pretend"
    secret = b"gateway-secret"

    def parse_webhook(self, headers, body):
        expected = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(headers.get("x-signature", ""), expected):
            raise providers.InvalidWebhook("bad signature")
        data = json.loads(body)
        if data["type"] != "payment.succeeded":
            return None
        return providers.PaymentEvent(provider=self.name, provider_payment_id=data["id"], invoice_number=data["invoice"],
                                      amount=Decimal(data["amount"]), currency=data["currency"], reference=data["id"])


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setitem(providers.PROVIDERS, "pretend", PretendGateway())
    return PretendGateway


def notify(api, body: dict, secret=b"gateway-secret"):
    raw = json.dumps(body).encode()
    return api().post("/api/billing/webhooks/pretend", content=raw, headers={"x-signature": hmac.new(secret, raw, hashlib.sha256).hexdigest(), "content-type": "application/json"})


def test_a_signed_payment_notification_closes_the_invoice_and_lifts_the_suspension(api, db, world, gateway):
    invoice = open_invoice(db, world.client_a, due=date(2020, 1, 1))
    apply_overdue_rules(db, date(2026, 10, 25))
    db.refresh(world.client_a)
    assert world.client_a.status == "suspended"

    response = notify(api, {"type": "payment.succeeded", "id": "pay_77", "invoice": invoice.number, "amount": "8000.00", "currency": "PKR"})
    assert response.status_code == 200 and response.json() == {"ok": True}
    db.expire_all()
    assert db.get(Invoice, invoice.id).status == "paid" and world.client_a.status == "active"
    [payment] = db.scalars(select(Payment)).all()
    assert (payment.provider, payment.provider_payment_id, payment.amount) == ("pretend", "pay_77", Decimal("8000.00"))


def test_a_repeated_notification_does_not_double_count(api, db, world, gateway):
    invoice = open_invoice(db, world.client_a)
    body = {"type": "payment.succeeded", "id": "pay_1", "invoice": invoice.number, "amount": "1000.00", "currency": "PKR"}
    assert notify(api, body).status_code == 200 and notify(api, body).status_code == 200
    assert len(db.scalars(select(Payment)).all()) == 1


def test_forged_unknown_and_mismatched_notifications_are_refused(api, db, world, gateway):
    invoice = open_invoice(db, world.client_a)
    good = {"type": "payment.succeeded", "id": "pay_9", "invoice": invoice.number, "amount": "100.00", "currency": "PKR"}
    assert notify(api, good, secret=b"wrong-secret").status_code == 400  # forged: bad signature
    assert notify(api, {**good, "invoice": "INV-2099-9999"}).status_code == 404
    assert notify(api, {**good, "currency": "USD"}).status_code == 400
    assert api().post("/api/billing/webhooks/unknown-gateway", content=b"{}").status_code == 404
    assert notify(api, {"type": "payment.started", "id": "x", "invoice": invoice.number, "amount": "1", "currency": "PKR"}).json()["ignored"] is True
    assert db.scalars(select(Payment)).all() == []  # nothing got through


def test_a_gateway_payment_for_an_already_paid_invoice_is_acknowledged_not_recorded(api, db, world, gateway):
    invoice = open_invoice(db, world.client_a)
    record_payment(db, invoice, method="bank_transfer")
    response = notify(api, {"type": "payment.succeeded", "id": "late", "invoice": invoice.number, "amount": "8000.00", "currency": "PKR"})
    assert response.status_code == 200 and response.json()["ignored"] is True  # so the gateway stops retrying
    assert len(db.scalars(select(Payment)).all()) == 1


def test_no_gateway_is_registered_by_default():
    assert providers.PROVIDERS == {}  # payments are manual until you add one


def test_billing_audit_entries_never_hold_secrets(api, db, world):
    from app.models import AuditLog

    admin = api("admin@agency.test")
    invoice = admin.post(f"/api/admin/clients/{world.client_a.id}/invoices", json={"description": "Fee", "amount": "100"}).json()
    admin.post(f"/api/admin/invoices/{invoice['id']}/payments", json={"method": "bank_transfer", "reference": "TX-1"})
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"admin.invoice_created", "admin.payment_recorded"} <= actions
    _ = PASSWORD, make_client, make_user


# ------------------------------------------------------------------ "Pay online" (checkout)


class CheckoutGateway(PretendGateway):
    name = "checkoutgw"
    fail = False

    async def create_checkout(self, invoice, *, return_url):
        if self.fail:
            raise providers.GatewayError("gateway down: secret-detail")
        return providers.CheckoutSession(url=f"https://pay.example/checkout/{invoice.number}?back={return_url}", provider_reference="ref-1")


@pytest.fixture
def online(monkeypatch, api):
    gw = CheckoutGateway()
    monkeypatch.setitem(providers.PROVIDERS, "checkoutgw", gw)

    def switch_on():
        api("admin@agency.test").patch("/api/admin/settings", json={"values": {"billing.online_provider": "checkoutgw"}})

    return gw, switch_on


def test_the_pay_online_button_only_exists_when_a_gateway_is_switched_on(api, db, world, online):
    gw, switch_on = online
    assert api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["online_payments"] is False
    switch_on()
    assert api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["online_payments"] is True


def test_the_setting_alone_is_not_enough_the_gateway_must_exist_in_the_code(api, db, world):
    api("admin@agency.test").patch("/api/admin/settings", json={"values": {"billing.online_provider": "not-built-yet"}})
    assert api("alice@a.test").get(f"/api/clients/{world.client_a.id}/billing").json()["online_payments"] is False


def test_an_owner_can_start_a_checkout_for_an_open_invoice(api, db, world, online):
    gw, switch_on = online
    switch_on()
    invoice = open_invoice(db, world.client_a)
    response = api("alice@a.test").post(f"/api/clients/{world.client_a.id}/invoices/{invoice.id}/checkout")
    assert response.status_code == 200 and response.json()["url"].startswith(f"https://pay.example/checkout/{invoice.number}")
    assert db.scalars(select(AuditLog).where(AuditLog.action == "billing.checkout_started")).one().details == {"provider": "checkoutgw"}


def test_checkout_refusals(api, db, world, online):
    gw, switch_on = online
    invoice = open_invoice(db, world.client_a)
    other = open_invoice(db, world.client_b)
    url = lambda c, i: f"/api/clients/{c.id}/invoices/{i.id}/checkout"  # noqa: E731
    assert api("alice@a.test").post(url(world.client_a, invoice)).status_code == 409  # no gateway switched on yet
    switch_on()
    assert api("vera@a.test").post(url(world.client_a, invoice)).status_code == 403  # a viewer
    assert api("bob@b.test").post(url(world.client_a, invoice)).status_code == 404  # another client's owner
    assert api("alice@a.test").post(url(world.client_a, other)).status_code == 404  # another client's invoice
    assert api().post(url(world.client_a, invoice)).status_code == 401
    record_payment(db, invoice, method="bank_transfer")
    assert api("alice@a.test").post(url(world.client_a, invoice)).status_code == 409  # already paid


def test_a_gateway_that_is_down_gives_a_plain_message_without_details(api, db, world, online):
    gw, switch_on = online
    switch_on()
    gw.fail = True
    invoice = open_invoice(db, world.client_a)
    response = api("alice@a.test").post(f"/api/clients/{world.client_a.id}/invoices/{invoice.id}/checkout")
    assert response.status_code == 502 and "secret-detail" not in response.text
    gw.fail = False


def test_a_suspended_client_can_still_start_a_checkout(api, db, world, online):
    gw, switch_on = online
    switch_on()
    invoice = open_invoice(db, world.client_a, due=date(2020, 1, 1))
    apply_overdue_rules(db, date(2026, 10, 25))
    assert api("alice@a.test").post(f"/api/clients/{world.client_a.id}/invoices/{invoice.id}/checkout").status_code == 200
