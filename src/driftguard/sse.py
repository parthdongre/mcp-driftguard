from __future__ import annotations

from .timeline import TimelineEvent


def encode_sse_event(event: TimelineEvent) -> str:
    """Serialize one timeline event using standard Server-Sent Events framing."""

    return (
        f"id: {event.event_id}\n"
        f"event: {event.kind.value}\n"
        f"data: {event.model_dump_json()}\n\n"
    )


def encode_sse_comment(comment: str = "keepalive") -> str:
    """Encode an SSE comment/heartbeat that clients ignore as an application event."""

    safe = comment.replace("\r", " ").replace("\n", " ")
    return f": {safe}\n\n"
