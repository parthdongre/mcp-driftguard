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

def test_sqlite_store_persists_discovery_revision_history(tmp_path):
    database = tmp_path / "revisions.db"
    store = SQLiteSnapshotStore(database)
    service = DriftGuardService(store=store)

    first = service.observe_surface(
        server_id="demo",
        tools=[_tool("Search repository")],
    )
    second = service.observe_surface(
        server_id="demo",
        tools=[_tool("Search repository with metadata")],
    )
    store.close()

    reopened = SQLiteSnapshotStore(database)
    history = reopened.revision_history("demo")
    latest = reopened.latest_revision("demo")
    reopened.close()

    assert len(history) == 2
    assert history[0].revision_id == first.revision.revision_id
    assert history[1].parent_revision_id == first.revision.revision_id
    assert latest is not None
    assert latest.revision_id == second.revision.revision_id


def test_sqlite_store_persists_catalog_change_signal_and_acknowledgement(tmp_path):
    database = tmp_path / "signals.db"
    store = SQLiteSnapshotStore(database)
    service = DriftGuardService(store=store)

    signal = service.mark_catalog_changed("demo")
    assert service.catalog_freshness("demo").dirty is True
    store.close()

    reopened = SQLiteSnapshotStore(database)
    persisted = reopened.catalog_signals("demo")
    assert len(persisted) == 1
    assert persisted[0].signal_id == signal.signal_id
    assert persisted[0].acknowledged_revision_id is None

    refreshed = DriftGuardService(store=reopened).observe_surface(
        server_id="demo",
        tools=[_tool()],
    )
    acknowledged = reopened.catalog_signals("demo")[0]
    reopened.close()

    assert acknowledged.acknowledged_revision_id == refreshed.revision.revision_id


def test_sqlite_store_persists_revision_security_check(tmp_path):
    from driftguard.adapters import intercept_tools_list

    database = tmp_path / "checks.db"
    store = SQLiteSnapshotStore(database)
    service = DriftGuardService(store=store)

    result = intercept_tools_list(
        payload={"result": {"tools": [_tool()]}},
        server_id="demo",
        service=service,
    )
    assert result.revision_check is not None
    revision_id = result.revision_check.revision_id
    store.close()

    reopened = SQLiteSnapshotStore(database)
    persisted = reopened.get_revision_check("demo", revision_id)
    history = reopened.revision_checks("demo")
    reopened.close()

    assert persisted is not None
    assert persisted.revision_id == revision_id
    assert persisted.state.value == "review_required"
    assert [item.revision_id for item in history] == [revision_id]


def test_sqlite_store_persists_trusted_checkpoint(tmp_path):
    from driftguard.adapters import intercept_tools_list

    database = tmp_path / "checkpoints.db"
    store = SQLiteSnapshotStore(database)
    service = DriftGuardService(store=store)

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

    checkpoint = service.create_checkpoint(
        server_id="demo",
        name="release/v1",
        revision_id=passing.surface.revision.revision_id,
        created_by="security-reviewer",
        note="Known-good release.",
    )
    store.close()

    reopened = SQLiteSnapshotStore(database)
    persisted = reopened.get_checkpoint("demo", "release/v1")
    history = reopened.checkpoints("demo")
    reopened.close()

    assert persisted is not None
    assert persisted.checkpoint_id == checkpoint.checkpoint_id
    assert persisted.revision_id == passing.surface.revision.revision_id
    assert [item.name for item in history] == ["release/v1"]
