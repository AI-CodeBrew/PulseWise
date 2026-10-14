"""
WhatsApp weekly reports: the number rules, the Meta Cloud API call, who is messaged and when, and failures.

Runs against a PRETEND Meta (written from Meta's documentation). It proves our logic, not that a real WhatsApp
Business account accepts our messages: send yourself a test from the admin panel before relying on it.
"""

import asyncio
import dataclasses
from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app import emailer, whatsapp
from app.jobs import run_job
from app.models import Alert, Client, Report
from app.reports import service

from .test_reports import NOW, answers, emails, make_report  # noqa: F401  (emails: a fixture; the others are helpers)

TOKEN = "EAAG-secret-access-token"


class FakeMeta:
    def __init__(self):
        self.sent: list[dict] = []
        self.status = 200
        self.body: dict | None = None
        self.network_down = False

    def send(self, url, headers, payload):
        if self.network_down:
            raise httpx.ConnectError(f"boom {headers['Authorization']}")
        self.sent.append({"url": url, "headers": headers, "payload": payload})
        body = self.body if self.body is not None else {"messages": [{"id": f"wamid.{len(self.sent)}"}]}
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))


@pytest.fixture
def meta(monkeypatch):
    fake = FakeMeta()
    monkeypatch.setattr(whatsapp, "settings", dataclasses.replace(whatsapp.settings, whatsapp_access_token=TOKEN, whatsapp_phone_number_id="1055551234"))
    monkeypatch.setattr(whatsapp, "_send", fake.send)
    return fake


def opt_in(db, client, number="923001234567", enabled=True):
    client.whatsapp_number, client.whatsapp_reports_enabled = number, enabled
    db.merge(client)
    db.commit()


# ------------------------------------------------------------------ numbers


@pytest.mark.parametrize("raw, expected", [
    ("+92 300-1234567", "923001234567"), ("923001234567", "923001234567"), ("0092 300 1234567", "923001234567"),
    ("+1 (415) 555-0132", "14155550132"), ("  +971501234567 ", "971501234567"),
])
def test_numbers_are_turned_into_international_digits(raw, expected):
    assert whatsapp.normalize_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "0300 1234567", "12345", "+92 300 12345678901234", "abc", "+0123456789", "92300123456a", "+92 (0) 300"])
def test_unusable_numbers_are_refused(raw):
    assert whatsapp.normalize_number(raw) is None


def test_template_values_are_made_safe_for_whatsapp():
    assert whatsapp.clean_param("line one\nline two\t\ttabbed     spaces") == "line one line two tabbed spaces"
    assert whatsapp.clean_param("   ") == "-" and len(whatsapp.clean_param("x" * 2000)) == 400


# ------------------------------------------------------------------ the API call


def test_a_template_message_is_sent_the_way_metas_docs_describe(meta):
    message_id = whatsapp.send_template("923001234567", "weekly_report", "en", ["Shop", "5-11 Oct 2026", "120 people visited", "https://x.test/r"], api_version="v23.0")
    assert message_id == "wamid.1"
    [call] = meta.sent
    assert call["url"] == "https://graph.facebook.com/v23.0/1055551234/messages"
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert call["payload"] == {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": "923001234567", "type": "template",
        "template": {"name": "weekly_report", "language": {"code": "en"}, "components": [{"type": "body", "parameters": [
            {"type": "text", "text": "Shop"}, {"type": "text", "text": "5-11 Oct 2026"}, {"type": "text", "text": "120 people visited"}, {"type": "text", "text": "https://x.test/r"}]}]},
    }


def test_not_configured(monkeypatch):
    monkeypatch.setattr(whatsapp, "settings", dataclasses.replace(whatsapp.settings, whatsapp_access_token="", whatsapp_phone_number_id=""))
    assert whatsapp.whatsapp_configured() is False
    with pytest.raises(whatsapp.WhatsAppError, match="isn't set up"):
        whatsapp.send_template("923001234567", "t", "en", ["x"], api_version="v23.0")


def test_metas_errors_are_explained_without_leaking_the_token(meta):
    meta.status, meta.body = 400, {"error": {"message": "(#132001) Template name does not exist in the translation", "code": 132001}}
    with pytest.raises(whatsapp.WhatsAppError, match="132001") as caught:
        whatsapp.send_template("923001234567", "weekly_report", "en", ["x"], api_version="v23.0")
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("status, body", [(200, {"messages": []}), (200, {}), (500, {"weird": True}), (401, {"error": "not even an object"})])
def test_odd_answers_are_never_treated_as_sent(meta, status, body):
    meta.status, meta.body = status, body
    with pytest.raises(whatsapp.WhatsAppError):
        whatsapp.send_template("923001234567", "t", "en", ["x"], api_version="v23.0")


def test_a_network_failure_is_a_plain_error_without_the_token(meta):
    meta.network_down = True
    with pytest.raises(whatsapp.WhatsAppError) as caught:
        whatsapp.send_template("923001234567", "t", "en", ["x"], api_version="v23.0")
    assert TOKEN not in str(caught.value) and "ConnectError" in str(caught.value)


@pytest.mark.parametrize("version", ["v23.0/../../x", "", "v 1", "a" * 70])
def test_the_api_version_setting_cannot_redirect_the_request(meta, version):
    with pytest.raises(whatsapp.WhatsAppError):
        whatsapp.send_template("923001234567", "t", "en", ["x"], api_version=version)
    assert meta.sent == []


# ------------------------------------------------------------------ the client's settings


def settings_url(world):
    return f"/api/clients/{world.client_a.id}/settings"


def test_the_whatsapp_section_is_hidden_when_the_server_has_no_whatsapp(api, world):
    assert api("alice@a.test").get(settings_url(world)).json()["whatsapp_available"] is False


def test_a_client_adds_a_number_and_opts_in(api, db, world, meta):
    alice = api("alice@a.test")
    assert alice.get(settings_url(world)).json() | {"timezones": 0} == {**alice.get(settings_url(world)).json(), "timezones": 0}
    assert alice.get(settings_url(world)).json()["whatsapp_available"] is True
    response = alice.patch(settings_url(world), json={"whatsapp_number": "+92 300-1234567", "whatsapp_reports_enabled": True})
    assert response.status_code == 200 and response.json()["whatsapp_number"] == "923001234567" and response.json()["whatsapp_reports_enabled"] is True
    db.expire_all()
    client = db.get(Client, world.client_a.id)
    assert (client.whatsapp_number, client.whatsapp_reports_enabled) == ("923001234567", True)


def test_opting_in_needs_a_number_and_a_valid_one(api, db, world, meta):
    alice = api("alice@a.test")
    assert alice.patch(settings_url(world), json={"whatsapp_reports_enabled": True}).status_code == 400
    assert alice.patch(settings_url(world), json={"whatsapp_number": "0300 1234567"}).status_code == 400  # no country code
    assert alice.patch(settings_url(world), json={"whatsapp_number": "not a number", "whatsapp_reports_enabled": True}).status_code == 400
    db.expire_all()
    client = db.get(Client, world.client_a.id)
    assert client.whatsapp_number is None and client.whatsapp_reports_enabled is False


def test_removing_the_number_switches_messages_off(api, db, world, meta):
    opt_in(db, world.client_a)
    assert api("alice@a.test").patch(settings_url(world), json={"whatsapp_number": ""}).status_code == 200
    db.expire_all()
    client = db.get(Client, world.client_a.id)
    assert client.whatsapp_number is None and client.whatsapp_reports_enabled is False


def test_only_owners_change_whatsapp_settings(api, db, world, meta):
    assert api("vera@a.test").patch(settings_url(world), json={"whatsapp_number": "+923001234567"}).status_code == 403
    assert api("bob@b.test").patch(settings_url(world), json={"whatsapp_number": "+923001234567"}).status_code == 404


# ------------------------------------------------------------------ sending a report


def test_a_report_goes_to_the_opted_in_number_once(db, world, fake_posthog, meta):
    opt_in(db, world.client_a)
    report_id = make_report(db, world, fake_posthog)
    assert service.send_report_whatsapp(report_id) is True
    [call] = meta.sent
    params = [p["text"] for p in call["payload"]["template"]["components"][0]["parameters"]]
    assert call["payload"]["to"] == "923001234567" and call["payload"]["template"]["name"] == "weekly_report"
    assert params[0] == "Client A site" and params[1] == "5-11 Oct 2026" and "120 people visited" in params[2] and params[3].endswith(f"/sites/{world.site_a.id}/reports/{report_id}")
    db.expire_all()
    assert db.get(Report, report_id).whatsapp_sent_at is not None
    assert service.send_report_whatsapp(report_id) is False and len(meta.sent) == 1  # never twice by itself
    assert service.send_report_whatsapp(report_id, force=True) is True and len(meta.sent) == 2  # unless an admin asks


def test_nothing_is_sent_without_opt_in_a_number_or_setup(db, world, fake_posthog, meta, monkeypatch):
    report_id = make_report(db, world, fake_posthog)
    assert service.send_report_whatsapp(report_id) is False  # never opted in
    opt_in(db, world.client_a, enabled=False)
    assert service.send_report_whatsapp(report_id) is False  # has a number but said no
    opt_in(db, world.client_a, number=None, enabled=True)
    assert service.send_report_whatsapp(report_id) is False  # opted in without a number
    opt_in(db, world.client_a)
    monkeypatch.setattr(whatsapp, "settings", dataclasses.replace(whatsapp.settings, whatsapp_access_token=""))
    assert service.send_report_whatsapp(report_id) is False  # the server has no WhatsApp set up
    assert meta.sent == []


def test_the_template_name_and_language_come_from_settings(db, world, fake_posthog, meta, api):
    admin = api("admin@agency.test")
    admin.patch("/api/admin/settings", json={"values": {"whatsapp.template_name": "my_template", "whatsapp.template_language": "en_US", "whatsapp.api_version": "v24.0"}})
    opt_in(db, world.client_a)
    service.send_report_whatsapp(make_report(db, world, fake_posthog))
    call = meta.sent[0]
    assert call["payload"]["template"]["name"] == "my_template" and call["payload"]["template"]["language"]["code"] == "en_US" and "/v24.0/" in call["url"]


def test_a_failed_send_raises_an_alert_without_breaking_anything_and_clears_when_it_works(db, world, fake_posthog, meta):
    opt_in(db, world.client_a)
    report_id = make_report(db, world, fake_posthog)
    meta.status, meta.body = 400, {"error": {"message": "Template does not exist", "code": 132001}}
    assert service.send_report_whatsapp(report_id) is False
    db.expire_all()
    alert = db.scalar(select(Alert).where(Alert.dedupe_key == f"whatsapp:{world.client_a.id}", Alert.status == "open"))
    assert alert is not None and "Template does not exist" in alert.message and TOKEN not in alert.message
    assert db.get(Report, report_id).whatsapp_sent_at is None  # so the next attempt tries again
    meta.status, meta.body = 200, None
    assert service.send_report_whatsapp(report_id) is True
    db.expire_all()
    assert db.scalar(select(Alert).where(Alert.dedupe_key == f"whatsapp:{world.client_a.id}", Alert.status == "open")) is None


def test_the_weekly_job_sends_whatsapp_too(db, world, fake_posthog, meta, emails, monkeypatch):
    from app.jobs import reports as reports_job

    opt_in(db, world.client_a)
    real = service.due_websites
    monkeypatch.setattr(reports_job.service, "due_websites", lambda db_, now=None: real(db_, NOW))
    answers(fake_posthog)
    result = asyncio.run(run_job("weekly_reports", "test"))
    assert "1 on WhatsApp" in result["message"] and len(meta.sent) == 1  # only client A opted in
    assert "on WhatsApp" not in asyncio.run(run_job("weekly_reports", "test"))["message"]  # a second run makes and sends nothing


def test_the_admin_button_sends_on_whatsapp_even_without_email(api, db, world, fake_posthog, meta, monkeypatch):
    monkeypatch.setattr(emailer, "email_configured", lambda: False)
    opt_in(db, world.client_a)
    answers(fake_posthog)
    response = api("admin@agency.test").post(f"/api/admin/websites/{world.site_a.id}/reports", json={"send": True})
    assert response.status_code == 201 and response.json()["whatsapp_sent"] is True and response.json()["emailed_to"] == 0
    assert len(meta.sent) == 1
