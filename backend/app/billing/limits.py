"""Alerts when a client's events approach or pass their plan's monthly limit.

Limits are SOFT: nothing is switched off (we can't stop PostHog from receiving events anyway). You get an alert,
decide whether to talk to the client about upgrading, and the Billing page shows them their usage.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import notify_admins, raise_alert, resolve_alerts
from app.billing.service import active_subscription, month_events, today_utc
from app.models import Client
from app.settings_store import get_setting


def evaluate_usage_limits(db: Session) -> dict[str, list[str]]:
    warn_at = get_setting(db, "usage.warn_percent")
    extra = get_setting(db, "alerts.extra_recipients")
    today = today_utc()
    result: dict[str, list[str]] = {"warning": [], "over": []}

    for client in db.scalars(select(Client)):
        sub = active_subscription(db, client.id)
        limit = sub.plan.monthly_event_limit if sub else None
        warn_key, over_key = f"usage_limit:{client.id}:warn", f"usage_limit:{client.id}:over"
        if not limit:
            resolve_alerts(db, dedupe_key=warn_key)
            resolve_alerts(db, dedupe_key=over_key)
            continue
        events = month_events(db, client.id, today)
        percent = events / limit * 100
        label = f"{client.name} has used {events:,} of the {limit:,} events in the {sub.plan.name} plan this month ({percent:.0f}%)."

        if percent >= 100:
            alert, created = raise_alert(db, kind="usage_limit", dedupe_key=over_key, client_id=client.id, severity="critical", message=label + " They are over their limit: time to talk about an upgrade.")
            resolve_alerts(db, dedupe_key=warn_key)
            result["over"].append(client.name)
        elif percent >= warn_at:
            alert, created = raise_alert(db, kind="usage_limit", dedupe_key=warn_key, client_id=client.id, severity="warning", message=label)
            resolve_alerts(db, dedupe_key=over_key)
            result["warning"].append(client.name)
        else:
            resolve_alerts(db, dedupe_key=warn_key)
            resolve_alerts(db, dedupe_key=over_key)
            continue
        if created:
            notify_admins(alert, extra)
    return result
