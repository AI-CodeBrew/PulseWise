"""
Settings an admin can change in the admin panel (stored in the `app_settings` table).

Every setting has a default in the code below; the database only holds values that were changed.
Secrets never go here (those stay in backend/.env).
"""

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting

Kind = Literal["int", "float", "bool", "line", "text"]


class SettingError(ValueError):
    """The value is not acceptable (the message is safe to show to the admin)."""


@dataclass(frozen=True)
class SettingDef:
    key: str
    default: Any
    kind: Kind
    label: str
    help: str = ""
    group: str = "General"
    minimum: float | None = None
    maximum: float | None = None


_DEFS = [
    SettingDef("alerts.no_events_hours", 48, "int", "Alert when a website sends no events for (hours)",
               "Raised once a website has been quiet this long (and is older than this).", "Alerts", 6, 720),
    SettingDef("alerts.extra_recipients", "", "line", "Extra alert emails",
               "Comma-separated. All admins always receive alert emails (once email sending is configured).", "Alerts"),
    SettingDef("usage.warn_percent", 80, "int", "Warn at this % of a plan's event limit",
               "An alert is raised when a client's month-to-date events reach this share of their plan.", "Usage", 10, 100),
]

SETTINGS: dict[str, SettingDef] = {d.key: d for d in _DEFS}


def register(*definitions: SettingDef) -> None:
    """Later phases add their own settings (billing, support...)."""
    for definition in definitions:
        SETTINGS[definition.key] = definition


def _coerce(definition: SettingDef, raw: Any) -> Any:
    try:
        if definition.kind == "int":
            if isinstance(raw, bool) or (isinstance(raw, float) and raw != int(raw)):
                raise ValueError
            value: Any = int(raw)
        elif definition.kind == "float":
            if isinstance(raw, bool):
                raise ValueError
            value = float(raw)
        elif definition.kind == "bool":
            if not isinstance(raw, bool):
                raise ValueError
            value = raw
        else:
            if not isinstance(raw, str):
                raise ValueError
            value = raw.strip()
    except (TypeError, ValueError):
        kind_word = {"int": "number", "float": "number", "bool": "yes/no value"}.get(definition.kind, "text")
        raise SettingError(f"{definition.label}: that is not a valid {kind_word}.") from None

    if definition.kind in ("int", "float"):
        if definition.minimum is not None and value < definition.minimum:
            raise SettingError(f"{definition.label} must be at least {definition.minimum:g}.")
        if definition.maximum is not None and value > definition.maximum:
            raise SettingError(f"{definition.label} must be at most {definition.maximum:g}.")
    elif definition.kind in ("line", "text"):
        limit = 300 if definition.kind == "line" else 4000
        if len(value) > limit:
            raise SettingError(f"{definition.label} is too long (at most {limit} characters).")
    return value


def get_setting(db: Session, key: str) -> Any:
    definition = SETTINGS[key]
    row = db.get(AppSetting, key)
    if row is None:
        return definition.default
    try:
        return _coerce(definition, row.value)
    except SettingError:
        return definition.default  # a stored value that is no longer valid: fall back to the default


def all_settings(db: Session) -> dict[str, Any]:
    stored = {row.key: row.value for row in db.scalars(select(AppSetting))}
    out: dict[str, Any] = {}
    for key, definition in SETTINGS.items():
        try:
            out[key] = _coerce(definition, stored[key]) if key in stored else definition.default
        except SettingError:
            out[key] = definition.default
    return out


def set_settings(db: Session, changes: dict[str, Any]) -> list[str]:
    """Validate everything first, then save: all or nothing. Returns the keys that were changed."""
    clean: dict[str, Any] = {}
    for key, raw in changes.items():
        if key not in SETTINGS:
            raise SettingError(f"Unknown setting '{key}'.")
        clean[key] = _coerce(SETTINGS[key], raw)

    changed = []
    for key, value in clean.items():
        row = db.get(AppSetting, key)
        if value == SETTINGS[key].default:
            if row is not None:
                db.delete(row)  # back to the default: no need to keep a row
                changed.append(key)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
            changed.append(key)
        elif row.value != value:
            row.value = value
            changed.append(key)
    return changed


# Billing and support settings (Phase 7)
register(
    SettingDef("billing.business_name", "", "line", "Your business name on invoices", "Falls back to the product name.", "Billing"),
    SettingDef("billing.business_address", "", "text", "Your address / tax details on invoices", "Shown under your name at the top of every invoice.", "Billing"),
    SettingDef("billing.payment_instructions", "", "text", "How clients pay you",
               "Bank account, JazzCash / Easypaisa number, etc. Shown on every invoice and in the client's Billing page.", "Billing"),
    SettingDef("billing.invoice_footer", "", "line", "Footer line on invoices", "For example a thank-you or a late-payment note.", "Billing"),
    SettingDef("billing.payment_terms_days", 7, "int", "Days to pay an invoice", "The due date is the issue date plus this many days.", "Billing", 0, 90),
    SettingDef("billing.grace_days", 7, "int", "Grace period after the due date (days)",
               "Access is suspended when an invoice is still unpaid this many days after its due date.", "Billing", 0, 90),
    SettingDef("billing.email_invoices", True, "bool", "Email each new invoice to the client",
               "Needs email sending to be configured (SMTP_* in backend/.env).", "Billing"),
    SettingDef("billing.usd_to_pkr", 280.0, "float", "USD to PKR rate",
               "Only used to add USD and PKR income together in your business overview. Update it now and then.", "Billing", 1, 10000),
    SettingDef("support.whatsapp", "", "line", "Support WhatsApp number",
               "International format without + or spaces, e.g. 923001234567. Shown to clients as a Help button.", "Support"),
    SettingDef("support.email", "", "line", "Support email", "Shown to clients as a Help button.", "Support"),
)

# Weekly reports (Phase 8)
register(
    SettingDef("ai.enabled", True, "bool", "Let AI write the report summaries",
               "Needs ANTHROPIC_API_KEY in backend/.env. Without a key (or when this is off) reports use fixed, rule-based sentences instead.", "Reports"),
    SettingDef("ai.model", "claude-opus-5-5", "line", "AI model for report summaries",
               "A Claude model name. The default writes the best summaries; a smaller model (for example claude-haiku-5-5) costs less.", "Reports"),
)

# Shopify (Phase 9)
register(
    SettingDef("shopify.api_version", "2026-10", "line", "Shopify API version",
               "Shopify releases a new version every 3 months and retires old ones after about a year. If syncing starts failing with a 'version' error, set a newer one (see shopify.dev/docs/api/usage/versioning).", "Shopify"),
)

# Online payments (Phase 10)
register(
    SettingDef("billing.online_provider", "", "line", "Online payment gateway",
               "The name of a payment gateway that has been added to the code (see backend/app/billing/providers.py). Leave empty for manual payments only: the 'Pay online' button then stays hidden.", "Billing"),
)

# WhatsApp (Phase 10)
register(
    SettingDef("whatsapp.template_name", "weekly_report", "line", "WhatsApp template name",
               "The name of the approved message template in Meta's WhatsApp Manager (4 variables: website, week, headline, link). See the roadmap for the exact text.", "WhatsApp"),
    SettingDef("whatsapp.template_language", "en", "line", "WhatsApp template language code",
               "The language the template was approved in, for example en, en_US or ur.", "WhatsApp"),
    SettingDef("whatsapp.api_version", "v23.0", "line", "WhatsApp (Meta Graph) API version",
               "Meta retires old versions after a while. If sending starts failing with a version error, set a newer one.", "WhatsApp"),
)
