"""
Estimating what PostHog charges US for the traffic our clients' websites generate.

Tiers copied from posthog.com/pricing on 2026-10-14. PostHog can change them: this is an ESTIMATE
(it ignores add-ons like "identified events", and credits). The monthly free allowance is shared by
the whole PostHog organization, i.e. by all our clients together.
"""

import math

# (upper limit of the tier, price per unit in USD): "first 1,000,000 are free, the next 1,000,000 cost 0.00005 each..."
EVENT_TIERS: list[tuple[float, float]] = [
    (1_000_000, 0.0),
    (2_000_000, 0.00005),
    (15_000_000, 0.0000343),
    (50_000_000, 0.0000295),
    (100_000_000, 0.0000218),
    (250_000_000, 0.000015),
    (math.inf, 0.000009),
]

RECORDING_TIERS: list[tuple[float, float]] = [
    (5_000, 0.0),
    (15_000, 0.005),
    (50_000, 0.0035),
    (150_000, 0.002),
    (500_000, 0.0017),
    (math.inf, 0.0015),
]

FREE_EVENTS = EVENT_TIERS[0][0]
FREE_RECORDINGS = RECORDING_TIERS[0][0]


def tiered_cost(volume: float, tiers: list[tuple[float, float]]) -> float:
    """Cost in USD of `volume` units, with prices that drop as the volume grows."""
    cost = 0.0
    lower = 0.0
    for upper, price in tiers:
        if volume <= lower:
            break
        cost += (min(volume, upper) - lower) * price
        lower = upper
    return cost


def event_cost(events: float) -> float:
    return tiered_cost(events, EVENT_TIERS)


def recording_cost(recordings: float) -> float:
    return tiered_cost(recordings, RECORDING_TIERS)


# ------------------------------------------------------------------ what WE charge: the provider's price plus a commission


def with_commission(cost_usd: float, commission_percent: float) -> float:
    """The provider's price plus our commission, e.g. $50 with a 30% commission is $65."""
    return cost_usd * (1 + commission_percent / 100)


def suggest_price(events: float, recordings: float, *, base_usd: float, commission_percent: float, usd_to_pkr: float) -> dict[str, float]:
    """What a plan that includes this many events and recordings per month should cost.

        price = base price + (what the provider charges ABOVE its free allowance) x (1 + commission)

    The base price covers the free part (1,000,000 events and 5,000 recordings), so a plan that stays inside
    the free allowance costs just the base price. The price is rounded UP to a whole dollar (and to the next 100 rupees).
    """
    events_usd = event_cost(events)
    recordings_usd = recording_cost(recordings)
    provider_usd = events_usd + recordings_usd
    extra_usd = with_commission(provider_usd, commission_percent)
    suggested_usd = math.ceil(round(base_usd + extra_usd, 4))
    return {
        "events": events, "recordings": recordings,
        "provider_events_usd": round(events_usd, 2), "provider_recordings_usd": round(recordings_usd, 2), "provider_usd": round(provider_usd, 2),
        "commission_percent": commission_percent, "commission_usd": round(extra_usd - provider_usd, 2),
        "base_usd": base_usd, "suggested_usd": suggested_usd,
        "suggested_pkr": math.ceil(round(suggested_usd * usd_to_pkr, 2) / 100) * 100, "usd_to_pkr": usd_to_pkr,
    }


def overage_cost(used: float, included: float | None, tiers: list[tuple[float, float]]) -> float:
    """The provider's price (USD) for the part of `used` that is above what the plan includes.

    Priced as if this client were the only one, from where the plan ends: the extra units cost
    `cost(used) - cost(included)`, so a plan that includes the free allowance pays from the first paid tier on.
    """
    if included is None or used <= included:
        return 0.0
    return tiered_cost(used, tiers) - tiered_cost(included, tiers)
