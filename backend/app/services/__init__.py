"""
Services = the "business logic" layer.

Each function takes a PostHogClient (already bound to one website) plus validated
parameters, runs HogQL, and returns plain dicts and lists ready to send as JSON.

Routers (the HTTP layer) stay thin and only call these. Later, background jobs
(weekly reports, AI summaries, usage sync) can call the same functions directly.

Date ranges: "last N days" always means today plus the N-1 days before it, in the
PostHog project's timezone. In HogQL that is:
    timestamp >= toStartOfDay(now()) - toIntervalDay({days} - 1)
"""
