"""
The plain-language summary of a weekly report, in English, Roman Urdu or Urdu.

Two writers:
  - `rules_summary`: fixed sentences filled with the real numbers. Always available, free, predictable.
  - `ai_summary`: Claude writes it from the same numbers. Used when ANTHROPIC_API_KEY is set (and `ai.enabled`);
    any problem (no key, API error, refusal, malformed answer) quietly falls back to the rules.

The Roman Urdu and Urdu sentence templates were written by an AI: have a native speaker read them once
and fix the wording to match how your customers talk. They are all in TEXT below.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import anthropic

from app.config import settings

log = logging.getLogger(__name__)

LANGUAGES = {"en": "English", "roman_ur": "Roman Urdu", "ur": "Urdu"}


@dataclass
class Summary:
    headline: str
    bullets: list[str]
    recommendation: str
    source: str  # "ai" or "rules"

    def as_dict(self) -> dict[str, Any]:
        return {"headline": self.headline, "bullets": self.bullets, "recommendation": self.recommendation}


# ------------------------------------------------------------------ rule-based writer

# {placeholders} are filled with numbers from the report. Keep them intact when editing a sentence.
TEXT: dict[str, dict[str, Any]] = {
    "en": {
        "headline": "{visitors} {people} visited your website this week ({trend}).",
        "person_one": "person",
        "person_many": "people",
        "no_visitors": "Nobody visited your website this week.",
        "trend_up": "up {pct}% from last week",
        "trend_down": "down {pct}% from last week",
        "trend_same": "about the same as last week",
        "trend_new": "last week had no data to compare with",
        "top_page": "Your most viewed page was {path} ({views} views).",
        "top_source": "Most visits came from {source} ({share}% of visits).",
        "mobile": "{pct}% of visitors used a phone.",
        "engagement": "People stayed {duration} on average, and {bounce}% left after seeing just one page.",
        "best_day": "Your busiest day was {day} (with {n} {people}).",
        "sales": "Orders this week: {orders}, worth {amount} ({trend}).",
        "sales_top": "Your best seller was {product}.",
        "top_event": "The most common action was {event} ({n} times).",
        "rec_bounce": "Many visitors leave after one page. Check that the first screen is clear and opens fast on a phone.",
        "rec_down": "Visitors went down. Post on social media or message your customers to bring people back.",
        "rec_up": "A good week! Keep doing what you did, and make sure your most viewed page has a clear button to message you or buy.",
        "rec_default": "Pick one page to improve this week, then compare next week's numbers.",
        "direct": "Direct visits",
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "duration": "{m}m {s}s",
        "duration_short": "{s}s",
    },
    "roman_ur": {
        "headline": "Is hafte {visitors} log aap ki website par aaye ({trend}).",
        "person_one": "banda",
        "person_many": "log",
        "sales": "Is hafte orders: {orders}, kul {amount} ({trend}).",
        "sales_top": "Sab se zyada bikne wali cheez: {product}.",
        "no_visitors": "Is hafte aap ki website par koi visitor nahi aaya.",
        "trend_up": "pichle hafte se {pct}% zyada",
        "trend_down": "pichle hafte se {pct}% kam",
        "trend_same": "pichle hafte jitne hi",
        "trend_new": "pichle hafte ka data nahi tha",
        "top_page": "Sab se ziyada dekha gaya page {path} tha ({views} views).",
        "top_source": "Zyada tar visits {source} se aaye ({share}% visits).",
        "mobile": "{pct}% visitors ne mobile phone istemal kiya.",
        "engagement": "Log average {duration} rukay, aur {bounce}% sirf ek page dekh kar chale gaye.",
        "best_day": "Sab se busy din {day} tha ({n} visitors).",
        "top_event": "Sab se ziyada hone wala action {event} tha ({n} dafa).",
        "rec_bounce": "Bohat se log sirf ek page dekh kar chale jaate hain. Check karein ke pehli screen saaf hai aur phone par jaldi khulti hai.",
        "rec_down": "Visitors kam hue hain. Social media par post karein ya apne customers ko message bhejein.",
        "rec_up": "Bohat achha hafta! Jo aap ne kiya wo jari rakhein, aur apne sab se ziyada dekhe jane wale page par WhatsApp ya Buy ka button zaroor rakhein.",
        "rec_default": "Is hafte ek page behtar banayein, phir agle hafte ke numbers se compare karein.",
        "direct": "Direct (seedha address)",
        "days": ["Peer", "Mangal", "Budh", "Jumeraat", "Jumma", "Hafta", "Itwaar"],
        "duration": "{m} minute {s} second",
        "duration_short": "{s} second",
    },
    "ur": {
        "headline": "اس ہفتے {visitors} لوگ آپ کی ویب سائٹ پر آئے ({trend})۔",
        "person_one": "شخص",
        "person_many": "لوگ",
        "sales": "اس ہفتے آرڈرز: {orders}، کل {amount} ({trend})۔",
        "sales_top": "سب سے زیادہ بکنے والی چیز: {product}۔",
        "no_visitors": "اس ہفتے آپ کی ویب سائٹ پر کوئی وزیٹر نہیں آیا۔",
        "trend_up": "پچھلے ہفتے سے {pct}% زیادہ",
        "trend_down": "پچھلے ہفتے سے {pct}% کم",
        "trend_same": "پچھلے ہفتے جتنے ہی",
        "trend_new": "پچھلے ہفتے کا ڈیٹا نہیں تھا",
        "top_page": "سب سے زیادہ دیکھا جانے والا صفحہ {path} تھا ({views} ویوز)۔",
        "top_source": "زیادہ تر وزٹس {source} سے آئے ({share}% وزٹس)۔",
        "mobile": "{pct}% وزیٹرز نے موبائل فون استعمال کیا۔",
        "engagement": "لوگ اوسطاً {duration} رکے، اور {bounce}% صرف ایک صفحہ دیکھ کر چلے گئے۔",
        "best_day": "سب سے مصروف دن {day} تھا ({n} وزیٹرز)۔",
        "top_event": "سب سے زیادہ ہونے والا عمل {event} تھا ({n} بار)۔",
        "rec_bounce": "بہت سے لوگ صرف ایک صفحہ دیکھ کر چلے جاتے ہیں۔ دیکھیں کہ پہلی اسکرین واضح ہو اور موبائل پر جلدی کھلے۔",
        "rec_down": "وزیٹرز کم ہوئے ہیں۔ سوشل میڈیا پر پوسٹ کریں یا اپنے کسٹمرز کو پیغام بھیجیں۔",
        "rec_up": "بہت اچھا ہفتہ! جو آپ نے کیا اسے جاری رکھیں، اور اپنے سب سے زیادہ دیکھے جانے والے صفحے پر واٹس ایپ یا خریدیں کا بٹن ضرور رکھیں۔",
        "rec_default": "اس ہفتے ایک صفحہ بہتر بنائیں، پھر اگلے ہفتے کے اعداد سے موازنہ کریں۔",
        "direct": "براہ راست",
        "days": ["پیر", "منگل", "بدھ", "جمعرات", "جمعہ", "ہفتہ", "اتوار"],
        "duration": "{m} منٹ {s} سیکنڈ",
        "duration_short": "{s} سیکنڈ",
    },
}


def _duration(seconds: float, t: dict[str, Any]) -> str:
    seconds = int(round(seconds))
    return t["duration"].format(m=seconds // 60, s=seconds % 60) if seconds >= 60 else t["duration_short"].format(s=seconds)


def _trend(change: float | None, t: dict[str, Any]) -> str:
    """"up 20% from last week" / "about the same" / "no data to compare with"."""
    if change is None:
        return t["trend_new"]
    if abs(change) < 3:
        return t["trend_same"]
    return t["trend_up" if change > 0 else "trend_down"].format(pct=abs(round(change)))


def money_text(currency: str, amount: float) -> str:
    return f"{currency} {amount:,.0f}".strip()


def rules_summary(data: dict[str, Any], language: str = "en") -> Summary:
    t = TEXT.get(language, TEXT["en"])
    kpis = data["kpis"]
    visitors = kpis["visitors"]["current"]
    if visitors == 0:
        return Summary(t["no_visitors"], [], t["rec_default"], "rules")

    change = kpis["visitors"]["change_pct"]
    trend = _trend(change, t)
    people = t["person_one" if visitors == 1 else "person_many"]  # "1 person" / "5 people"
    headline = t["headline"].format(visitors=visitors, trend=trend, people=people)

    bullets: list[str] = []
    sales = data.get("sales")  # present when the client has a connected Shopify store
    if sales and sales["orders"]["current"] > 0:
        bullets.append(t["sales"].format(orders=sales["orders"]["current"], amount=money_text(sales["currency"], sales["revenue"]["current"]), trend=_trend(sales["revenue"]["change_pct"], t)))
        if sales.get("top_product"):
            bullets.append(t["sales_top"].format(product=sales["top_product"]["title"]))
    if data["top_pages"]:
        page = data["top_pages"][0]
        bullets.append(t["top_page"].format(path=page["path"], views=page["views"]))
    sessions_total = sum(s["sessions"] for s in data["sources"]) or 0
    if data["sources"] and sessions_total:
        top = data["sources"][0]
        name = t["direct"] if top["name"] == "Direct" else top["name"]
        bullets.append(t["top_source"].format(source=name, share=round(top["sessions"] / sessions_total * 100)))
    device_total = sum(d["visitors"] for d in data["devices"])
    mobile = sum(d["visitors"] for d in data["devices"] if d["name"].lower() in ("mobile", "tablet"))
    if device_total:
        bullets.append(t["mobile"].format(pct=round(mobile / device_total * 100)))
    bounce = kpis["bounce_rate"]["current"]
    if kpis["sessions"]["current"]:
        bullets.append(t["engagement"].format(duration=_duration(kpis["avg_session_duration"]["current"], t), bounce=round(bounce)))
    busiest = max(data["daily"], key=lambda d: d["visitors"], default=None)
    if busiest and busiest["visitors"] > 0:
        weekday = date.fromisoformat(busiest["date"]).weekday()
        bullets.append(t["best_day"].format(day=t["days"][weekday], n=busiest["visitors"], people=t["person_one" if busiest["visitors"] == 1 else "person_many"]))
    if data["custom_events"]:
        top_event = data["custom_events"][0]
        bullets.append(t["top_event"].format(event=top_event["event"], n=top_event["count"]))

    if bounce >= 70:
        recommendation = t["rec_bounce"]
    elif change is not None and change <= -20:
        recommendation = t["rec_down"]
    elif change is not None and change >= 20:
        recommendation = t["rec_up"]
    else:
        recommendation = t["rec_default"]
    return Summary(headline, bullets, recommendation, "rules")


# ------------------------------------------------------------------ AI writer

SYSTEM_PROMPT = """You write the weekly website report summary for owners of small businesses in Pakistan. They are not technical.

Rules:
- Use ONLY the numbers in the JSON you are given. Never invent numbers, causes, competitors or trends that the data doesn't show.
- Plain words, no jargon: say "visitors", "people left after one page" (not "bounce rate"), "phone" (not "mobile traffic").
- Be honest and kind: if traffic fell, say so, without alarm.
- Write in {language}. {language_note}
- headline: one sentence with the most important fact of the week.
- bullets: 3 to 5 short bullets, each stating one fact from the data with its number.
- recommendation: ONE concrete action the owner can do this week.
- No emojis, no markdown, no greeting, no sign-off."""

LANGUAGE_NOTES = {
    "en": "",
    "roman_ur": "Write Urdu using the Latin alphabet, the way people write on WhatsApp in Pakistan. Keep numbers as digits.",
    "ur": "Write in Urdu script. Keep numbers as ordinary digits (0-9).",
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string"},
    },
    "required": ["headline", "bullets", "recommendation"],
    "additionalProperties": False,
}


def make_ai_client() -> anthropic.AsyncAnthropic | None:
    """The Claude client, or None when no key is configured. (Tests replace this function.)"""
    if not settings.anthropic_api_key:
        return None
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=90.0, max_retries=2)


def _ai_input(data: dict[str, Any]) -> dict[str, Any]:
    """Only aggregated numbers go to the AI: no names, emails or visitor ids exist in this data."""
    return {
        "week": data["period"],
        "kpis": data["kpis"],
        "visitors_per_day": [{"date": d["date"], "visitors": d["visitors"]} for d in data["daily"]],
        "top_pages": data["top_pages"],
        "sources": data["sources"],
        "channels": data["channels"],
        "countries": data["countries"],
        "devices": data["devices"],
        "actions": data["custom_events"],
        **({"store_sales": data["sales"]} if data.get("sales") else {}),  # orders and revenue from the client's Shopify store (money in the shop's currency)
        "notes": "avg_session_duration is in seconds; bounce_rate is the percent of visits that saw only one page; change_pct compares with the previous 7 days.",
    }


def _clean_ai_output(raw: dict[str, Any]) -> Summary | None:
    headline, recommendation, bullets = raw.get("headline"), raw.get("recommendation"), raw.get("bullets")
    if not (isinstance(headline, str) and isinstance(recommendation, str) and isinstance(bullets, list)):
        return None
    bullets = [b.strip() for b in bullets if isinstance(b, str) and b.strip()]
    if not headline.strip() or not recommendation.strip() or not 1 <= len(bullets) <= 8:
        return None
    # A sanity limit so a runaway answer can't flood an email.
    if len(headline) > 400 or len(recommendation) > 600 or any(len(b) > 400 for b in bullets):
        return None
    return Summary(headline.strip(), bullets[:6], recommendation.strip(), "ai")


async def ai_summary(data: dict[str, Any], language: str, model: str) -> Summary | None:
    """Ask Claude for the summary. Returns None (and the caller uses the rules) on ANY problem."""
    client = make_ai_client()
    if client is None:
        return None
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM_PROMPT.format(language=LANGUAGES.get(language, "English"), language_note=LANGUAGE_NOTES.get(language, "")),
            messages=[{"role": "user", "content": "Here are this week's numbers:\n" + json.dumps(_ai_input(data), ensure_ascii=False)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            log.warning("AI summary not used: stop_reason=%s", response.stop_reason)
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        return _clean_ai_output(json.loads(text)) if text else None
    except (anthropic.APIError, ValueError, TypeError, StopIteration):
        # APIError covers rate limits, overload, bad key, network. ValueError: the JSON wasn't valid.
        log.exception("AI summary failed; using the rule-based summary instead")
        return None


async def write_summary(data: dict[str, Any], language: str, *, ai_enabled: bool, model: str) -> Summary:
    if ai_enabled:
        summary = await ai_summary(data, language, model)
        if summary is not None:
            return summary
    return rules_summary(data, language)
