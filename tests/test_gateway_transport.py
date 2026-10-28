"""Actual subprocess wire tests using only an authored local fixture server."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from driftguard.gateway import GateError, GuardStore
from driftguard.gateway_transport import (
    LEGACY,
    HANDSHAKE_VERSIONS,
    MODERN,
    DownstreamSession,
    ProtectedGateway,
    RpcError,
    StdioConfig,
    TransportError,
    decode_message,
    protocol_meta,
)

FIXTURE = r'''
import json, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    with (root / "wire.jsonl").open("a") as stream:
        stream.write(json.dumps(request) + "\n")
    control = json.loads((root / "control.json").read_text())
    method = request["method"]
    if control.get("mode") == "timeout" and method == "tools/list":
        time.sleep(5)
    if control.get("mode") == "noise" and method == "tools/list":
        print("this is not json", flush=True)
        continue
    if control.get("mode") == "oversized" and method == "tools/list":
        print("x" * 2000000, flush=True)
        continue
    if method == "initialize":
        result = {"protocolVersion": control.get("negotiatedVersion", "2025-11-25"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "owned-fixture", "version": "1"}}
    elif method == "server/discover":
        result = {"resultType": "complete", "supportedVersions": ["2026-07-28"],
                  "capabilities": {"tools": {}}, "ttlMs": 0, "cacheScope": "private"}
    elif method == "tools/list":
        result = {"tools": control["tools"]}
        if control.get("mode") == "cursor":
            result["nextCursor"] = "same-cursor"
    elif method == "tools/call":
        with (root / "calls.jsonl").open("a") as stream:
            stream.write(json.dumps(request["params"]) + "\n")
        result = control.get("output", {"content": [{"type": "text", "text": "Sunny"}]})
    else:
        result = {}
    if request.get("params", {}).get("_meta", {}).get("io.modelcontextprotocol/protocolVersion"):
        result["resultType"] = (control.get("callResultType", "complete") if method == "tools/call"
                                else control.get("resultType", "complete"))
    response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
    if control.get("mode") == "wrong-id" and method == "tools/list":
        response["id"] += 100
    print(json.dumps(response), flush=True)
'''


def tool(description="Read weather information"):
    return {"name": "weather", "description": description,
            "inputSchema": {"type": "object", "properties": {}}}


@pytest.fixture
def server(tmp_path):
    script = tmp_path / "owned_server.py"
    script.write_text(FIXTURE)
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"tools": [tool()]}))
    def config(version=MODERN, **kwargs):
        return StdioConfig("fixture", (sys.executable, str(script), str(tmp_path)),
                           cwd=str(tmp_path), protocol_version=version, **kwargs)
    def update(**kwargs):
        value = json.loads(control.read_text())
        value.update(kwargs)
        control.write_text(json.dumps(value))
    return config, update, tmp_path


def approve(store):
    record = store.get_tool("fixture", "weather")
    return store.approve("fixture", "weather", expected_hash=record["sha256"],
                         expected_revision=record["revision"])


@pytest.mark.parametrize("version", [MODERN, LEGACY])
def test_real_stdio_requires_exact_review_and_forwards_only_approved(server, version):
    config, _, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(version), store)
        try:
            assert gateway.list_approved() == []
            with pytest.raises(GateError):
                gateway.call("weather", {})
            assert not (root / "calls.jsonl").exists()
            approve(store)
            assert gateway.list_approved() == [tool()]
            assert gateway.call("weather", {})["content"][0]["text"] == "Sunny"
            wire = [json.loads(line) for line in (root / "wire.jsonl").read_text().splitlines()]
            assert wire[-2]["method"] == "tools/list"
            assert wire[-1]["method"] == "tools/call"
            if version == MODERN:
                assert wire[0]["method"] == "server/discover"
                assert all(request["params"]["_meta"] == protocol_meta() for request in wire)
            else:
                assert wire[0]["method"] == "initialize"
                assert "_meta" not in wire[-1]["params"]
        finally:
            gateway.close()


def test_changed_definition_and_revocation_block_dispatch(server):
    config, update, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        try:
            approve(store)
            update(tools=[tool("Read current weather forecasts")])
            with pytest.raises(GateError):
                gateway.call("weather", {})
            assert not (root / "calls.jsonl").exists()
            record = approve(store)
            store.revoke("fixture", "weather", expected_hash=record["sha256"],
                         expected_revision=record["revision"])
            with pytest.raises(GateError):
                gateway.call("weather", {})
        finally:
            gateway.close()


@pytest.mark.parametrize("mode", ["timeout", "noise", "oversized", "wrong-id", "cursor"])
def test_bad_upstream_fails_closed_invalidates_and_never_invokes(server, mode):
    config, update, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(timeout_seconds=0.2), store)
        approve(store)
        update(mode=mode)
        with pytest.raises((TransportError, GateError)):
            gateway.call("weather", {})
        assert gateway.peer.process.poll() is not None
        assert store.get_tool("fixture", "weather")["status"] == "revoked"
        assert not (root / "calls.jsonl").exists()
        gateway.close()


def test_duplicate_tool_names_reject_whole_catalog(server):
    config, update, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        approve(store)
        update(tools=[tool(), tool()])
        with pytest.raises(TransportError, match="duplicate"):
            gateway.call("weather", {})
        assert store.list_servers()[0]["catalog_valid"] == 0
        assert not (root / "calls.jsonl").exists()


def test_identity_changed_script_is_not_dispatched(server):
    config, _, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        approve(store)
        with (root / "owned_server.py").open("a") as stream:
            stream.write("\n# replacement version\n")
        with pytest.raises(TransportError, match="changed"):
            gateway.call("weather", {})
        assert not (root / "calls.jsonl").exists()


@pytest.mark.parametrize("output", [
    {"content": [{"type": "resource_link", "uri": "file:///secret"}]},
    {"content": [{"type": "text", "text": "-----BEGIN PRIVATE KEY-----secret"}]},
    {"content": "invalid"},
])
def test_independent_output_policy_blocks_unsupported_or_secret_results(server, output):
    config, update, _ = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        approve(store)
        update(output=output)
        with pytest.raises(TransportError):
            gateway.call("weather", {})
        assert any(event["event_type"] == "call_failed" for event in store.events())


def test_configured_credential_is_blocked_at_egress(server, monkeypatch):
    config, update, _ = server
    monkeypatch.setenv("DRIFTGUARD_TEST_TOKEN", "secret-token-fixture-123")
    with GuardStore() as store:
        gateway = ProtectedGateway(config(pass_env=("DRIFTGUARD_TEST_TOKEN",)), store)
        approve(store)
        update(output={"content": [{"type": "text", "text": "secret-token-fixture-123"}]})
        with pytest.raises(TransportError, match="credential"):
            gateway.call("weather", {})
        assert "secret-token-fixture-123" not in json.dumps(store.events())


def test_active_policy_change_blocks_same_live_connection(server):
    config, _, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        try:
            approve(store)
            store.set_policy_revision("new-policy-v2")
            with pytest.raises(GateError):
                gateway.call("weather", {})
            assert not (root / "calls.jsonl").exists()
            assert any(event["event_type"] == "gateway_call_blocked" for event in store.events())
        finally:
            gateway.close()


def test_reconnect_requires_new_review(server):
    config, _, root = server
    with GuardStore() as store:
        first = ProtectedGateway(config(), store)
        approve(store)
        first.close()
        second = ProtectedGateway(config(), store)
        try:
            assert second.list_approved() == []
            with pytest.raises(GateError):
                second.call("weather", {})
            assert not (root / "calls.jsonl").exists()
        finally:
            second.close()


def test_stale_connection_cannot_overwrite_or_revoke_replacement(server):
    config, _, _ = server
    with GuardStore() as store:
        original_config = config()
        first = ProtectedGateway(original_config, store)
        approve(store)
        # Starting a replacement without closing the original simulates a stale
        # persisted approval after a gateway crash and a concurrently old child.
        second = ProtectedGateway(original_config, store)
        try:
            assert second.identity.auth_context != first.identity.auth_context
            assert second.list_approved() == []
            approved = approve(store)
            with pytest.raises(GateError, match="identity"):
                first.refresh_catalog()
            assert first.peer.process.poll() is not None
            assert store.get_tool("fixture", "weather")["status"] == "approved"
            assert store.get_tool("fixture", "weather")["revision"] == approved["revision"]
            assert second.call("weather", {})["content"][0]["text"] == "Sunny"
        finally:
            first.close()
            second.close()


def test_idle_process_death_invalidates_review_state(server):
    config, _, _ = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        approve(store)
        gateway.peer.process.kill()
        gateway._monitor.join(timeout=2)
        assert not gateway._monitor.is_alive()
        assert store.list_servers()[0]["catalog_valid"] == 0
        assert store.get_tool("fixture", "weather")["status"] == "revoked"
        gateway.close()


def test_credentials_in_catalog_are_blocked_before_storage(server, monkeypatch):
    config, update, _ = server
    monkeypatch.setenv("DRIFTGUARD_TEST_TOKEN", 'secret-"token-fixture-123')
    with GuardStore() as store:
        gateway = ProtectedGateway(config(pass_env=("DRIFTGUARD_TEST_TOKEN",)), store)
        approve(store)
        update(tools=[tool('Read secret-"token-fixture-123')])
        with pytest.raises(TransportError, match="credential"):
            gateway.call("weather", {})
        assert 'secret-"token-fixture-123' not in json.dumps(store.events() + store.list_tools())


def test_output_schema_contract_is_hidden_and_blocked_before_execution(server):
    config, update, root = server
    definition = {**tool(), "outputSchema": {"type": "object"}}
    update(tools=[definition])
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        try:
            approve(store)
            assert gateway.list_approved() == []
            with pytest.raises(RpcError, match="outputSchema"):
                gateway.call("weather", {})
            assert not (root / "calls.jsonl").exists()
            assert any(event.get("details", {}).get("reason") == "unsupported_output_contract"
                       for event in store.events())
        finally:
            gateway.close()


@pytest.mark.parametrize("method", ["ping", "tools/list", "tools/call"])
def test_downstream_modern_results_always_identify_gateway(server, method):
    config, _, _ = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        try:
            approve(store)
            params = {"_meta": protocol_meta()}
            if method == "tools/call":
                params.update(name="weather", arguments={})
            reply = DownstreamSession(gateway).handle({"jsonrpc": "2.0", "id": 1,
                                                       "method": method, "params": params})
            assert reply["result"]["resultType"] == "complete"
            assert reply["result"]["_meta"]["io.modelcontextprotocol/serverInfo"] == {
                "name": "driftguard", "version": "0.4.0"}
        finally:
            gateway.close()


def test_modern_mrtr_is_rejected_without_forwarding_input_request(server):
    config, update, _ = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        approve(store)
        update(output={"content": [{"type": "text", "text": "waiting"}],
                       "inputRequests": {"sample": {"method": "sampling/createMessage"}}},
               callResultType="input_required")
        with pytest.raises(TransportError, match="complete"):
            gateway.call("weather", {})


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": float("nan")}, {"max_tools": True}, {"pass_env": (123,)},
    {"max_message_bytes": -1}, {"protocol_version": "unknown"},
])
def test_invalid_configuration_limits_fail_early(server, kwargs):
    config, _, _ = server
    with pytest.raises((ValueError, TypeError)):
        config(**kwargs)


def test_downstream_modern_metadata_and_method_allowlist(server):
    config, _, root = server
    with GuardStore() as store:
        gateway = ProtectedGateway(config(), store)
        session = DownstreamSession(gateway)
        try:
            malformed = session.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert malformed["error"]["code"] == -32600
            discover = session.handle({"jsonrpc": "2.0", "id": 2, "method": "server/discover",
                                       "params": {"_meta": protocol_meta()}})
            assert discover["result"]["supportedVersions"] == [MODERN, *HANDSHAKE_VERSIONS]
            blocked = session.handle({"jsonrpc": "2.0", "id": 3, "method": "roots/list",
                                      "params": {"_meta": protocol_meta()}})
            assert blocked["error"]["code"] == -32601
            retry = session.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                    "params": {"_meta": protocol_meta(), "name": "weather"}})
            assert retry["error"]["code"] == -32600
            assert not (root / "calls.jsonl").exists()
        finally:
            gateway.close()


@pytest.mark.parametrize("raw", [
    b'{"jsonrpc":"2.0","id":1,"id":2}',
    b'{"jsonrpc":"2.0","value":NaN}',
    b'{"jsonrpc":"2.0","value":1e400}',
    b'{"jsonrpc":"2.0","value":"\\ud800"}',
    b'[{"jsonrpc":"2.0"}]',
    b'not json',
])
def test_strict_json_decoder(raw):
    with pytest.raises(TransportError):
        decode_message(raw)


def test_cli_keeps_stdout_json_only_and_does_not_log_command(server):
    config_factory, _, root = server
    config = config_factory()
    config_path = root / "gateway-config.json"
    config_path.write_text(json.dumps({"server_id": config.server_id, "argv": config.argv,
                                       "cwd": config.cwd, "protocol_version": MODERN}))
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
               "params": {"_meta": protocol_meta()}}
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    completed = subprocess.run([sys.executable, "-m", "driftguard.gateway_cli", "serve",
                                "--config", str(config_path), "--state", str(root / "state.db")],
                               input=json.dumps(request) + "\n", text=True, capture_output=True,
                               env=env, timeout=10, check=True)
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert responses[0]["result"]["tools"] == []
    assert "owned_server.py" not in completed.stderr
    assert "gateway active" in completed.stderr
