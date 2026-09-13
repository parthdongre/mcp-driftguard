from driftguard.adapters import intercept_tools_list
from driftguard.runtime import DriftGuardService


def _tool(description: str = "Search documents"):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_overview_reports_divergence_from_latest_trusted_checkpoint():
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
        name="release/v1",
        revision_id=passing.surface.revision.revision_id,
        created_by="alice",
    )

    intercept_tools_list(
        payload={
            "result": {
                "tools": [
                    _tool("Search documents and metadata"),
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

    overview = service.overview("demo")

    assert overview is not None
    assert overview.latest_checkpoint is not None
    assert overview.latest_checkpoint.name == "release/v1"
    assert overview.revisions_since_checkpoint == 1
    assert overview.checkpoint_tree_matches is False
    assert overview.checkpoint_delta is not None
    assert overview.checkpoint_delta.added_tools == ["format"]
    assert [item.tool_name for item in overview.checkpoint_delta.modified_tools] == [
        "search"
    ]


def test_overview_without_checkpoint_still_reports_security_and_freshness():
    service = DriftGuardService()
    intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.mark_catalog_changed("demo")

    overview = service.overview("demo")

    assert overview is not None
    assert overview.latest_checkpoint is None
    assert overview.checkpoint_delta is None
    assert overview.latest_security_check is not None
    assert overview.freshness.dirty is True
    assert overview.tool_count == 1
