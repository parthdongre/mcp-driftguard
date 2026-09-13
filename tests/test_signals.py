from driftguard.runtime import DriftGuardService


def _tool():
    return {
        "name": "search",
        "description": "Search documents",
        "inputSchema": {"type": "object", "properties": {}},
    }


def test_catalog_change_signal_marks_status_dirty_until_next_surface_refresh():
    service = DriftGuardService()
    first = service.observe_surface(server_id="demo", tools=[_tool()])

    clean = service.catalog_freshness("demo")
    assert clean.dirty is False
    assert clean.last_refreshed_revision_id == first.revision.revision_id

    signal = service.mark_catalog_changed("demo")
    dirty = service.catalog_freshness("demo")

    assert dirty.dirty is True
    assert dirty.pending_signals == 1
    assert signal.acknowledged_revision_id is None

    refreshed = service.observe_surface(server_id="demo", tools=[_tool()])
    clean_again = service.catalog_freshness("demo")
    stored_signal = service.store.catalog_signals("demo")[0]

    assert clean_again.dirty is False
    assert clean_again.pending_signals == 0
    assert clean_again.last_refreshed_revision_id == refreshed.revision.revision_id
    assert stored_signal.acknowledged_revision_id == refreshed.revision.revision_id
    assert refreshed.freshness is not None
    assert refreshed.freshness.dirty is False


def test_multiple_pending_signals_are_acknowledged_by_one_refresh():
    service = DriftGuardService()
    service.mark_catalog_changed("demo")
    service.mark_catalog_changed("demo")

    assert service.catalog_freshness("demo").pending_signals == 2

    revision = service.observe_surface(server_id="demo", tools=[_tool()])

    assert service.catalog_freshness("demo").pending_signals == 0
    assert {
        signal.acknowledged_revision_id
        for signal in service.store.catalog_signals("demo")
    } == {revision.revision.revision_id}
