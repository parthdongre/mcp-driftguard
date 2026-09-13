from driftguard.adapters import intercept_tools_list
from driftguard.runtime import DriftGuardService
from driftguard.timeline import TimelineEventKind


def _tool(description: str = "Search documents"):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_server_timeline_merges_revision_check_signal_and_review_events():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.approve(
        first.observations[0].snapshot,
        reviewer="alice",
        reason="Known local server.",
    )
    service.mark_catalog_changed("demo")
    intercept_tools_list(
        payload={"result": {"tools": [_tool("Search documents and metadata")]}},
        server_id="demo",
        service=service,
    )

    timeline = service.timeline("demo")
    kinds = {item.kind for item in timeline}

    assert TimelineEventKind.REVISION in kinds
    assert TimelineEventKind.SECURITY_CHECK in kinds
    assert TimelineEventKind.CATALOG_SIGNAL in kinds
    assert TimelineEventKind.REVIEW in kinds
    assert timeline == sorted(
        timeline,
        key=lambda item: (item.occurred_at, item.event_id),
        reverse=True,
    )


def test_timeline_revision_event_includes_provenance_and_change_summary():
    service = DriftGuardService()
    intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.mark_catalog_changed("demo")
    intercept_tools_list(
        payload={
            "result": {
                "tools": [
                    _tool("Search documents"),
                    {
                        "name": "format",
                        "description": "Format output",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        },
        server_id="demo",
        service=service,
    )

    revision_event = next(
        item
        for item in service.timeline("demo")
        if item.kind == TimelineEventKind.REVISION
        and item.details.get("trigger") == "list_changed_refresh"
    )

    assert revision_event.details["pending_change_signals"] == 1
    assert revision_event.details["added_tools"] == ["format"]


def test_timeline_cursor_accepts_event_id_and_raw_revision_id():
    from driftguard.timeline import build_server_timeline, timeline_events_after

    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.mark_catalog_changed("demo")

    chronological = build_server_timeline(
        revisions=service.store.revision_history("demo"),
        checks=service.store.revision_checks("demo"),
        signals=service.store.catalog_signals("demo"),
        reviews=service.store.server_reviews("demo"),
        newest_first=False,
    )

    assert first.surface is not None
    raw_revision = first.surface.revision.revision_id
    after_revision = timeline_events_after(chronological, raw_revision)
    assert after_revision is not None
    assert any(item.kind == TimelineEventKind.CATALOG_SIGNAL for item in after_revision)

    cursor = chronological[0].event_id
    after_event = timeline_events_after(chronological, cursor)
    assert after_event == chronological[1:]
    assert timeline_events_after(chronological, "missing") is None


def test_timeline_includes_trusted_checkpoint_event():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.approve(first.observations[0].snapshot)
    passing = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    assert passing.surface is not None

    service.create_checkpoint(
        server_id="demo",
        name="known-good",
        revision_id=passing.surface.revision.revision_id,
        created_by="alice",
    )
    timeline = service.timeline("demo")

    assert timeline is not None
    checkpoint_event = next(
        item for item in timeline if item.kind == TimelineEventKind.CHECKPOINT
    )
    assert checkpoint_event.details["name"] == "known-good"
    assert checkpoint_event.revision_id == passing.surface.revision.revision_id
