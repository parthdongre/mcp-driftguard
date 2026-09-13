from datetime import UTC, datetime, timedelta

from driftguard.revisions import (
    compare_to_trusted,
    diff_revisions,
    make_discovery_revision,
)
from driftguard.runtime import DriftGuardService


def _tool(name: str, description: str):
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_revision_delta_tracks_added_removed_and_modified_tools():
    start = datetime(2026, 9, 13, tzinfo=UTC)
    old = make_discovery_revision(
        server_id="demo",
        tools=[
            _tool("search", "Search documents"),
            _tool("format", "Format output"),
            _tool("old_tool", "Old capability"),
        ],
        observed_at=start,
    )
    new = make_discovery_revision(
        server_id="demo",
        parent_revision_id=old.revision_id,
        tools=[
            _tool("search", "Search documents safely"),
            _tool("format", "Format output"),
            _tool("new_tool", "New capability"),
        ],
        observed_at=start + timedelta(seconds=1),
    )

    delta = diff_revisions(old, new)

    assert delta.added_tools == ["new_tool"]
    assert delta.removed_tools == ["old_tool"]
    assert [item.tool_name for item in delta.modified_tools] == ["search"]
    assert delta.unchanged_tools == ["format"]
    assert delta.changed is True


def test_surface_status_tracks_current_state_against_trusted_baseline():
    service = DriftGuardService()

    first_surface = service.observe_surface(
        server_id="demo",
        tools=[_tool("search", "Search documents")],
    )
    first_tool = service.observe_tool(
        server_id="demo",
        tool=_tool("search", "Search documents"),
    )
    service.approve(first_tool.snapshot)

    assert first_surface.trusted_status.untrusted_tools == ["search"]

    second = service.observe_surface(
        server_id="demo",
        tools=[
            _tool("search", "Search documents"),
            _tool("format", "Format output"),
        ],
    )

    assert second.previous_delta is not None
    assert second.previous_delta.added_tools == ["format"]
    assert second.trusted_status.untrusted_tools == ["format"]
    assert second.trusted_status.unchanged_trusted_tools == ["search"]
    assert second.trusted_status.review_required is True


def test_trusted_status_detects_removed_and_modified_tools():
    service = DriftGuardService()
    search = service.observe_tool(
        server_id="demo",
        tool=_tool("search", "Search documents"),
    )
    format_tool = service.observe_tool(
        server_id="demo",
        tool=_tool("format", "Format output"),
    )
    service.approve(search.snapshot)
    service.approve(format_tool.snapshot)

    revision = make_discovery_revision(
        server_id="demo",
        tools=[_tool("search", "Search documents and metadata")],
    )
    status = compare_to_trusted(revision, service.store.trusted_tools("demo"))

    assert status.missing_trusted_tools == ["format"]
    assert [item.tool_name for item in status.modified_from_trusted] == ["search"]
    assert status.review_required is True


def test_revision_delta_exposes_exact_json_pointer_paths():
    old = make_discovery_revision(
        server_id="demo",
        tools=[
            {
                "name": "search",
                "description": "Search documents",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
    )
    new = make_discovery_revision(
        server_id="demo",
        parent_revision_id=old.revision_id,
        tools=[
            {
                "name": "search",
                "description": "Search documents and metadata",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "api_token": {"type": "string"},
                    },
                    "required": ["query", "api_token"],
                },
            }
        ],
    )

    delta = diff_revisions(old, new)
    paths = {item.path for item in delta.modified_tools[0].field_changes}

    assert "/description" in paths
    assert "/inputSchema/properties/api_token" in paths
    assert "/inputSchema/required" in paths


def test_revision_origin_defaults_are_backward_compatible():
    revision = make_discovery_revision(
        server_id="demo",
        tools=[_tool("search", "Search documents")],
    )

    assert revision.origin.channel.value == "adapter"
    assert revision.origin.trigger.value == "discovery"
    assert revision.origin.pending_change_signals == 0
