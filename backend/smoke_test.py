"""
Live smoke test: logs in to the RUNNING API and calls every analytics endpoint.

(The automated tests in tests/ use a fake PostHog. This one talks to the real thing,
so it shows whether your real setup works end to end.)

1. Start the API in one terminal:   uvicorn app.main:app --reload
2. Run this in another terminal:    python smoke_test.py

It asks for the email and password of a dashboard user (it never saves them).
For scripts, set SMOKE_EMAIL and SMOKE_PASSWORD instead. To test one specific website,
set SMOKE_WEBSITE_ID (default: the first website that user can see).
"""

import getpass
import os
import sys
import time

import httpx

BASE = os.getenv("API_URL", "http://localhost:8000")
client = httpx.Client(base_url=BASE, timeout=90)  # keeps the login cookie between calls
failures = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global failures
    if not ok:
        failures += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {extra}")


def expect_ok(path: str, keys: list[str], **params) -> dict:
    """GET must return 200 and contain the given top-level keys."""
    started = time.perf_counter()
    r = client.get(path, params=params)
    took = time.perf_counter() - started
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok = r.status_code == 200 and all(k in body for k in keys)
    check(f"GET {path.split('/', 4)[-1]} {params or ''}", ok, f"-> {r.status_code} in {took:.2f}s" + ("" if ok else f" {r.text[:200]}"))
    return body


def main() -> None:
    email = os.getenv("SMOKE_EMAIL") or input("Dashboard email: ")
    password = os.getenv("SMOKE_PASSWORD") or getpass.getpass("Password (hidden): ")

    # --- Login
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    check("login", r.status_code == 200, f"-> {r.status_code} {'' if r.status_code == 200 else r.text[:150]}")
    if r.status_code != 200:
        sys.exit(1)
    websites = r.json()["websites"]
    check("user can see at least one website", len(websites) > 0)
    if not websites:
        sys.exit(1)
    site_id = os.getenv("SMOKE_WEBSITE_ID") or websites[0]["id"]
    site = f"/api/websites/{site_id}"
    print(f"\nTesting website: {next((w['name'] for w in websites if w['id'] == site_id), site_id)}\n")

    # --- Every analytics endpoint
    for days in (7, 30, 90):
        expect_ok(f"{site}/overview", ["pageviews", "visitors", "sessions", "avg_session_duration", "bounce_rate"], days=days)
    trends = expect_ok(f"{site}/trends", ["series"], days=7)
    check("trends has exactly 7 daily points", len(trends.get("series", [])) == 7)
    expect_ok(f"{site}/top-pages", ["results"])
    expect_ok(f"{site}/sources", ["referrers", "utm_sources", "channels"])
    expect_ok(f"{site}/geo", ["countries", "cities"])
    expect_ok(f"{site}/devices", ["device_types", "browsers", "operating_systems"])
    expect_ok(f"{site}/events/live", ["results"])
    expect_ok(f"{site}/events/custom", ["results"])
    expect_ok(f"{site}/recordings", ["results", "next_cursor"], limit=3)

    page1 = expect_ok(f"{site}/sessions", ["results", "next_cursor"], limit=3)
    if page1.get("next_cursor"):
        page2 = expect_ok(f"{site}/sessions", ["results"], limit=3, cursor=page1["next_cursor"])
        ids1 = {s["session_id"] for s in page1["results"]}
        ids2 = {s["session_id"] for s in page2.get("results", [])}
        check("sessions page 2 has no overlap with page 1", not (ids1 & ids2))
    if page1.get("results"):
        detail = expect_ok(f"{site}/sessions/{page1['results'][0]['session_id']}", ["session", "events"])
        times = [e["timestamp"] for e in detail.get("events", [])]
        check("session events are in time order", times == sorted(times), f"({len(times)} events)")

    people = expect_ok(f"{site}/persons", ["results", "next_cursor"], limit=3)
    if people.get("results"):
        expect_ok(f"{site}/persons/{people['results'][0]['id']}", ["id", "properties", "events"])

    # --- Bad input must be rejected
    for label, path, params in [
        ("days=5 rejected", f"{site}/overview", {"days": 5}),
        ("days SQL injection rejected", f"{site}/overview", {"days": "30; DROP TABLE events"}),
        ("limit=1000 rejected", f"{site}/sessions", {"limit": 1000}),
        ("garbage cursor rejected", f"{site}/sessions", {"cursor": "AAAA"}),
        ("bad session id rejected", f"{site}/sessions/not-a-uuid", {}),
        ("bad website id rejected", "/api/websites/1/overview", {}),
    ]:
        r = client.get(path, params=params)
        check(label, r.status_code == 422, f"-> {r.status_code}")
    r = client.get(f"/api/websites/00000000-0000-0000-0000-000000000000/overview")
    check("unknown website -> 404", r.status_code == 404, f"-> {r.status_code}")
    r = client.get(f"{site}/sessions/00000000-0000-0000-0000-000000000000")
    check("unknown session -> 404", r.status_code == 404, f"-> {r.status_code}")

    # --- Cache: the second identical call should be (much) faster.
    # (Every request still checks your login and website access in the database, which costs
    # roughly 100-300 ms with a remote database. The PostHog part itself is served from memory.)
    t0 = time.perf_counter()
    client.get(f"{site}/geo", params={"days": 90})
    first = time.perf_counter() - t0
    t0 = time.perf_counter()
    client.get(f"{site}/geo", params={"days": 90})
    cached = time.perf_counter() - t0
    check("repeat call is served from the cache (<0.8s)", cached < 0.8, f"({cached * 1000:.0f} ms; first call {first * 1000:.0f} ms)")

    # --- Logout really ends the session
    client.post("/api/auth/logout")
    r = client.get(f"{site}/overview")
    check("after logout, data is refused (401)", r.status_code == 401, f"-> {r.status_code}")

    print()
    print("ALL PASSED" if failures == 0 else f"{failures} CHECK(S) FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
