import json

import pytest

from driftguard.desktop_bridge import execute
from driftguard.gateway import GateError, GuardStore
from driftguard.host_catalog import import_source, list_sources


def source(tools=True):
    return {"source_id": "figma", "name": "Figma", "description": "Design tools from the current host.",
            "captured_at": "2026-10-28T00:00:00Z", "visibility": "session_tools" if tools else "skills_only",
            "tools": [{"name": "inspect_design", "description": "Read a selected design."}] if tools else []}


def test_host_descriptions_persist_and_missing_contract_is_explicit(tmp_path):
    path = tmp_path / "host.db"
    with GuardStore(path) as store:
        imported = import_source(store, source())
        assert imported["tools_count"] == 1
        row = store.list_tools()[0]
        assert row["description"] == "Read a selected design."
        assert row["definition"]["x-driftguard-input-schema"] == "not-exported"
        assert not store.gateway_health()
        approved = store.approve(row["server_id"], row["tool_name"], expected_hash=row["sha256"], expected_revision=row["revision"])
        with pytest.raises(GateError, match="cannot authorize"):
            store.authorize_call(row["server_id"], row["tool_name"], expected_hash=approved["sha256"], expected_revision=approved["revision"])
    with GuardStore(path) as store:
        saved = list_sources(store)
        assert saved[0]["name"] == "Figma" and saved[0]["tools"][0]["description"]


def test_skill_only_app_remains_visible_without_fabricated_tools(tmp_path):
    with GuardStore(tmp_path / "host.db") as store:
        imported = import_source(store, source(False))
        assert imported["tools_count"] == 0 and not store.list_tools()
        assert list_sources(store)[0]["visibility"] == "skills_only"


def test_host_import_changes_are_reviewed_again(tmp_path):
    with GuardStore(tmp_path / "host.db") as store:
        original = source()
        import_source(store, original)
        row = store.list_tools()[0]
        store.approve(row["server_id"], row["tool_name"], expected_hash=row["sha256"], expected_revision=row["revision"])
        original["tools"][0]["description"] = "Read selected design details."
        import_source(store, original)
        assert store.list_tools()[0]["status"] != "approved"
        assert len(store.history(row["server_id"], row["tool_name"])) == 2


@pytest.mark.parametrize("update", [{"command": "whoami"}, {"source_id": "host:live"}, {"tools": [{"name": "read", "description": "x", "inputSchema": {}}]}, {"visibility": "connected"}])
def test_invalid_host_metadata_cannot_change_the_store(tmp_path, update):
    with GuardStore(tmp_path / "host.db") as store:
        with pytest.raises(ValueError):
            import_source(store, {**source(), **update})
        assert not store.list_servers()


def test_native_host_request_boundary_accepts_metadata_and_rejects_command(tmp_path):
    db = tmp_path / "host.db"
    imported = execute(db, json.dumps({"action": "host_catalog_import", "source": source()}).encode())
    assert imported["ok"]
    listed = execute(db, b'{"action":"host_catalog_list"}')
    assert listed["ok"] and listed["data"][0]["tools"][0]["name"] == "inspect_design"
    assert not execute(db, b'{"action":"host_catalog_list","command":"whoami"}')["ok"]
