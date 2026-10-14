"""
Admin-only PostHog helpers: validate a connection before saving it, and read project info.

Unlike the client-facing error messages (which never mention PostHog), these messages are for
YOU, the admin, so they say exactly what is wrong and how to fix it.
"""

import uuid
from typing import Any

from app.config import WebsiteConfig, settings
from app.posthog_client import AnalyticsError, PostHogClient

# What each PostHog error means for someone setting up a connection.
HINTS = {
    401: "PostHog did not accept the API key. Check that it is a Personal API key (starts with phx_), "
    "is typed correctly, and belongs to the same region as the host.",
    403: "The key is valid but not allowed to do this. It needs the 'Query: Read' scope (plus 'Session recording: Read' "
    "and 'Person: Read') and access to this project.",
    404: "PostHog doesn't know this project id on that host. Check the project id and the region (US vs EU).",
}


class InvalidPostHogHost(ValueError):
    """The host is not one we are willing to send API keys to."""


def validate_host(host: str) -> str:
    """Normalise a PostHog host and make sure it is on the allowlist.

    API keys are sent to this address, so it must not be arbitrary: a typo or a malicious value
    would leak the key (or let a request reach internal addresses). Self-hosted PostHog?
    Add its address to POSTHOG_ALLOWED_HOSTS in backend/.env.
    """
    cleaned = host.strip().rstrip("/")
    if cleaned not in settings.posthog_allowed_hosts:
        allowed = ", ".join(settings.posthog_allowed_hosts)
        raise InvalidPostHogHost(
            f"'{cleaned}' is not an allowed PostHog address. Allowed: {allowed}. "
            "(Self-hosted? Add it to POSTHOG_ALLOWED_HOSTS in backend/.env.)"
        )
    return cleaned


async def check_connection(host: str, project_id: int, api_key: str) -> dict[str, Any]:
    """Try a tiny query with these details. Never raises: returns {"ok": bool, "message": str, ...}."""
    probe = PostHogClient(
        WebsiteConfig(
            website_id=f"connection-check-{uuid.uuid4()}",  # unique, so nothing is shared through the cache
            name="connection check",
            posthog_host=host,
            project_id=project_id,
            api_key=api_key,
        )
    )
    try:
        await probe.hogql("SELECT 1", ttl=0, name="portal: connection check")
    except AnalyticsError as exc:
        reason = HINTS.get(exc.upstream_status or 0)
        detail = f" (PostHog said: {exc.upstream_detail})" if exc.upstream_detail else ""
        return {"ok": False, "message": (reason or "PostHog could not run the test query.") + detail, "upstream_status": exc.upstream_status}

    info: dict[str, Any] = {"ok": True, "message": "Connected.", "project_token": None, "project_name": None, "timezone": None}
    try:
        # Needs the "Project: Read" scope. Optional: it just saves the admin from typing the public token.
        project = await probe.rest_get("", ttl=0)
        info["project_token"] = project.get("api_token")
        info["project_name"] = project.get("name")
        info["timezone"] = project.get("timezone")
    except AnalyticsError:
        pass
    return info
