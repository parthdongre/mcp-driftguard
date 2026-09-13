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
