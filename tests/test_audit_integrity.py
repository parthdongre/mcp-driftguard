from driftguard.runtime import (
    DriftGuardService,
    InMemorySnapshotStore,
    ReviewDecision,
    SQLiteSnapshotStore,
    verify_review_chain,
)


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


def test_review_events_form_valid_hash_chain():
    service = DriftGuardService(store=InMemorySnapshotStore())
    first = service.observe_tool(server_id="demo", tool=_tool())
    service.approve(first.snapshot, reviewer="alice", reason="initial review")

    second = service.observe_tool(server_id="demo", tool=_tool("Search relevant documents"))
    service.reject(second.snapshot, reviewer="bob", reason="unexpected wording")

    events = service.store.reviews("demo", "search")
    report = verify_review_chain(events)

    assert report.valid is True
    assert report.event_count == 2
    assert report.head_hash == events[-1].event_hash
    assert events[0].previous_event_hash is None
    assert events[1].previous_event_hash == events[0].event_hash
    assert events[0].decision == ReviewDecision.APPROVED
    assert events[1].decision == ReviewDecision.REJECTED


def test_tampered_review_event_breaks_integrity():
    service = DriftGuardService(store=InMemorySnapshotStore())
    first = service.observe_tool(server_id="demo", tool=_tool())
    service.approve(first.snapshot, reviewer="alice")

    events = service.store.reviews("demo", "search")
    tampered = [events[0].model_copy(update={"reviewer": "mallory"})]
    report = verify_review_chain(tampered)

    assert report.valid is False
    assert report.first_invalid_index == 0
    assert "content" in (report.reason or "").lower()


def test_sqlite_review_chain_survives_restart(tmp_path):
    database = tmp_path / "audit.db"

    first_store = SQLiteSnapshotStore(database)
    first_service = DriftGuardService(store=first_store)
    first = first_service.observe_tool(server_id="demo", tool=_tool())
    first_service.approve(first.snapshot, reviewer="alice")
    first_store.close()

    second_store = SQLiteSnapshotStore(database)
    second_service = DriftGuardService(store=second_store)
    second = second_service.observe_tool(
        server_id="demo",
        tool=_tool("Search documents by keyword"),
    )
    second_service.reject(second.snapshot, reviewer="bob")

    events = second_store.reviews("demo", "search")
    report = verify_review_chain(events)
    second_store.close()

    assert report.valid is True
    assert len(events) == 2
    assert events[1].previous_event_hash == events[0].event_hash
