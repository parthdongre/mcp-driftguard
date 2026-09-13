from driftguard.checks import RevisionCheckState
from driftguard.adapters import intercept_tools_list
from driftguard.runtime import DriftGuardService


def _tool(description: str = "Search documents"):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


def test_revision_check_records_first_seen_review_requirement():
    service = DriftGuardService()
    result = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )

    check = result.revision_check
    assert check is not None
    assert check.state == RevisionCheckState.REVIEW_REQUIRED
    assert check.withheld_tools == ["search"]
    assert check.tools[0].action == "require_reconsent"
    assert service.store.get_revision_check("demo", check.revision_id) == check


def test_revision_check_passes_after_approved_unchanged_catalog():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.approve(first.observations[0].snapshot)

    second = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )

    assert second.revision_check is not None
    assert second.revision_check.state == RevisionCheckState.PASS
    assert second.revision_check.forwarded_tools == ["search"]
    assert second.revision_check.tools[0].change_class == "C0"
