import json
import os
import subprocess
import sys

import pytest

from driftguard.desktop_bridge import MAX_REQUEST_BYTES, execute


def request(db, **payload):
    return execute(db, json.dumps(payload).encode())


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
