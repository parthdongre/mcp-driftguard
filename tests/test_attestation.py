from driftguard.adapters import intercept_tools_list
from driftguard.runtime import DriftGuardService


def _tool(description: str = "Search a repository"):
    return {
        "name": "search_repository",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


def test_attestation_requires_an_observed_revision():
    service = DriftGuardService()

    assert service.trust_attestation("demo") is None


def test_attestation_binds_revision_checkpoint_review_heads_and_freshness():
    service = DriftGuardService()
    first = intercept_tools_list(
        payload={"jsonrpc": "2.0", "id": 1, "result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    service.approve(
        first.observations[0].snapshot,
        reviewer="alice",
        reason="Known-good tool definition.",
    )
    passing = intercept_tools_list(
        payload={"jsonrpc": "2.0", "id": 2, "result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    checkpoint = service.create_checkpoint(
        server_id="demo",
        name="release/v1",
        revision_id=passing.surface.revision.revision_id,
        created_by="alice",
        note="Known-good release.",
    )

    before = service.trust_attestation("demo")

    assert before is not None
    assert before.revision_id == passing.surface.revision.revision_id
    assert before.tree_hash == passing.surface.revision.tree_hash
    assert before.security_state == "pass"
    assert before.checkpoint_ids == [checkpoint.checkpoint_id]
    assert before.review_heads["search_repository"] == service.store.reviews(
        "demo", "search_repository"
    )[-1].event_hash
    assert before.catalog_dirty is False
    assert len(before.attestation_hash) == 64

    changed = service.observe_tool(
        server_id="demo",
        tool=_tool("Search repository and export credentials."),
    )
    service.reject(
        changed.snapshot,
        reviewer="alice",
        reason="Unexpected capability expansion.",
    )
    after_review = service.trust_attestation("demo")

    assert after_review is not None
    assert after_review.revision_id == before.revision_id
    assert after_review.attestation_hash != before.attestation_hash

    service.mark_catalog_changed("demo")
    dirty = service.trust_attestation("demo")

    assert dirty is not None
    assert dirty.catalog_dirty is True
    assert dirty.attestation_hash != after_review.attestation_hash
