"""Session recordings: a list, and everything needed to PLAY one inside our own dashboard.

Recordings are not in HogQL. They come from PostHog's REST endpoints:
    GET session_recordings/                      the list (pages with a `next_cursor`)
    GET session_recordings/{id}                  one recording's details
    GET session_recordings/{id}/snapshots        the list of data blocks ("sources")
    GET session_recordings/{id}/snapshots?source=blob_v2&start_blob_key=A&end_blob_key=B
                                                 the blocks A..B as JSON Lines: one `[window_id, event]` per line

The events are in the standard "rrweb" format (a recording of the page's DOM), which the
browser replays with the `rrweb-player` library. All of this passes through OUR backend,
so clients never need a PostHog login and never see PostHog.
"""

import asyncio
import gzip
import json
import logging
import zlib
from typing import Any

from fastapi import HTTPException

from app.posthog_client import AnalyticsError, PostHogClient
from app.services.persons import display_name

log = logging.getLogger(__name__)

# How many blocks one request may ask for (blocks are ~0.3-1 MB each).
MAX_BLOCKS_PER_REQUEST = 4
# A single decompressed event may not be larger than this (protects against "zip bombs").
MAX_DECOMPRESSED_EVENT_BYTES = 64 * 1024 * 1024


def _person_label(person: dict | None, distinct_id: str | None) -> str:
    """Best label for who was recorded. `person` shape differs between PostHog versions."""
    person = person or {}
    props = person.get("properties") or {}
    ids = person.get("distinct_ids") or []
    first_id = ids[0] if ids and isinstance(ids[0], str) else None
    return display_name(
        props.get("email"), props.get("name") or person.get("name"), distinct_id or first_id
    )


def _shape(r: dict) -> dict:
    return {
        "id": r["id"],
        "person": _person_label(r.get("person"), r.get("distinct_id")),
        "start_time": r["start_time"],
        "end_time": r.get("end_time"),
        "duration": r.get("recording_duration", 0),  # seconds
        "active_seconds": r.get("active_seconds", 0),
        "clicks": r.get("click_count", 0),
        "start_url": r.get("start_url"),
    }


async def list_recordings(ph: PostHogClient, days: int, limit: int, cursor: str | None) -> dict:
    data = await ph.rest_get(
        "session_recordings/",
        {"limit": limit, "date_from": f"-{days}d", "after": cursor},
    )
    return {
        "days": days,
        "results": [_shape(r) for r in data.get("results", [])],
        "next_cursor": data.get("next_cursor") if data.get("has_next") else None,
    }


def _recording_not_found(exc: AnalyticsError) -> Exception:
    """PostHog answers 404 for a recording that doesn't exist (or has expired): tell the user that,
    instead of the generic "project not found" message. Any other error is passed on unchanged."""
    if exc.upstream_status == 404:
        return HTTPException(status_code=404, detail="Recording not found (it may have expired).")
    return exc


async def get_recording(ph: PostHogClient, recording_id: str) -> dict:
    """Details + the list of blocks the player has to load."""
    try:
        details, snapshots = await asyncio.gather(  # two independent questions: ask at the same time
            ph.rest_get(f"session_recordings/{recording_id}/", quiet_404=True),
            ph.rest_get(f"session_recordings/{recording_id}/snapshots", quiet_404=True),
        )
    except AnalyticsError as exc:
        raise _recording_not_found(exc) from exc
    sources = [s for s in snapshots.get("sources", []) if s.get("source") == "blob_v2"]
    if not details.get("id") and not sources:
        raise HTTPException(status_code=404, detail="Recording not found")
    return {
        **_shape({"id": recording_id, **details}),
        "blocks": [
            {"key": int(s["blob_key"]), "start": s.get("start_timestamp"), "end": s.get("end_timestamp")}
            for s in sources
        ],
    }


async def get_recording_events(ph: PostHogClient, recording_id: str, start: int, end: int) -> dict:
    if end < start:
        raise HTTPException(status_code=422, detail="end must not be smaller than start")
    if end - start + 1 > MAX_BLOCKS_PER_REQUEST:
        raise HTTPException(status_code=422, detail=f"Ask for at most {MAX_BLOCKS_PER_REQUEST} blocks at a time")
    try:
        text = await ph.rest_get_text(
            f"session_recordings/{recording_id}/snapshots",
            {"source": "blob_v2", "start_blob_key": start, "end_blob_key": end},
            quiet_404=True,
        )
    except AnalyticsError as exc:
        raise _recording_not_found(exc) from exc
    events = parse_snapshot_lines(text)
    return {"start": start, "end": end, "events": events}


# ---------------------------------------------------------------- parsing


def parse_snapshot_lines(text: str) -> list[dict[str, Any]]:
    """JSON Lines from PostHog -> a list of plain rrweb events (decompressed, in time order)."""
    events: list[dict[str, Any]] = []
    # Split ONLY on "\n". str.splitlines() would also cut at U+2028, form feeds and other
    # characters that can legitimately appear inside the recorded page's text.
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            log.warning("Skipping an unreadable recording line (%d chars)", len(line))
            continue
        # Normal format: [window_id, event]. Older format: {"window_id": ..., "data": [events]}.
        candidates: list[Any] = []
        if isinstance(parsed, list) and len(parsed) == 2 and isinstance(parsed[1], dict):
            candidates = [parsed[1]]
        elif isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
            candidates = [e for e in parsed["data"] if isinstance(e, dict)]
        elif isinstance(parsed, dict) and "type" in parsed:
            candidates = [parsed]
        for event in candidates:
            if _is_not_for_playback(event):
                continue
            normalized = _decompress_event(event)
            if normalized is not None:
                events.append(normalized)
    events.sort(key=lambda e: e.get("timestamp", 0))  # stable, so equal timestamps keep their order
    return events


def _is_not_for_playback(event: dict[str, Any]) -> bool:
    """Events the replay doesn't need, which we don't want to send to the browser:

    - type 6 = "plugin" events, notably the page's console log output. Not needed to replay, can contain
      private data, and shrinks the download a lot when dropped.
    - type 5 = custom events whose tag starts with "$": the recorder's own internal markers
      (e.g. its configuration). The player would show them on the timeline with PostHog's names.
    """
    kind = event.get("type")
    if kind == 6:
        return True
    if kind == 5:
        data = event.get("data")
        tag = data.get("tag") if isinstance(data, dict) else None
        return isinstance(tag, str) and tag.startswith("$")
    return False


# The parts of a "page changed" (mutation) event that posthog-js compresses one by one.
MUTATION_FIELDS = ("adds", "removes", "texts", "attributes")


class _TooBig(Exception):
    """A piece of a recording decompresses to more than we allow."""


def _gunzip_json(packed: str) -> Any:
    """One compressed piece: string (one character per byte, latin-1) -> bytes -> gunzip -> UTF-8 JSON."""
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)  # 16+ = gzip header
    unpacked = decompressor.decompress(packed.encode("latin-1"), MAX_DECOMPRESSED_EVENT_BYTES)
    if decompressor.unconsumed_tail:  # more data than allowed
        raise _TooBig
    return json.loads(unpacked.decode("utf-8"))


def _decompress_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """posthog-js gzips large event data and marks it with `cv` ("compression version"). Two shapes exist:

    1. the WHOLE `data` is one compressed string (the page snapshot and most other events);
    2. for "page changed" (mutation) events, `data` stays an object but its `adds`, `removes`, `texts` and
       `attributes` are compressed separately. (Missing this second shape was a real bug: everything that
       appeared on the page AFTER the first snapshot, such as a store's product grid, never showed in our replay.)

    We unpack both here, so the browser's player gets ordinary rrweb events.
    """
    data = event.get("data")
    if "cv" not in event:
        return event
    try:
        new_event = {k: v for k, v in event.items() if k not in ("cv", "data")}
        if isinstance(data, str):
            new_event["data"] = _gunzip_json(data)
        elif isinstance(data, dict):
            new_event["data"] = {k: (_gunzip_json(v) if k in MUTATION_FIELDS and isinstance(v, str) else v) for k, v in data.items()}
        else:
            return event
        return new_event
    except _TooBig:
        log.warning("Skipping a recording event that decompresses to more than the limit")
        return None
    except (UnicodeError, zlib.error, ValueError):
        log.warning("Skipping a recording event that could not be decompressed")
        return None


def gzip_to_posthog_string(obj: Any) -> str:
    """The reverse of the above (used by tests to build realistic compressed events)."""
    return gzip.compress(json.dumps(obj).encode("utf-8")).decode("latin-1")
