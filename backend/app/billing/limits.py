"""Alerts when a client's events or recordings ("videos") approach or pass their plan's monthly limit.

Limits are SOFT: nothing is switched off (we can't stop PostHog from receiving events anyway). You get an alert,
decide whether to talk to the client about upgrading (or send an extra-usage invoice), and the Billing page shows
them their usage.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import notify_admins, raise_alert, resolve_alerts
from app.billing.service import active_subscription, month_usage, today_utc
from app.models import Client
from app.settings_store import get_setting


def evaluate_usage_limits(db: Session) -> dict[str, list[str]]:
    warn_at = get_setting(db, "usage.warn_percent")
    extra = get_setting(db, "alerts.extra_recipients")
    today = today_utc()
    result: dict[str, list[str]] = {"warning": [], "over": []}

    for client in db.scalars(select(Client)):
        sub = active_subscription(db, client.id)
        events, recordings = month_usage(db, client.id, today)
        plan = sub.plan if sub else None
        # (what is counted, its limit, how it is named in the alert, the alert key. Events keep the keys they always had.)
        meters = [
            (events, plan.monthly_event_limit if plan else None, "events", f"usage_limit:{client.id}"),
            (recordings, plan.monthly_recording_limit if plan else None, "recordings (videos)", f"usage_limit:{client.id}:rec"),
        ]
        for used, limit, noun, key in meters:
            warn_key, over_key = f"{key}:warn", f"{key}:over"
            if not limit:
                resolve_alerts(db, dedupe_key=warn_key)
                resolve_alerts(db, dedupe_key=over_key)
                continue
            percent = used / limit * 100
            label = f"{client.name} has used {used:,} of the {limit:,} {noun} in the {plan.name} plan this month ({percent:.0f}%)."
            name = client.name if noun == "events" else f"{client.name} (recordings)"

            if percent >= 100:
                alert, created = raise_alert(db, kind="usage_limit", dedupe_key=over_key, client_id=client.id, severity="critical", message=label + " They are over their limit: time to talk about an upgrade or an extra-usage invoice.")
                resolve_alerts(db, dedupe_key=warn_key)
                result["over"].append(name)
            elif percent >= warn_at:
                alert, created = raise_alert(db, kind="usage_limit", dedupe_key=warn_key, client_id=client.id, severity="warning", message=label)
                resolve_alerts(db, dedupe_key=over_key)
                result["warning"].append(name)
            else:
                resolve_alerts(db, dedupe_key=warn_key)
                resolve_alerts(db, dedupe_key=over_key)
                continue
            if created:
                notify_admins(alert, extra)
    return result
