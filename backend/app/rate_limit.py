"""
A small in-memory rate limiter, used to slow down password guessing.

Limitation: the counts live in this process's memory. They reset when the server
restarts, and two server processes would count separately. That's fine for one
server. With several servers, move the counts to Redis (see docs/ROADMAP.md).
"""

import threading
import time
from collections import deque

_MAX_KEYS = 10_000  # safety cap so the dict can't grow forever


class RateLimiter:
    """Allows at most `max_hits` hits per key within a sliding window of `window_seconds`."""

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()  # sync endpoints run in several threads at once

    def retry_after(self, key: str) -> int | None:
        """Seconds until `key` may try again, or None if it is not blocked."""
        with self._lock:
            now = time.monotonic()
            hits = self._prune(key, now)
            if len(hits) >= self.max_hits:
                return int(hits[0] + self.window_seconds - now) + 1
            return None

    def hit(self, key: str) -> None:
        with self._lock:
            if len(self._hits) >= _MAX_KEYS:
                self._prune_all(time.monotonic())
            self._hits.setdefault(key, deque()).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def _prune_all(self, now: float) -> None:
        for key in list(self._hits):
            self._prune(key, now)


# Wrong passwords: 5 per (IP + email) and 30 per IP, within 15 minutes.
login_failures_by_account = RateLimiter(max_hits=5, window_seconds=15 * 60)
login_failures_by_ip = RateLimiter(max_hits=30, window_seconds=15 * 60)

# "Forgot password" emails: 5 per IP per hour.
reset_requests_by_ip = RateLimiter(max_hits=5, window_seconds=60 * 60)


def all_limiters() -> list[RateLimiter]:
    return [login_failures_by_account, login_failures_by_ip, reset_requests_by_ip]
