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
