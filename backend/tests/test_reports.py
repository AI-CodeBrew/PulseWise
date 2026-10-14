"""Weekly reports: the week, the numbers, the summary (rules and AI), email and PDF, who is due, and the API."""

import asyncio
import itertools
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from sqlalchemy import select

from app import emailer
from app.billing.service import FEATURES
from app.jobs import run_job
from app.models import Alert, Client, Plan, Report, Subscription
from app.reports import render, service, summary
from app.reports.collect import collect_report_data
from app.reports.summary import TEXT, Summary, rules_summary

from .conftest import PostHogClient

START, END = date(2026, 10, 5), date(2026, 10, 11)  # a Monday to a Sunday
_site_counter = itertools.count()


# ------------------------------------------------------------------ test data


def answers(fake, *, visitors=120, prev_visitors=100, sessions=150, bounce=0.4, no_data=False):
    """Make the fake PostHog answer every report query with realistic rows."""
    if no_data:
        for name in ("kpi_events", "kpi_sessions", "daily", "top_pages", "sources", "channels", "countries", "devices", "custom_events"):
            fake.answer(f"report:{name}", ["x"], [])
        return
    fake.answer("report:kpi_events", ["pageviews", "visitors", "prev_pageviews", "prev_visitors"], [[400, visitors, 300, prev_visitors]])
    fake.answer("report:kpi_sessions", ["sessions", "prev_sessions", "avg_duration", "prev_avg_duration", "bounce_rate", "prev_bounce_rate"], [[sessions, 130, 134.0, 120.0, bounce, 0.5]])
    fake.answer("report:daily", ["day", "pageviews", "visitors"], [["2026-10-05", 50, 20], ["2026-10-07", 200, 70], ["2026-10-09", 150, 30]])
    fake.answer("report:top_pages", ["path", "views", "visitors"], [["/shop", 220, 90], ["/<script>alert(1)</script>", 40, 10], [None, 5, 2]])
    fake.answer("report:sources", ["name", "sessions"], [["$direct", 80], ["instagram.com", 50], [None, 20]])
    fake.answer("report:channels", ["name", "sessions"], [["Direct", 80], ["Social", 70]])
    fake.answer("report:countries", ["name", "visitors"], [["Pakistan", 100], ["UAE", 20]])
    fake.answer("report:devices", ["name", "visitors"], [["Mobile", 90], ["Desktop", 30]])
    fake.answer("report:custom_events", ["event", "count"], [["whatsapp_click", 33], ["cta_click", 10]])


class FakeAI:
    """Stands in for the Claude client. Records what it was asked and answers as scripted."""

    def __init__(self, reply=None, stop_reason="end_turn", error=None):
        self.calls = []
        self.reply, self.stop_reason, self.error = reply, stop_reason, error
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        text = json.dumps(self.reply) if not isinstance(self.reply, str) else self.reply
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


GOOD_AI_REPLY = {"headline": "120 people visited this week, up 20%.", "bullets": ["Your shop page got 220 views.", "Instagram sent 50 visits."], "recommendation": "Post your best product on Instagram on Tuesday."}


def api_error():
    return anthropic.APIConnectionError(message="boom", request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


@pytest.fixture
def fake_ai(monkeypatch):
    def install(**kwargs):
        ai = FakeAI(**kwargs)
        monkeypatch.setattr(summary, "make_ai_client", lambda: ai)
        return ai

    return install


@pytest.fixture
def emails(monkeypatch):
    sent = []
    monkeypatch.setattr(emailer, "email_configured", lambda: True)

    def capture(to, subject, body, *, html=None, attachments=None):
        sent.append({"to": to, "subject": subject, "body": body, "html": html, "attachments": attachments or []})
        return True

    monkeypatch.setattr(emailer, "send_email", capture)
    monkeypatch.setattr("app.alerts.send_email", lambda *a, **k: True)
    return sent


def sample_data(fake, **kwargs):
    answers(fake, **kwargs)
    # (a fresh website id each time: PostHog answers are cached per website)
    config = SimpleNamespace(website_id=f"x-{next(_site_counter)}", name="x", posthog_host="https://us.posthog.com", project_id=1, api_key="k", client_id="", role="owner")
    return asyncio.run(collect_report_data(PostHogClient(config), START, END))


# ------------------------------------------------------------------ the week and the time zone


@pytest.mark.parametrize("today, expected", [
    (date(2026, 10, 12), (date(2026, 10, 5), date(2026, 10, 11))),  # Monday: the week that just ended
    (date(2026, 10, 14), (date(2026, 10, 5), date(2026, 10, 11))),  # Wednesday: still that week
    (date(2026, 10, 18), (date(2026, 10, 5), date(2026, 10, 11))),  # Sunday: the week before the running one
    (date(2026, 10, 19), (date(2026, 10, 12), date(2026, 10, 18))),
    (date(2027, 1, 4), (date(2026, 12, 28), date(2027, 1, 3))),  # across the new year
])
def test_last_full_week_is_monday_to_sunday(today, expected):
    start, end = service.last_full_week(today)
    assert (start, end) == expected and start.weekday() == 0 and end.weekday() == 6 and (end - start).days == 6


def test_reports_are_ready_from_monday_8am_in_the_clients_time_zone():
    karachi = Client(name="K", timezone="Asia/Karachi")  # UTC+5, no daylight saving
    utc = lambda h, m: datetime(2026, 10, 12, h, m, tzinfo=timezone.utc)  # a Monday  # noqa: E731
    assert service.is_ready(karachi, utc(2, 59))[0] is False  # 07:59 in Karachi
    assert service.is_ready(karachi, utc(3, 0)) == (True, date(2026, 10, 5), date(2026, 10, 11))  # 08:00 in Karachi
    assert service.is_ready(Client(name="U", timezone="UTC"), utc(7, 59))[0] is False
    assert service.is_ready(Client(name="U", timezone="UTC"), utc(8, 0))[0] is True
    # Later in the week the same report is still the one that's due (catch-up if the server was off on Monday).
    assert service.is_ready(karachi, datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)) == (True, date(2026, 10, 5), date(2026, 10, 11))
    assert service.is_ready(Client(name="X", timezone="Not/AZone"), utc(12, 0))[0] is True  # a broken time zone falls back to Karachi


# ------------------------------------------------------------------ the numbers


def test_the_numbers_are_collected_with_comparisons_and_every_day_present(fake_posthog):
    data = sample_data(fake_posthog)
    assert data["period"] == {"start": "2026-10-05", "end": "2026-10-11", "days": 7}
    assert data["kpis"]["visitors"] == {"current": 120, "previous": 100, "change_pct": 20.0}
    assert data["kpis"]["bounce_rate"] == {"current": 40.0, "previous": 50.0, "change_pct": -20.0}
    assert data["kpis"]["avg_session_duration"]["current"] == 134
    assert [d["date"] for d in data["daily"]] == [f"2026-10-{n:02d}" for n in range(5, 12)]  # all 7 days
    assert [d["visitors"] for d in data["daily"]] == [20, 0, 70, 0, 30, 0, 0]  # a day with no data is a real zero
    assert data["top_pages"][2]["path"] == "(unknown)" and data["sources"][0]["name"] == "Direct" and data["sources"][2]["name"] == "Direct"


def test_the_week_is_asked_for_with_explicit_dates(fake_posthog):
    sample_data(fake_posthog)
    assert {c["query_name"] for c in fake_posthog.calls} >= {"report:kpi_events", "report:daily", "report:top_pages"}


def test_a_website_with_no_data_gives_an_empty_but_valid_report(fake_posthog):
    data = sample_data(fake_posthog, no_data=True)
    assert data["kpis"]["visitors"]["current"] == 0 and data["kpis"]["visitors"]["change_pct"] is None
    assert data["top_pages"] == [] and len(data["daily"]) == 7


# ------------------------------------------------------------------ the rule-based summary


def test_all_three_languages_have_exactly_the_same_sentences():
    assert TEXT["en"].keys() == TEXT["roman_ur"].keys() == TEXT["ur"].keys()
    for lang in TEXT:
        assert len(TEXT[lang]["days"]) == 7


@pytest.mark.parametrize("language", ["en", "roman_ur", "ur"])
def test_the_summary_is_filled_in_completely_in_every_language(fake_posthog, language):
    s = rules_summary(sample_data(fake_posthog), language)
    text = " ".join([s.headline, *s.bullets, s.recommendation])
    assert "{" not in text and "}" not in text, text  # no placeholder was left unfilled
    assert "120" in s.headline and "/shop" in s.bullets[0] and "220" in s.bullets[0]
    assert s.source == "rules" and len(s.bullets) >= 5
    assert any("33" in b for b in s.bullets)  # the most common action


def test_the_urdu_summary_is_in_urdu_script_and_roman_urdu_is_latin(fake_posthog):
    data = sample_data(fake_posthog)
    assert any("؀" <= ch <= "ۿ" for ch in rules_summary(data, "ur").headline)
    roman = rules_summary(data, "roman_ur").headline
    assert roman.isascii() and "log" in roman


@pytest.mark.parametrize("visitors, previous, expected", [
    (120, 100, "up 20%"), (80, 100, "down 20%"), (101, 100, "about the same"), (50, 0, "no data to compare"),
])
def test_the_trend_sentence(fake_posthog, visitors, previous, expected):
    assert expected in rules_summary(sample_data(fake_posthog, visitors=visitors, prev_visitors=previous), "en").headline


def test_the_recommendation_depends_on_what_happened(fake_posthog):
    assert "leave after one page" in rules_summary(sample_data(fake_posthog, bounce=0.8), "en").recommendation
    assert "went down" in rules_summary(sample_data(fake_posthog, visitors=60, prev_visitors=100, bounce=0.3), "en").recommendation
    assert "good week" in rules_summary(sample_data(fake_posthog, visitors=150, prev_visitors=100, bounce=0.3), "en").recommendation
    assert "Pick one page" in rules_summary(sample_data(fake_posthog, visitors=102, prev_visitors=100, bounce=0.3), "en").recommendation


def test_a_quiet_week_says_so(fake_posthog):
    s = rules_summary(sample_data(fake_posthog, no_data=True), "en")
    assert "Nobody visited" in s.headline and s.bullets == []


# ------------------------------------------------------------------ the AI summary


def run_ai(data, language="en", model="claude-opus-5-5"):
    return asyncio.run(summary.write_summary(data, language, ai_enabled=True, model=model))


def test_the_ai_writes_the_summary_when_it_works(fake_posthog, fake_ai):
    ai = fake_ai(reply=GOOD_AI_REPLY)
    result = run_ai(sample_data(fake_posthog), "roman_ur", model="claude-haiku-5-5")
    assert result.source == "ai" and result.headline == GOOD_AI_REPLY["headline"] and len(result.bullets) == 2

    [call] = ai.calls
    assert call["model"] == "claude-haiku-5-5"  # the admin's setting
    assert call["output_config"]["effort"] == "low" and call["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in call  # (on current models thinking must be left to adapt; we never disable it)
    assert "Roman Urdu" in call["system"] and "ONLY the numbers" in call["system"]
    sent = json.loads(call["messages"][0]["content"].split("\n", 1)[1])
    assert sent["kpis"]["visitors"]["current"] == 120 and set(sent) >= {"week", "kpis", "top_pages", "sources", "devices"}
    assert "email" not in json.dumps(sent).lower() and "person" not in json.dumps(sent).lower()  # aggregated numbers only


@pytest.mark.parametrize("scenario", ["no_key", "api_error", "refusal", "cut_off", "not_json", "missing_field", "too_long", "wrong_types", "empty_bullets"])
def test_any_ai_problem_falls_back_to_the_rules(fake_posthog, fake_ai, monkeypatch, scenario):
    if scenario == "no_key":
        monkeypatch.setattr(summary, "make_ai_client", lambda: None)
    elif scenario == "api_error":
        fake_ai(error=api_error())
    elif scenario == "refusal":
        fake_ai(reply=GOOD_AI_REPLY, stop_reason="refusal")
    elif scenario == "cut_off":
        fake_ai(reply=GOOD_AI_REPLY, stop_reason="max_tokens")
    elif scenario == "not_json":
        fake_ai(reply="Sure! Here is your report: ...")
    elif scenario == "missing_field":
        fake_ai(reply={"headline": "x", "bullets": ["y"]})
    elif scenario == "too_long":
        fake_ai(reply={**GOOD_AI_REPLY, "headline": "x" * 500})
    elif scenario == "wrong_types":
        fake_ai(reply={"headline": 5, "bullets": "no", "recommendation": None})
    elif scenario == "empty_bullets":
        fake_ai(reply={**GOOD_AI_REPLY, "bullets": []})
    result = run_ai(sample_data(fake_posthog))
    assert result.source == "rules" and "120 people visited" in result.headline  # always a usable summary


def test_ai_can_be_switched_off(fake_posthog, fake_ai):
    ai = fake_ai(reply=GOOD_AI_REPLY)
    result = asyncio.run(summary.write_summary(sample_data(fake_posthog), "en", ai_enabled=False, model="x"))
    assert result.source == "rules" and ai.calls == []


def test_no_key_means_no_client():
    assert summary.make_ai_client() is None  # the test environment has no ANTHROPIC_API_KEY


# ------------------------------------------------------------------ generating, storing and replacing


def generate(site, **kwargs):
    return asyncio.run(service.generate_report(site.id, START, END, **kwargs))


def test_a_generated_report_is_stored_and_regenerating_replaces_it(db, world, fake_posthog):
    answers(fake_posthog)
    first = generate(world.site_a)
    answers(fake_posthog, visitors=200)
    second = generate(world.site_a, generated_by="admin", language="ur")
    assert first == second  # the same row
    db.expire_all()
    [report] = db.scalars(select(Report).where(Report.website_id == world.site_a.id)).all()
    assert report.data["kpis"]["visitors"]["current"] == 200 and report.language == "ur" and report.generated_by == "admin"
    assert (report.period_start, report.period_end) == (START, END) and report.summary_source == "rules"
    assert report.client_id == world.client_a.id


def test_the_clients_language_is_used_and_the_ai_is_asked_for_it(db, world, fake_posthog, fake_ai):
    world.client_a.report_language = "roman_ur"
    db.merge(world.client_a)
    db.commit()
    answers(fake_posthog)
    ai = fake_ai(reply=GOOD_AI_REPLY)
    generate(world.site_a)
    db.expire_all()
    report = db.scalars(select(Report)).one()
    assert report.language == "roman_ur" and report.summary_source == "ai" and "Roman Urdu" in ai.calls[0]["system"]


def test_the_model_and_the_switch_come_from_settings(db, world, fake_posthog, fake_ai, api):
    admin = api("admin@agency.test")
    admin.patch("/api/admin/settings", json={"values": {"ai.model": "claude-sonnet-5-5"}})
    answers(fake_posthog)
    ai = fake_ai(reply=GOOD_AI_REPLY)
    generate(world.site_a)
    assert ai.calls[0]["model"] == "claude-sonnet-5-5"
    admin.patch("/api/admin/settings", json={"values": {"ai.enabled": False}})
    generate(world.site_a)
    assert len(ai.calls) == 1  # not asked again
    db.expire_all()
    assert db.scalars(select(Report)).one().summary_source == "rules"


# ------------------------------------------------------------------ email and PDF


def make_report(db, world, fake_posthog, language="en", site=None):
    answers(fake_posthog)
    return generate(site or world.site_a, language=language)


def test_the_report_email_has_html_text_and_a_pdf_for_the_owners(db, world, fake_posthog, emails):
    report_id = make_report(db, world, fake_posthog)
    assert service.send_report(report_id) == 1  # alice is the owner; vera (viewer) is not emailed
    [mail] = emails
    assert mail["to"] == "alice@a.test" and "Client A site" in mail["subject"] and "5-11 Oct 2026" in mail["subject"]
    assert "120 people visited" in mail["body"] and "/shop" in mail["body"]
    assert "Open your dashboard" in mail["html"] and f"/reports/{report_id}" in mail["html"]
    filename, content, mime = mail["attachments"][0]
    assert filename == "weekly-report-2026-10-11.pdf" and mime == "application/pdf" and content.startswith(b"%PDF-")
    db.expire_all()
    report = db.get(Report, report_id)
    assert report.emailed_at is not None and report.emailed_to == 1


def test_data_from_the_visitors_cannot_inject_html_into_the_email(db, world, fake_posthog, emails):
    service.send_report(make_report(db, world, fake_posthog))
    html = emails[0]["html"]
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


@pytest.mark.parametrize("language, rtl", [("en", False), ("roman_ur", False), ("ur", True)])
def test_every_language_renders_html_and_pdf(db, world, fake_posthog, emails, language, rtl):
    report_id = make_report(db, world, fake_posthog, language=language)
    service.send_report(report_id)
    assert ('dir="rtl"' in emails[0]["html"]) is rtl
    pdf = emails[0]["attachments"][0][1]
    assert pdf.startswith(b"%PDF-") and len(pdf) > 1500


def test_a_pdf_survives_odd_names(db, world, fake_posthog):
    world.site_a.name = "شاپ Ali’s ✓ café"
    db.merge(world.site_a)
    db.commit()
    report_id = make_report(db, world, fake_posthog, language="ur")
    assert service.render_report_pdf(db, db.get(Report, report_id)).startswith(b"%PDF-")


def test_no_email_when_email_is_not_set_up_or_nobody_owns_the_account(db, world, fake_posthog, monkeypatch, emails):
    report_id = make_report(db, world, fake_posthog)
    monkeypatch.setattr(emailer, "email_configured", lambda: False)
    assert service.send_report(report_id) == 0
    monkeypatch.setattr(emailer, "email_configured", lambda: True)
    bob_report = make_report(db, world, fake_posthog, site=world.site_b)
    from app.models import ClientMember

    db.query(ClientMember).filter(ClientMember.client_id == world.client_b.id).delete()
    db.commit()
    assert service.send_report(bob_report) == 0 and emails == []
    db.expire_all()
    assert db.get(Report, report_id).emailed_at is None


# ------------------------------------------------------------------ which reports are due


NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)  # Monday 10:00 in Karachi: past 08:00


def due(db, now=NOW):
    return {str(w) for w, _, _ in service.due_websites(db, now)}


def test_every_active_website_is_due_on_monday_morning(db, world):
    assert due(db) == {str(world.site_a.id), str(world.site_b.id)}
    assert due(db, datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)) == set()  # 07:00 in Karachi


def test_clients_can_opt_out_and_plans_can_exclude_reports(db, world):
    world.client_a.weekly_report_enabled = False
    starter = Plan(name="Starter", slug="s", features={k: False for k in FEATURES}, price_pkr=1, price_usd=1)
    db.add(starter)
    db.commit()
    db.add(Subscription(client_id=world.client_b.id, plan_id=starter.id, started_at=date(2026, 1, 1), billing_day=1))
    db.merge(world.client_a)
    db.commit()
    assert due(db) == set()  # A opted out, B's plan doesn't include weekly reports
    starter.features = {**starter.features, "weekly_reports": True}
    db.merge(starter)
    db.commit()
    assert due(db) == {str(world.site_b.id)}


def test_suspended_clients_and_inactive_websites_are_skipped(db, world):
    world.client_a.status = "suspended"
    world.site_b.is_active = False
    db.merge(world.client_a)
    db.merge(world.site_b)
    db.commit()
    assert due(db) == set()


def test_a_week_is_reported_once(db, world, fake_posthog):
    answers(fake_posthog)
    asyncio.run(service.generate_report(world.site_a.id, date(2026, 10, 5), date(2026, 10, 11)))
    assert str(world.site_a.id) not in due(db)
    assert str(world.site_a.id) in due(db, datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc))  # next week it is due again


# ------------------------------------------------------------------ the weekly job


@pytest.fixture
def monday_morning(monkeypatch):
    """The weekly job asks 'what is due right now?'. Pin 'now' to a Monday morning."""
    from app.jobs import reports as reports_job

    real = service.due_websites
    monkeypatch.setattr(reports_job.service, "due_websites", lambda db_, now=None: real(db_, NOW))


def test_the_weekly_job_makes_and_emails_reports_once(db, world, fake_posthog, emails, monday_morning):
    answers(fake_posthog)
    result = asyncio.run(run_job("weekly_reports", "test"))
    assert result["status"] == "ok" and "2 reports made, 2 emailed" in result["message"]
    assert sorted(m["to"] for m in emails) == ["alice@a.test", "bob@b.test"]
    again = asyncio.run(run_job("weekly_reports", "test"))
    assert "0 reports made" in again["message"] and len(emails) == 2


def test_when_every_website_fails_the_job_fails_and_alerts(db, world, fake_posthog, monkeypatch):
    from app.posthog_client import AnalyticsError

    monkeypatch.setattr(service, "due_websites", lambda db_, now=None: [(world.site_a.id, START, END)])

    async def boom(*a, **k):
        raise AnalyticsError(502, "no", upstream_status=401, upstream_detail="bad key")

    monkeypatch.setattr(service, "generate_report", boom)
    result = asyncio.run(run_job("weekly_reports", "test"))
    assert result["status"] == "error"
    db.expire_all()
    assert db.scalar(select(Alert).where(Alert.dedupe_key == "job_failed:weekly_reports", Alert.status == "open")) is not None


# ------------------------------------------------------------------ the API for clients


def seed_report(db, world, site=None, **overrides):
    site = site or world.site_a
    data = sample_data_static()
    s = rules_summary(data, "en")
    report = Report(website_id=site.id, client_id=site.client_id, period_start=START, period_end=END, language="en", data=data, summary=s.as_dict(), summary_source="rules", **overrides)
    db.add(report)
    db.commit()
    return report


def sample_data_static():
    return {
        "period": {"start": "2026-10-05", "end": "2026-10-11", "days": 7},
        "kpis": {"visitors": {"current": 120, "previous": 100, "change_pct": 20.0}, "pageviews": {"current": 400, "previous": 300, "change_pct": 33.3},
                 "sessions": {"current": 150, "previous": 130, "change_pct": 15.4}, "avg_session_duration": {"current": 134, "previous": 120, "change_pct": 11.7},
                 "bounce_rate": {"current": 40.0, "previous": 50.0, "change_pct": -20.0}},
        "daily": [{"date": f"2026-10-{n:02d}", "visitors": n, "pageviews": n * 2} for n in range(5, 12)],
        "top_pages": [{"path": "/shop", "views": 220, "visitors": 90}], "sources": [{"name": "Direct", "sessions": 80}], "channels": [],
        "countries": [{"name": "Pakistan", "visitors": 100}], "devices": [{"name": "Mobile", "visitors": 90}], "custom_events": [{"event": "cta_click", "count": 10}],
    }


def test_a_client_reads_its_reports_and_pdf(api, db, world):
    report = seed_report(db, world)
    alice = api("alice@a.test")
    listing = alice.get(f"/api/websites/{world.site_a.id}/reports").json()["results"]
    assert [r["id"] for r in listing] == [str(report.id)] and "data" not in listing[0] and listing[0]["summary"]["headline"]
    detail = alice.get(f"/api/websites/{world.site_a.id}/reports/{report.id}").json()
    assert detail["data"]["kpis"]["visitors"]["current"] == 120 and detail["website_name"] == "Client A site"
    pdf = alice.get(f"/api/websites/{world.site_a.id}/reports/{report.id}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-") and "weekly-report-2026-10-11" in pdf.headers["content-disposition"]
    assert api("vera@a.test").get(f"/api/websites/{world.site_a.id}/reports").status_code == 200  # viewers may read them


def test_reports_never_cross_between_clients(api, db, world):
    mine, theirs = seed_report(db, world), seed_report(db, world, site=world.site_b)
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_b.id}/reports").status_code == 404
    assert alice.get(f"/api/websites/{world.site_a.id}/reports/{theirs.id}").status_code == 404  # B's report through A's URL
    assert alice.get(f"/api/websites/{world.site_a.id}/reports/{theirs.id}/pdf").status_code == 404
    assert [r["id"] for r in alice.get(f"/api/websites/{world.site_a.id}/reports").json()["results"]] == [str(mine.id)]


def test_the_report_pages_need_a_plan_that_includes_them(api, db, world):
    report = seed_report(db, world)
    plan = Plan(name="Starter", slug="s2", features={k: False for k in FEATURES}, price_pkr=1, price_usd=1)
    db.add(plan)
    db.commit()
    db.add(Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=date(2026, 1, 1), billing_day=1))
    db.commit()
    for path in ("", f"/{report.id}", f"/{report.id}/pdf"):
        response = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/reports{path}")
        assert response.status_code == 403 and "Weekly reports" in response.json()["detail"]
    assert api("admin@agency.test").get(f"/api/websites/{world.site_a.id}/reports").status_code == 200


def test_report_data_never_leaks_secrets(api, db, world):
    report = seed_report(db, world)
    text = api("alice@a.test").get(f"/api/websites/{world.site_a.id}/reports/{report.id}").text
    assert "phx_" not in text and "posthog" not in text.lower()


# ------------------------------------------------------------------ the admin button


def test_the_admin_can_make_and_email_a_report_now(api, db, world, fake_posthog, emails):
    answers(fake_posthog)
    admin = api("admin@agency.test")
    made = admin.post(f"/api/admin/websites/{world.site_a.id}/reports", json={"send": True, "language": "roman_ur"})
    assert made.status_code == 201 and made.json()["emailed_to"] == 1
    db.expire_all()
    report = db.scalars(select(Report)).one()
    assert report.generated_by == "admin" and report.language == "roman_ur" and str(report.id) == made.json()["report_id"]
    assert (report.period_end - report.period_start).days == 6 and report.period_end.weekday() == 6  # a Mon-Sun week


def test_the_admin_report_button_validates(api, world, fake_posthog, monkeypatch):
    admin = api("admin@agency.test")
    assert admin.post(f"/api/admin/websites/{world.site_a.id}/reports", json={"language": "klingon"}).status_code == 400
    monkeypatch.setattr(emailer, "email_configured", lambda: False)
    assert admin.post(f"/api/admin/websites/{world.site_a.id}/reports", json={"send": True}).status_code == 409
    assert admin.post("/api/admin/websites/00000000-0000-0000-0000-000000000000/reports", json={}).status_code == 404
    assert api("alice@a.test").post(f"/api/admin/websites/{world.site_a.id}/reports", json={}).status_code == 403


def test_one_visitor_reads_naturally(fake_posthog):
    s = rules_summary(sample_data(fake_posthog, visitors=1, prev_visitors=1), "en")
    assert s.headline.startswith("1 person visited") and "people" not in s.headline


# ------------------------------------------------------------------ the store's week inside the report (Phase 9)


def with_store(db, world):
    from tests.test_shopify import at, connect_in_db, seed_orders

    connect_in_db(db, world.site_a)
    # The report week is the last full Monday-Sunday week before today: put orders in it, and in the week before.
    start, end = service.last_full_week(datetime.now(service.client_zone(world.client_a)).date())
    mid = datetime.combine(start + timedelta(days=2), datetime.min.time(), service.client_zone(world.client_a)).replace(hour=12)
    before = mid - timedelta(days=7)
    seed_orders(db, world.site_a, [
        (mid, "3000.00", {"items": [("Hoodie", 2, "3000.00")]}), (mid + timedelta(hours=2), "1000.00", {"items": [("Cap", 1, "1000.00")]}),
        (before, "2000.00", {"items": [("Hoodie", 1, "2000.00")]}),
        (mid, "9999.00", {"is_test": True}),
    ])
    return start, end


def test_the_report_includes_the_stores_week(db, world, fake_posthog, emails):
    start, end = with_store(db, world)
    answers(fake_posthog)
    report_id = asyncio.run(service.generate_report(world.site_a.id, start, end))
    db.expire_all()
    report = db.get(Report, report_id)
    sales = report.data["sales"]
    assert sales["currency"] == "PKR" and sales["orders"] == {"current": 2, "previous": 1, "change_pct": 100.0}
    assert sales["revenue"]["current"] == 4000.0 and sales["revenue"]["previous"] == 2000.0 and sales["top_product"]["title"] == "Hoodie"
    assert report.summary["bullets"][0] == "Orders this week: 2, worth PKR 4,000 (up 100% from last week)."
    assert report.summary["bullets"][1] == "Your best seller was Hoodie."
    service.send_report(report_id)
    assert "Your store:" in emails[0]["body"] and "PKR 4,000" in emails[0]["body"]
    assert ">Your store<" in emails[0]["html"] and "Hoodie" in emails[0]["html"]
    assert emails[0]["attachments"][0][1].startswith(b"%PDF-")


@pytest.mark.parametrize("language", ["roman_ur", "ur"])
def test_the_store_sentence_exists_in_every_language(db, world, fake_posthog, language):
    start, end = with_store(db, world)
    answers(fake_posthog)
    report_id = asyncio.run(service.generate_report(world.site_a.id, start, end, language=language))
    db.expire_all()
    bullets = db.get(Report, report_id).summary["bullets"]
    assert "4,000" in bullets[0] and "Hoodie" in bullets[1] and "{" not in " ".join(bullets)


def test_no_store_or_no_plan_means_no_store_section(db, world, fake_posthog):
    start, end = service.last_full_week(date.today())
    answers(fake_posthog)
    report_id = asyncio.run(service.generate_report(world.site_a.id, start, end))  # no store connected
    db.expire_all()
    assert "sales" not in db.get(Report, report_id).data

    with_store(db, world)
    plan = Plan(name="NoShop", slug="noshop", features={**{k: True for k in FEATURES}, "shopify": False}, price_pkr=1, price_usd=1)
    db.add(plan)
    db.commit()
    db.add(Subscription(client_id=world.client_a.id, plan_id=plan.id, started_at=date(2026, 1, 1), billing_day=1))
    db.commit()
    report_id = asyncio.run(service.generate_report(world.site_a.id, start, end))
    db.expire_all()
    assert "sales" not in db.get(Report, report_id).data  # the plan doesn't include it: not in the report either


def test_the_ai_gets_the_store_numbers_too(db, world, fake_posthog, fake_ai):
    start, end = with_store(db, world)
    answers(fake_posthog)
    ai = fake_ai(reply=GOOD_AI_REPLY)
    asyncio.run(service.generate_report(world.site_a.id, start, end))
    sent = json.loads(ai.calls[0]["messages"][0]["content"].split("\n", 1)[1])
    assert sent["store_sales"]["revenue"]["current"] == 4000.0
    assert "order" not in json.dumps(sent["store_sales"]).replace("orders", "").replace("average_order_value", "")  # no individual orders or names
