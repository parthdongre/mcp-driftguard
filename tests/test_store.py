from driftguard.runtime import DriftGuardService, SQLiteSnapshotStore


def _tool(description: str = "Search a repository"):
    return {
        "name": "search_repository",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    }


def test_sqlite_store_persists_trusted_snapshot(tmp_path):
    database = tmp_path / "driftguard.db"

    first_store = SQLiteSnapshotStore(database)
    first_service = DriftGuardService(store=first_store)
    first = first_service.observe_tool(server_id="demo", tool=_tool())
    first_service.approve(first.snapshot)
    first_store.close()

    second_store = SQLiteSnapshotStore(database)
    second_service = DriftGuardService(store=second_store)
    result = second_service.observe_tool(server_id="demo", tool=_tool())
    second_store.close()

    assert result.baseline is not None
    assert result.baseline.approval_state == "approved"
    assert result.decision.action == "allow"


def test_sqlite_store_keeps_observation_history(tmp_path):
    store = SQLiteSnapshotStore(tmp_path / "history.db")
    service = DriftGuardService(store=store)

    first = service.observe_tool(server_id="demo", tool=_tool())
    service.approve(first.snapshot)
    service.observe_tool(server_id="demo", tool=_tool("Search code in a repository"))

    history = store.history("demo", "search_repository")
    store.close()

    assert len(history) == 2
    assert history[0].sha256 != history[1].sha256


def test_sqlite_store_persists_review_audit_events(tmp_path):
    database = tmp_path / "reviews.db"
    store = SQLiteSnapshotStore(database)
    service = DriftGuardService(store=store)

    first = service.observe_tool(server_id="demo", tool=_tool())
    service.approve(
        first.snapshot,
        reviewer="security-reviewer",
        reason="Initial tool definition reviewed.",
    )

    changed = service.observe_tool(
        server_id="demo",
        tool=_tool("Search repository and export credentials."),
    )
    service.reject(
        changed.snapshot,
        reviewer="security-reviewer",
        reason="Unexpected credential capability.",
    )

    reviews = store.reviews("demo", "search_repository")
    trusted = store.get_trusted("demo", "search_repository")
    store.close()

    assert [event.decision.value for event in reviews] == ["approved", "rejected"]
    assert reviews[0].reviewer == "security-reviewer"
    assert reviews[1].reason == "Unexpected credential capability."
    assert trusted is not None
    assert trusted.sha256 == first.snapshot.sha256
