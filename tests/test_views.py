from driftguard.adapters import intercept_tools_list
from driftguard.checks import RevisionCheckState
from driftguard.runtime import DriftGuardService
from driftguard.views import build_revision_view


def _tool(description: str = "Search documents"):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_revision_view_combines_revision_diff_and_original_check():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.approve(first.observations[0].snapshot)

    second = intercept_tools_list(
        payload={"result": {"tools": [_tool("Search documents and metadata")]}},
        server_id="demo",
        service=service,
    )
    assert second.surface is not None
    assert second.revision_check is not None

    view = build_revision_view(
        service.revision_history("demo"),
        target_revision_id=second.surface.revision.revision_id,
        security_check=second.revision_check,
        freshness=service.catalog_freshness("demo"),
    )

    assert view is not None
    assert view.is_latest is True
    assert view.parent_delta is not None
    assert [item.tool_name for item in view.parent_delta.modified_tools] == ["search"]
    assert view.security_check.state in {
        RevisionCheckState.PASS,
        RevisionCheckState.REVIEW_REQUIRED,
        RevisionCheckState.BLOCKED,
    }
    assert view.freshness is not None
    assert view.freshness.dirty is False


def test_historical_revision_view_does_not_attach_current_freshness():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    intercept_tools_list(
        payload={"result": {"tools": [_tool("Search documents again")]}},
        server_id="demo",
        service=service,
    )

    assert first.surface is not None
    view = build_revision_view(
        service.revision_history("demo"),
        target_revision_id=first.surface.revision.revision_id,
        security_check=first.revision_check,
        freshness=service.catalog_freshness("demo"),
    )

    assert view is not None
    assert view.is_latest is False
    assert view.freshness is None
