"""
A tiny in-memory cache with expiry times ("TTL" = time to live).

Why: every PostHog query costs us money and counts against PostHog's rate limits.
If two people open the same dashboard within 5 minutes, the second one is served
from memory.

Later (see docs/ROADMAP.md) this can be swapped for Redis. Keep the same two methods,
get() and set(), and nothing else in the app has to change.
"""

import hashlib
import json
import time
from typing import Any


def make_key(*parts: Any) -> str:
    """Turn any JSON-able parts (website id, query text, values...) into a short key.

    The website id is always one of the parts, so two websites can never share
    a cached result.
    """
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


class TTLCache:
    def __init__(self, max_items: int = 2000):
        self.max_items = max_items
        self._store: dict[str, tuple[float, Any]] = {}  # key -> (expires_at, value)

    def get(self, key: str) -> Any | None:
        """Return the cached value, or None if missing or expired."""
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if len(self._store) >= self.max_items:
            self._evict()
        self._store[key] = (time.monotonic() + ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()

    def _evict(self) -> None:
        """Make room: drop expired items, and if still full, the oldest-expiring ones."""
        now = time.monotonic()
        for key in [k for k, (exp, _) in self._store.items() if exp < now]:
            del self._store[key]
        if len(self._store) >= self.max_items:
            by_expiry = sorted(self._store, key=lambda k: self._store[k][0])
            for key in by_expiry[: len(by_expiry) // 4]:
                del self._store[key]


# One shared cache for the whole app.
cache = TTLCache()
