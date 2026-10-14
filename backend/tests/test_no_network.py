"""The test suite itself must never reach the internet."""

import asyncio

import httpx
import pytest

from app import posthog_client
from app.config import WebsiteConfig
from app.posthog_client import PostHogClient

REAL_REQUEST = PostHogClient._request


def test_a_real_request_in_a_test_fails_loudly(monkeypatch):
    monkeypatch.setattr(PostHogClient, "_request", REAL_REQUEST)

    async def go():
        await posthog_client.startup()
        ph = PostHogClient(WebsiteConfig("w", "w", "https://us.posthog.com", 1, "phx_x"))
        await ph.hogql("SELECT 1")

    with pytest.raises((AssertionError, httpx.HTTPError)) as caught:
        asyncio.run(go())
    assert "real network" in str(caught.value) or isinstance(caught.value, httpx.HTTPError)
