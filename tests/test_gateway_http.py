"""Actual loopback HTTP/SSE exchanges; no external target server is executed."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from driftguard.gateway import GateError, GuardStore
from driftguard.gateway_http import HttpConfig, HttpPeer, load_config
from driftguard.gateway_transport import LEGACY, MODERN, ProtectedGateway, TransportError

TOOL = {"name": "read_notes", "description": "Read selected résumé notes",
        "inputSchema": {"type": "object", "properties": {}}}


@contextmanager
def server(*, sse=False, failure=None):
    state = {"requests": [], "session": "fixture-session-one", "tools": [TOOL], "calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            message = json.loads(raw)
            state["requests"].append((message, dict(self.headers)))
            if failure == "slow":
                time.sleep(0.2)
            method = message["method"]
            if "id" not in message:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {"protocolVersion": LEGACY, "capabilities": {"tools": {}}}
            elif method == "server/discover":
                result = {"resultType": "complete", "supportedVersions": [MODERN],
                          "capabilities": {"tools": {}}}
            elif method == "tools/list":
                result = {"tools": state["tools"]}
            else:
                state["calls"] += 1
                result = {"content": [{"type": "text", "text": "safe result"}]}
            if self.headers.get("MCP-Protocol-Version") == MODERN:
                result["resultType"] = "complete"
            message = {"jsonrpc": "2.0", "id": message["id"], "result": result}
            if failure == "wrong_id":
                message["id"] += 1
            if failure == "duplicate_json":
                payload = b'{"jsonrpc":"2.0","id":1,"id":1,"result":{}}'
            elif failure == "oversized":
                payload = b"x" * 2048
            elif failure == "callback":
                payload = json.dumps({"jsonrpc": "2.0", "id": 9, "method": "sampling/createMessage"}).encode()
            else:
                payload = json.dumps(message).encode()
            if failure == "slow_sse":
                payload = b"data:" + b"x" * 40
            if sse:
                payload = b": keepalive\n\ndata: " + payload + b"\n\n"
            self.send_response(302 if failure == "redirect" else 200)
            self.send_header("Content-Type", "text/event-stream" if sse else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Mcp-Session-Id", state["session"])
            if failure == "redirect":
                self.send_header("Location", "https://unrequested.invalid/")
            if failure == "compressed":
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            try:
                if failure == "slow_sse":
                    for byte in payload:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.03)
                else:
                    self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/mcp", state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def config(url, **kwargs):
    return HttpConfig("http-fixture", url, allow_insecure_loopback=True, **kwargs)


@pytest.mark.parametrize("url", [
    "http://example.com/mcp", "http://localhost/mcp", "https://user:pass@example.com/mcp",
    "https://example.com/mcp?token=secret", "https://example.com/mcp#fragment",
    "file:///etc/passwd", "https://example.com:0/mcp",
])
def test_http_configuration_rejects_unsafe_or_ambiguous_endpoints(url):
    with pytest.raises(ValueError):
        HttpConfig("fixture", url)


def test_plain_loopback_is_explicit_and_environment_contains_only_token_name(monkeypatch):
    with pytest.raises(ValueError):
        HttpConfig("fixture", "http://127.0.0.1/mcp")
    monkeypatch.setenv("FIXTURE_HTTP_TOKEN", "authored-fixture-token")
    profile = HttpConfig("fixture", "https://example.com/mcp", auth_token_env="FIXTURE_HTTP_TOKEN")
    assert profile.pass_env == ("FIXTURE_HTTP_TOKEN",)
    assert "authored-fixture-token" not in repr(profile.identity())
    with pytest.raises(ValueError):
        HttpConfig("fixture", "https://example.com/mcp", auth_token_env="TOKEN=value")


@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("protocol", [LEGACY, MODERN])
def test_actual_http_gateway_requires_exact_approval_and_preserves_session(tmp_path, sse, protocol):
    with server(sse=sse) as (url, state), GuardStore(tmp_path / "guard.sqlite3") as store:
        gateway = ProtectedGateway(config(url, protocol_version=protocol), store)
        try:
            assert gateway.list_approved() == []
            with pytest.raises(GateError):
                gateway.call("read_notes", {})
            assert state["calls"] == 0
            record = store.get_tool("http-fixture", "read_notes")
            store.approve("http-fixture", "read_notes", expected_hash=record["sha256"],
                          expected_revision=record["revision"])
            assert len(gateway.list_approved()) == 1
            assert gateway.call("read_notes", {})["content"][0]["text"] == "safe result"
            assert state["calls"] == 1
            state["tools"] = [{**TOOL, "description": "Changed behavior declaration"}]
            with pytest.raises(GateError):
                gateway.call("read_notes", {})
            assert state["calls"] == 1
            assert any(headers.get("Mcp-Session-Id") == "fixture-session-one"
                       for _, headers in state["requests"][1:])
        finally:
            gateway.close()


@pytest.mark.parametrize("failure", [
    "wrong_id", "duplicate_json", "oversized", "callback", "redirect", "compressed",
])
def test_bad_http_responses_fail_closed_without_retries(failure):
    with server(failure=failure) as (url, state):
        peer = HttpPeer(config(url, max_message_bytes=1024))
        with pytest.raises(TransportError):
            peer.initialize()
        assert len(state["requests"]) == 1
        with pytest.raises(TransportError):
            peer.request("tools/list")
        assert len(state["requests"]) == 1


def test_http_deadline_bounds_the_callers_waiting():
    with server(failure="slow") as (url, state):
        peer = HttpPeer(config(url, timeout_seconds=0.05))
        started = time.monotonic()
        with pytest.raises(TransportError):
            peer.initialize()
        assert time.monotonic() - started < 1
        assert len(state["requests"]) == 1


def test_session_replacement_revokes_approval_in_shared_store(tmp_path):
    with server() as (url, state), GuardStore(tmp_path / "guard.sqlite3") as store:
        gateway = ProtectedGateway(config(url), store)
        record = store.get_tool("http-fixture", "read_notes")
        store.approve("http-fixture", "read_notes", expected_hash=record["sha256"],
                      expected_revision=record["revision"])
        state["session"] = "different-session"
        with pytest.raises(TransportError):
            gateway.list_approved()
        assert store.get_tool("http-fixture", "read_notes")["status"] != "approved"


def test_token_rotation_invalidates_live_identity(monkeypatch):
    monkeypatch.setenv("FIXTURE_HTTP_TOKEN", "authored-first-token")
    with server() as (url, state):
        peer = HttpPeer(config(url, auth_token_env="FIXTURE_HTTP_TOKEN"))
        peer.initialize()
        assert state["requests"][0][1]["Authorization"] == "Bearer authored-first-token"
        count = len(state["requests"])
        monkeypatch.setenv("FIXTURE_HTTP_TOKEN", "authored-second-token")
        with pytest.raises(TransportError):
            peer.request("tools/list")
        assert len(state["requests"]) == count


def test_loader_preserves_explicit_transport_and_rejects_unknown_keys(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"server_id": "fixture", "transport": "http",
                                "url": "https://example.com/mcp"}))
    assert isinstance(load_config(path), HttpConfig)
    path.write_text('{"transport":"http","server_id":"fixture","url":"https://example.com","token":"secret"}')
    with pytest.raises(ValueError):
        load_config(path)

def test_slow_sse_cannot_hold_a_buffered_read_lock_past_the_deadline():
    with server(sse=True, failure="slow_sse") as (url, _):
        peer = HttpPeer(config(url, timeout_seconds=0.05))
        started = time.monotonic()
        with pytest.raises(TransportError):
            peer.initialize()
        assert time.monotonic() - started < 0.5
