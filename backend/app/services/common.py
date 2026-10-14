"""Small helpers shared by the service modules."""

import math
from typing import Any


def num(value: Any) -> float:
    """Turn a PostHog number into a float. None or NaN (e.g. the average of no rows) -> 0."""
    if value is None:
        return 0.0
    value = float(value)
    return 0.0 if math.isnan(value) else value


def change_pct(current: float, previous: float) -> float | None:
    """Percent change from the previous period. None when there is nothing to compare to."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def metric(current: Any, previous: Any, digits: int = 0) -> dict[str, Any]:
    """Build {"current", "previous", "change_pct"} for one KPI card."""
    cur, prev = num(current), num(previous)
    if digits == 0:
        cur, prev = int(round(cur)), int(round(prev))
    else:
        cur, prev = round(cur, digits), round(prev, digits)
    return {"current": cur, "previous": prev, "change_pct": change_pct(cur, prev)}


def label(value: Any, empty: str = "(unknown)") -> str:
    """Display text for a breakdown value. Empty or missing values get a readable label."""
    if value is None or value == "":
        return empty
    return str(value)
