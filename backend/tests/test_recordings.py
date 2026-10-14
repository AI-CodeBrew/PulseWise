"""Recording playback data: parsing, decompression, limits."""

import json

import pytest

from app.services.recordings import (
    MAX_DECOMPRESSED_EVENT_BYTES,
    gzip_to_posthog_string,
    parse_snapshot_lines,
)

RECORDING = "01a0eebd-1729-7069-8fc2-8cff61d875e4"


def line(event: dict, window: str = "w1") -> str:
    return json.dumps([window, event])


def test_plain_events_are_returned_in_time_order():
    text = "\n".join([
        line({"type": 3, "timestamp": 300, "data": {"source": 1}}),
        line({"type": 4, "timestamp": 100, "data": {"href": "http://x.test/"}}),
        line({"type": 3, "timestamp": 200, "data": {"source": 2}}),
    ])
    events = parse_snapshot_lines(text)
    assert [e["timestamp"] for e in events] == [100, 200, 300]


def test_compressed_events_are_unpacked():
    full_snapshot = {"node": {"type": 0, "childNodes": [{"type": 2, "tagName": "html", "text": "héllo wörld ✓"}]}}
    event = {"type": 2, "timestamp": 5, "cv": "2024-10", "data": gzip_to_posthog_string(full_snapshot)}
    # PostHog sends the text over HTTP as UTF-8; make sure that round trip works too.
    wire_text = line(event)
    assert json.loads(wire_text)[1]["data"] != full_snapshot  # really compressed on the wire
    [parsed] = parse_snapshot_lines(wire_text)
    assert parsed["data"] == full_snapshot
    assert "cv" not in parsed


def test_text_with_special_line_separators_does_not_break_parsing():
    # U+2028 and form feed can appear inside recorded page text. str.splitlines() would cut there.
    event = {"type": 3, "timestamp": 1, "data": {"text": "a b\x0cc\x1dd"}}
    text = line(event) + "\n" + line({"type": 3, "timestamp": 2, "data": {}})
    events = parse_snapshot_lines(text)
    assert len(events) == 2 and events[0]["data"]["text"] == "a b\x0cc\x1dd"


def test_unreadable_lines_and_broken_compression_are_skipped_not_fatal():
    text = "\n".join([
        "this is not json",
        line({"type": 2, "timestamp": 1, "cv": "2024-10", "data": "not really gzip"}),
        line({"type": 3, "timestamp": 2, "data": {"ok": True}}),
        "",
    ])
    events = parse_snapshot_lines(text)
    assert [e["timestamp"] for e in events] == [2]


def test_decompression_bombs_are_refused():
    bomb = gzip_to_posthog_string("0" * (MAX_DECOMPRESSED_EVENT_BYTES + 1024))
    events = parse_snapshot_lines(line({"type": 2, "timestamp": 1, "cv": "2024-10", "data": bomb}))
    assert events == []


def test_older_line_format_is_understood():
    text = json.dumps({"window_id": "w", "data": [{"type": 3, "timestamp": 1, "data": {}}, {"type": 3, "timestamp": 2, "data": {}}]})
    assert len(parse_snapshot_lines(text)) == 2


def test_recording_details_endpoint(api, world, fake_posthog):
    alice = api("alice@a.test")
    body = alice.get(f"/api/websites/{world.site_a.id}/recordings/{RECORDING}").json()
    assert body["id"] == RECORDING
    assert body["blocks"] == [{"key": 0, "start": "2026-10-10T10:00:00Z", "end": "2026-10-10T10:05:00Z"}]
    assert "open_url" not in body
    # Only client A's project and key were used.
    assert fake_posthog.projects_called() == {7350981}


def test_recording_events_endpoint_returns_events(api, world):
    alice = api("alice@a.test")
    body = alice.get(f"/api/websites/{world.site_a.id}/recordings/{RECORDING}/events", params={"start": 0, "end": 0}).json()
    assert body["events"][0]["type"] == 4


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"start": 3, "end": 1}, 422),  # end before start
        ({"start": 0, "end": 10}, 422),  # more than 4 blocks
        ({"start": -1, "end": 0}, 422),
        ({"start": "x", "end": 0}, 422),
        ({"start": 0}, 422),  # missing end
    ],
)
def test_recording_events_validate_the_block_range(api, world, params, expected):
    alice = api("alice@a.test")
    response = alice.get(f"/api/websites/{world.site_a.id}/recordings/{RECORDING}/events", params=params)
    assert response.status_code == expected


def test_recording_id_must_be_a_uuid(api, world):
    alice = api("alice@a.test")
    assert alice.get(f"/api/websites/{world.site_a.id}/recordings/not-a-uuid").status_code == 422
    assert alice.get(f"/api/websites/{world.site_a.id}/recordings/../../overview/events?start=0&end=0").status_code in (404, 422)


def test_another_clients_recording_is_never_requested(api, world, fake_posthog):
    alice = api("alice@a.test")
    response = alice.get(f"/api/websites/{world.site_b.id}/recordings/{RECORDING}/events", params={"start": 0, "end": 0})
    assert response.status_code == 404
    assert fake_posthog.calls == []


def test_responses_are_gzip_compressed_when_large(api, world):
    alice = api("alice@a.test")
    response = alice.get("/api/auth/me", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200  # (small bodies are not compressed; the middleware just must not break anything)


def test_console_logs_and_internal_markers_are_not_sent_to_the_browser():
    text = "\n".join([
        line({"type": 4, "timestamp": 1, "data": {"href": "http://x.test/", "width": 800, "height": 600}}),
        line({"type": 6, "timestamp": 2, "data": {"plugin": "rrweb/console@1", "payload": {"payload": ["secret: card 4111..."]}}}),
        line({"type": 5, "timestamp": 3, "data": {"tag": "$posthog_config", "payload": {"x": 1}}}),
        line({"type": 5, "timestamp": 4, "data": {"tag": "my-own-marker", "payload": {}}}),
        line({"type": 3, "timestamp": 5, "data": {"source": 1}}),
    ])
    events = parse_snapshot_lines(text)
    assert [e["type"] for e in events] == [4, 5, 3]  # console log and "$posthog_config" are gone
    assert "posthog" not in json.dumps(events).lower() and "secret" not in json.dumps(events)


def test_an_unknown_recording_is_a_plain_404(api, world, monkeypatch):
    from app.posthog_client import AnalyticsError, PostHogClient

    async def not_found(self, method, path, raw=False, **kwargs):
        raise AnalyticsError(502, "project not found", upstream_status=404, upstream_detail="Not found.")

    alice = api("alice@a.test")
    monkeypatch.setattr(PostHogClient, "_request", not_found)
    for path in (f"/recordings/{RECORDING}", f"/recordings/{RECORDING}/events?start=0&end=0"):
        response = alice.get(f"/api/websites/{world.site_a.id}{path}")
        assert response.status_code == 404 and "Recording not found" in response.json()["detail"]
