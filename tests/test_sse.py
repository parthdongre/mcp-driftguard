import json
from datetime import UTC, datetime

from driftguard.sse import encode_sse_comment, encode_sse_event
from driftguard.timeline import TimelineEvent, TimelineEventKind


def test_sse_event_preserves_cursor_kind_and_json_payload():
    event = TimelineEvent(
        event_id="revision:abc123",
        kind=TimelineEventKind.REVISION,
        occurred_at=datetime(2026, 9, 13, tzinfo=UTC),
        server_id="demo",
        revision_id="abc123",
        summary="Observed revision",
    )

    encoded = encode_sse_event(event)
    lines = encoded.strip().splitlines()

    assert lines[0] == "id: revision:abc123"
    assert lines[1] == "event: revision"
    payload = json.loads(lines[2].removeprefix("data: "))
    assert payload["revision_id"] == "abc123"
    assert payload["server_id"] == "demo"


def test_sse_comment_sanitizes_newlines():
    assert encode_sse_comment("keep\nalive") == ": keep alive\n\n"
