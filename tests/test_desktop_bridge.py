import json
import os
import subprocess
import sys

import pytest

from driftguard.desktop_bridge import MAX_REQUEST_BYTES, execute


def request(db, **payload):
    return execute(db, json.dumps(payload).encode())


def test_definition_alerts_survive_restart_and_can_be_dismissed(tmp_path):
    db = tmp_path / "review.db"

    def observe(description):
        result = request(db, action="import_definitions", server_id="source", identity="fixture",
                         tools=[{"name": "read_note", "description": description,
                                 "inputSchema": {"type": "object"}}])
        assert result["ok"]

    observe("Read a note.")
    assert request(db, action="definition_alerts")["data"]["unread"] == 0
    observe("Read the selected note.")
    observe("Read the selected note.")
    alerts = request(db, action="definition_alerts")["data"]
    assert alerts["unread"] == 1
    assert alerts["latest"]["tool_name"] == "read_note"
    assert alerts["latest"]["detail"]["changed_fields"] == ["description"]
    alert_id = alerts["latest"]["id"]
    observe("Read the selected local note.")
    assert request(db, action="dismiss_definition_alerts", through_id=alert_id)["ok"]
    remaining = request(db, action="definition_alerts")["data"]
    assert remaining["unread"] == 1
    assert remaining["latest"]["id"] > alert_id
    history = request(db, action="history", server_id="import:source", tool_name="read_note")["data"]
    assert [entry["description"] for entry in history] == [
        "Read a note.", "Read the selected note.", "Read the selected local note.",
    ]


def test_release_quarantine_requires_current_revision_and_new_approval(tmp_path):
    db = tmp_path / "review.db"
    initial, = request(db, action="import_definitions", server_id="source", identity="fixture",
                       tools=[{"name": "read_note", "inputSchema": {"type": "object"}}])["data"]
    identity = {"server_id": initial["server_id"], "tool_name": initial["tool_name"],
                "expected_sha256": initial["sha256"], "expected_revision": initial["revision"]}
    quarantined = request(db, action="quarantine", **identity)["data"]
    assert not request(db, action="release_quarantine", **identity)["ok"]
    identity["expected_revision"] = quarantined["revision"]
    released = request(db, action="release_quarantine", **identity)["data"]
    assert released["status"] == "pending"
    assert not released["quarantine_active"]
    assert request(db, action="overview")["data"]["approved"] == 0
    identity["expected_revision"] = released["revision"]
    assert request(db, action="approve", **identity)["data"]["status"] == "approved"


def test_persistent_review_roundtrip_and_stale_decision_rejection(tmp_path):
    db = tmp_path / "review.db"
    imported = request(db, action="import_definitions", server_id="manual", identity="review-v1",
                       tools=[{"name": "search", "description": "Search local files",
                               "inputSchema": {"type": "object"}}])
    assert imported["ok"]
    tool = imported["data"][0]
    assert tool["server_id"] == "import:manual"
    assert tool["status"] == "pending"
    mutation = {"server_id": tool["server_id"], "tool_name": "search",
                "expected_sha256": tool["sha256"], "expected_revision": tool["revision"]}
    approved = request(db, action="approve", **mutation)
    assert approved["ok"]
    assert approved["data"]["status"] == "approved"
    assert not request(db, action="deny", **mutation)["ok"]
    overview = request(db, action="overview")["data"]
    assert overview["approved"] == 1
    assert overview["protection_status"] == "review_only"
    assert overview["research"]["cloud_analysis_enabled"] is False
    assert request(db, action="history", server_id="import:manual", tool_name="search")["data"]
    events = request(db, action="activity")["data"]
    assert any(event["event"] == "tool_approved" for event in events)


@pytest.mark.parametrize("raw", [b'{"action":"overview","action":"approve"}',
                                 b'{"action":NaN}', b'[]', b'null',
                                 b'{"action":"forward_call"}', b'\xff',
                                 b'x' * (MAX_REQUEST_BYTES + 1)],
                         ids=["duplicate-action", "nonfinite-json", "array", "null",
                              "unsupported-action", "invalid-utf8", "oversized-request"])
def test_invalid_ambiguous_and_unallowlisted_requests_fail_safely(tmp_path, raw):
    result = execute(tmp_path / "review.db", raw)
    assert not result["ok"]
    assert result["error"]["code"] == "invalid_request"
    assert "Traceback" not in json.dumps(result)


def test_subprocess_protocol_returns_one_json_response_without_input_echo(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "driftguard.desktop_bridge", "--db", str(tmp_path / "review.db")],
        input=b'{"action":"overview"}', capture_output=True, check=True, timeout=10,
    )
    assert json.loads(completed.stdout)["data"]["tools"] == 0
    assert len(completed.stdout.splitlines()) == 1
    assert not completed.stderr


def test_tool_summary_preserves_metadata_and_loads_full_contract_on_selection(tmp_path):
    db = tmp_path / 'review.db'
    definition = {'name': 'search', 'description': 'Read selected records',
                  'inputSchema': {'type': 'object', 'properties': {'id': {'type': 'string'}}}}
    assert request(db, action='import_definitions', server_id='summary', identity='fixture',
                   tools=[definition])['ok']
    summary = request(db, action='list_tools', summary=True)['data'][0]
    assert summary['description'] == definition['description']
    assert 'definition' not in summary and 'new_tool' not in summary
    full = request(db, action='list_tools')['data'][0]
    assert full['definition'] == definition
    review = request(db, action='review', server_id=summary['server_id'], tool_name='search')
    assert review['data']['new_tool'] == definition
    assert not request(db, action='list_tools', summary='yes')['ok']


def test_catalog_labels_follow_current_definition_without_changing_review_state(tmp_path):
    db = tmp_path / 'review.db'
    definition = {'name': 'move_file', 'title': 'Move a file',
                  'description': 'Move a file. Use read_file to inspect it first.',
                  'annotations': {'readOnlyHint': True},
                  'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}
    assert request(db, action='import_definitions', server_id='files', identity='fixture',
                   tools=[definition])['ok']
    summary = request(db, action='list_tools', summary=True)['data'][0]
    assert summary['catalog'] == {'operations': ['write'], 'resources': ['filesystem']}
    assert summary['status'] == 'pending'
    assert 'catalog' not in request(db, action='list_tools')['data'][0]

    changed = {'name': 'opaque', 'description': 'Query a database',
               'inputSchema': {'type': 'object'}}
    assert request(db, action='import_definitions', server_id='files', identity='fixture',
                   tools=[changed])['ok']
    summary, = request(db, action='list_tools', summary=True)['data']
    assert summary['catalog'] == {'operations': ['read'], 'resources': ['database']}


def test_subprocess_protocol_preserves_unicode_with_ascii_text_streams(tmp_path):
    description = "Read résumé notes — 测试 🌙"
    payload = {"action": "import_definitions", "server_id": "unicode",
               "identity": "local-unicode-fixture",
               "tools": [{"name": "read_note", "description": description,
                          "inputSchema": {"type": "object"}}]}
    completed = subprocess.run(
        [sys.executable, "-m", "driftguard.desktop_bridge", "--db",
         str(tmp_path / "révision 测试.db")],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True, check=True, timeout=10,
    )
    response = json.loads(completed.stdout.decode("utf-8"))
    assert response["ok"]
    assert response["data"][0]["definition"]["description"] == description
    assert not completed.stderr
