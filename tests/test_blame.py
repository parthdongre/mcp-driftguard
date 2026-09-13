from datetime import UTC, datetime, timedelta

from driftguard.blame import blame_tool
from driftguard.revisions import make_discovery_revision


def _tool(description: str, *, token: bool = False):
    properties = {"query": {"type": "string"}}
    required = ["query"]
    if token:
        properties["api_token"] = {
            "type": "string",
            "description": "Credential token",
        }
        required.append("api_token")
    return {
        "name": "search",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def _history():
    start = datetime(2026, 9, 13, tzinfo=UTC)
    first = make_discovery_revision(
        server_id="demo",
        tools=[_tool("Search documents")],
        observed_at=start,
    )
    second = make_discovery_revision(
        server_id="demo",
        tools=[_tool("Search indexed documents")],
        parent_revision_id=first.revision_id,
        observed_at=start + timedelta(seconds=1),
    )
    third = make_discovery_revision(
        server_id="demo",
        tools=[_tool("Search indexed documents", token=True)],
        parent_revision_id=second.revision_id,
        observed_at=start + timedelta(seconds=2),
    )
    return first, second, third


def test_blame_tracks_last_revision_for_each_current_field():
    first, second, third = _history()

    result = blame_tool([first, second, third], tool_name="search")

    assert result is not None
    blame = {item.path: item.revision_id for item in result.fields}
    assert blame["/name"] == first.revision_id
    assert blame["/description"] == second.revision_id
    assert blame["/inputSchema/properties/api_token/type"] == third.revision_id
    assert blame["/inputSchema/required"] == third.revision_id


def test_blame_path_prefix_selects_capability_subtree():
    first, second, third = _history()

    result = blame_tool(
        [first, second, third],
        tool_name="search",
        path_prefix="/inputSchema/properties/api_token",
    )

    assert result is not None
    assert result.fields
    assert all(
        item.path.startswith("/inputSchema/properties/api_token/")
        for item in result.fields
    )
    assert {item.revision_id for item in result.fields} == {third.revision_id}


def test_blame_restarts_after_tool_removal_and_readdition():
    first, _, _ = _history()
    removed = make_discovery_revision(
        server_id="demo",
        tools=[],
        parent_revision_id=first.revision_id,
        observed_at=first.observed_at + timedelta(seconds=1),
    )
    readded = make_discovery_revision(
        server_id="demo",
        tools=[_tool("Search documents")],
        parent_revision_id=removed.revision_id,
        observed_at=first.observed_at + timedelta(seconds=2),
    )

    result = blame_tool([first, removed, readded], tool_name="search")

    assert result is not None
    assert result.fields
    assert {item.revision_id for item in result.fields} == {readded.revision_id}


def test_blame_reports_duplicate_target_as_ambiguous():
    first, _, _ = _history()
    duplicate = make_discovery_revision(
        server_id="demo",
        tools=[
            _tool("Search A"),
            _tool("Search B"),
        ],
        parent_revision_id=first.revision_id,
        observed_at=first.observed_at + timedelta(seconds=1),
    )

    result = blame_tool([first, duplicate], tool_name="search")

    assert result is not None
    assert result.ambiguous is True
    assert result.fields == []
