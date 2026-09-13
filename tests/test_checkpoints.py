import pytest

from driftguard.adapters import intercept_tools_list
from driftguard.runtime import DriftGuardService


def _tool(description: str = "Search documents"):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


def _service_with_passing_revision():
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
    return service, passing.surface.revision.revision_id


def test_checkpoint_requires_revision_with_passing_security_check():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    assert first.surface is not None

    with pytest.raises(ValueError, match="PASS"):
        service.create_checkpoint(
            server_id="demo",
            name="known-good",
            revision_id=first.surface.revision.revision_id,
            created_by="alice",
        )


def test_checkpoint_is_named_immutable_reference_and_can_diff_to_latest():
    service, passing_revision = _service_with_passing_revision()
    checkpoint = service.create_checkpoint(
        server_id="demo",
        name="release/v1",
        revision_id=passing_revision,
        created_by="alice",
        note="Reviewed baseline.",
    )

    changed = intercept_tools_list(
        payload={"result": {"tools": [_tool("Search documents and metadata")]}},
        server_id="demo",
        service=service,
    )
    assert changed.surface is not None

    delta = service.compare_checkpoint(
        server_id="demo",
        checkpoint_name="release/v1",
        to_revision_id=changed.surface.revision.revision_id,
    )

    assert checkpoint.revision_id == passing_revision
    assert delta is not None
    assert [item.tool_name for item in delta.modified_tools] == ["search"]


def test_checkpoint_name_is_unique_per_server():
    service, passing_revision = _service_with_passing_revision()
    service.create_checkpoint(
        server_id="demo",
        name="baseline",
        revision_id=passing_revision,
        created_by="alice",
    )

    with pytest.raises(ValueError, match="already exists"):
        service.create_checkpoint(
            server_id="demo",
            name="baseline",
            revision_id=passing_revision,
            created_by="bob",
        )
