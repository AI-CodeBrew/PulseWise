"""
The ONLY module that talks to PostHog.

Everything else asks this module for data. That keeps three things in one place:
  1. URLs and auth headers  (per website, from WebsiteConfig)
  2. Caching                (5 minutes by default; the key includes the website id)
  3. Error handling         (PostHog errors -> friendly, white-label messages)

If we later read from our own Postgres copy of the events (PostHog batch exports)
instead of live PostHog, this is the module to replace.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.cache import cache, make_key
from app.config import WebsiteConfig, settings

log = logging.getLogger(__name__)

# PostHog runs at most 3 queries at once per project. Extra queries would be queued
# or rejected by PostHog, so we queue them ourselves: one semaphore per project.
# (Keyed by host + project id: US and EU cloud project ids could clash.)
MAX_CONCURRENT_QUERIES = 3
_semaphores: dict[tuple[str, int], asyncio.Semaphore] = {}

# Temporary PostHog overload errors worth retrying (3 tries in total).
RETRYABLE_STATUSES = {502, 503, 504}
RETRY_ATTEMPTS = 3

# Functions called (with the website, PostHog's status code and message) whenever a request fails for good.
# The app registers app.alerts.record_posthog_error here at startup, which opens an admin alert.
error_listeners: list[Callable[[WebsiteConfig, int | None, str | None], Awaitable[None]]] = []

# One shared HTTP client for the whole app (it reuses connections, so it is faster).
# It is created when the app starts and closed when it stops (see main.py).
_http: httpx.AsyncClient | None = None


async def startup() -> None:
    global _http
    # PostHog may queue a query for up to 30s and run it for up to 10s, so allow 60s.
    _http = httpx.AsyncClient(timeout=60)


async def shutdown() -> None:
    if _http is not None:
        await _http.aclose()


class AnalyticsError(Exception):
    """Something went wrong while fetching analytics data.

    `message` is safe to show to a client: it never mentions PostHog (white-label)
    and never contains the API key. The technical details go to the server log.
    """

    def __init__(self, status_code: int, message: str, upstream_status: int | None = None, upstream_detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        # The REAL reason, for admins and the alerts log. NEVER send these to a client.
        self.upstream_status = upstream_status
        self.upstream_detail = upstream_detail


class PostHogClient:
    """Reads data for ONE website. Create one per request with that website's config."""

    def __init__(self, website: WebsiteConfig):
        self.website = website

    async def hogql(
        self,
        query: str,
        values: dict[str, Any] | None = None,
        *,
        name: str = "portal",
        ttl: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run a HogQL (SQL) query and return the rows as a list of dicts.

        SAFETY: user input must ONLY go into `values`, never into the `query` text.
        In the query, write {name} and PostHog substitutes the value as a typed
        constant. A value like "' OR 1=1 --" stays a harmless string. (We tested this.)

        `name` labels the query in PostHog's query log, which helps with debugging.
        """
        values = values or {}
        key = make_key(self.website.website_id, "hogql", query, values)
        cached = cache.get(key)
        if cached is not None:
            return cached

        body = {
            "query": {"kind": "HogQLQuery", "query": query, "values": values},
            "name": name,
        }
        data = await self._request(
            "POST", f"/api/projects/{self.website.project_id}/query/", json=body
        )

        # PostHog returns {"columns": ["a", "b"], "results": [[1, 2], [3, 4]]}.
        # Turn that into [{"a": 1, "b": 2}, {"a": 3, "b": 4}], which is easier to use.
        columns = data.get("columns") or []
        rows = [dict(zip(columns, row)) for row in data.get("results") or []]

        cache.set(key, rows, ttl if ttl is not None else settings.cache_ttl_seconds)
        return rows

    async def rest_get(
        self, path: str, params: dict[str, Any] | None = None, *, ttl: int | None = None, quiet_404: bool = False
    ) -> dict[str, Any]:
        """GET one of PostHog's regular REST endpoints (e.g. session recordings).

        `path` is relative to the project, e.g. "session_recordings/".
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = make_key(self.website.website_id, "rest", path, params)
        cached = cache.get(key)
        if cached is not None:
            return cached

        data = await self._request(
            "GET", f"/api/projects/{self.website.project_id}/{path}", params=params, quiet_404=quiet_404
        )
        cache.set(key, data, ttl if ttl is not None else settings.cache_ttl_seconds)
        return data

    async def rest_get_text(self, path: str, params: dict[str, Any] | None = None, *, quiet_404: bool = False) -> str:
        """GET a REST endpoint that answers with plain text (e.g. JSON Lines), NOT cached.

        Used for session-recording snapshot blocks: big, immutable, and not worth holding in memory.
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        return await self._request(
            "GET", f"/api/projects/{self.website.project_id}/{path}", params=params, raw=True, quiet_404=quiet_404
        )

    # ------------------------------------------------------------------ internals

    async def _request(self, method: str, path: str, raw: bool = False, quiet_404: bool = False, **kwargs: Any) -> Any:
        """Send the request. If it fails for good, tell the listeners (they raise an admin alert), then re-raise.

        `quiet_404`: a 404 is an expected answer (e.g. "that recording doesn't exist"), not a broken connection.
        """
        try:
            return await self._send(method, path, raw=raw, **kwargs)
        except AnalyticsError as exc:
            if not (quiet_404 and exc.upstream_status == 404):
                for listener in error_listeners:
                    await listener(self.website, exc.upstream_status, exc.upstream_detail)
            raise

    async def _send(self, method: str, path: str, raw: bool = False, **kwargs: Any) -> Any:
        if _http is None:
            raise RuntimeError("HTTP client not started (posthog_client.startup())")

        project_key = (self.website.posthog_host, self.website.project_id)
        semaphore = _semaphores.get(project_key)
        if semaphore is None:
            semaphore = _semaphores[project_key] = asyncio.Semaphore(MAX_CONCURRENT_QUERIES)

        url = f"{self.website.posthog_host}{path}"
        headers = {"Authorization": f"Bearer {self.website.api_key}"}

        # PostHog sometimes answers 502/503/504 ("queries are a little too busy right
        # now"). That is temporary, so wait a moment and try again before giving up.
        # The wait happens OUTSIDE the semaphore so other queries can use the slot.
        response = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                async with semaphore:
                    response = await _http.request(method, url, headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                log.warning("PostHog timeout website=%s path=%s", self.website.website_id, path)
                raise AnalyticsError(
                    504, "The analytics service took too long to answer. Please try again.", upstream_detail="timeout"
                ) from exc
            except httpx.HTTPError as exc:
                log.warning(
                    "PostHog unreachable website=%s path=%s error=%r",
                    self.website.website_id, path, exc,
                )
                raise AnalyticsError(
                    503, "Could not reach the analytics service. Please try again shortly.", upstream_detail=f"unreachable: {exc!r}"[:300]
                ) from exc

            if response.status_code not in RETRYABLE_STATUSES or attempt == RETRY_ATTEMPTS - 1:
                break
            delay = 1.5 * (attempt + 1)  # 1.5s, then 3s
            log.info(
                "PostHog busy (status %s), retrying in %.1fs (attempt %d/%d)",
                response.status_code, delay, attempt + 1, RETRY_ATTEMPTS,
            )
            await asyncio.sleep(delay)

        if response.status_code >= 400:
            raise self._translate_error(response, path)
        return response.text if raw else response.json()

    def _translate_error(self, response: httpx.Response, path: str) -> AnalyticsError:
        error = self._friendly_error(response, path)
        try:
            error.upstream_detail = str(response.json().get("detail", ""))[:300]
        except ValueError:
            error.upstream_detail = response.text[:300]
        error.upstream_status = response.status_code
        return error

    def _friendly_error(self, response: httpx.Response, path: str) -> AnalyticsError:
        """Log the real PostHog error, and return a safe, friendly one."""
        try:
            detail = response.json().get("detail", "")
        except ValueError:
            detail = response.text[:300]
        status = response.status_code

        # Full details for us, in the server log. (Phase 6: also save to an alerts table.)
        log.warning(
            "PostHog error website=%s status=%s path=%s detail=%s",
            self.website.website_id, status, path, str(detail)[:500],
        )

        if status in (401, 403):
            return AnalyticsError(
                502, "The analytics connection for this website is not authorized. "
                "Please contact support."
            )
        if status == 404:
            return AnalyticsError(
                502, "The analytics project for this website was not found. "
                "Please contact support."
            )
        if status == 503:
            return AnalyticsError(
                503, "The analytics service is busy right now. Please try again in a moment."
            )
        if status == 429:
            retry = response.headers.get("Retry-After")
            wait = f" in {retry} seconds" if retry else " in a minute"
            return AnalyticsError(503, f"Too many requests right now. Please try again{wait}.")
        if status == 400:
            # A 400 means our own query is wrong, so this is a bug on our side.
            return AnalyticsError(500, "This report could not be loaded (query error).")
        return AnalyticsError(502, "The analytics service returned an error. Please try again.")
