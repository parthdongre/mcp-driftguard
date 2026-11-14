from __future__ import annotations

import json
import os
import sys
import uuid

import pytest

from driftguard import credentials
from driftguard.desktop_bridge import execute
from driftguard.gateway_http import HttpConfig
from driftguard.gateway_transport import TransportError


def test_vault_identity_binds_exact_source_and_endpoint():
    assert credentials.account("a", "https://example.com/a") != credentials.account("a", "https://example.com/b")
    assert credentials.account("a", "https://example.com/a") != credentials.account("b", "https://example.com/a")


def test_renderer_can_write_but_never_read_credential_values(tmp_path, monkeypatch):
    written = []
    monkeypatch.setattr(credentials, "write", lambda server, endpoint, secret: written.append((server, endpoint, secret)))
    payload = {"action": "store_http_credential", "server_id": "fixture",
               "url": "https://example.com/mcp", "secret": "authored-test-secret"}
    response = execute(tmp_path / "guard.sqlite3", json.dumps(payload).encode())
    assert response == {"ok": True, "data": {"stored": True, "available": True}}
    assert written == [("fixture", "https://example.com/mcp", "authored-test-secret")]
    assert "authored-test-secret" not in json.dumps(response)
    response = execute(tmp_path / "guard.sqlite3", b'{"action":"read_http_credential"}')
    assert response["ok"] is False


def test_explicit_plain_loopback_credential_is_accepted_only_with_opt_in(tmp_path, monkeypatch, capsys):
    written = []
    monkeypatch.setattr(credentials, "write", lambda server, endpoint, secret: written.append((server, endpoint, secret)))
    monkeypatch.setattr(credentials.getpass, "getpass", lambda prompt: "authored-test-secret")
    loopback = "http://127.0.0.1:8765/mcp"
    db = tmp_path / "guard.sqlite3"
    request = {"action": "store_http_credential", "server_id": "fixture", "url": loopback,
               "secret": "authored-test-secret"}
    assert execute(db, json.dumps(request).encode())["ok"] is False
    assert credentials.main(["set", "--server-id", "fixture", "--url", loopback]) == 2
    assert execute(db, json.dumps({**request, "allow_insecure_loopback": "yes"}).encode())["ok"] is False
    assert written == []
    response = execute(db, json.dumps({**request, "allow_insecure_loopback": True}).encode())
    assert response == {"ok": True, "data": {"stored": True, "available": True}}
    assert credentials.main(["set", "--server-id", "fixture", "--url", loopback,
                             "--allow-insecure-loopback"]) == 0
    assert written == [("fixture", loopback, "authored-test-secret")] * 2
    # The opt-in never extends to non-loopback plain HTTP.
    remote = "http://example.com/mcp"
    assert execute(db, json.dumps({**request, "url": remote, "allow_insecure_loopback": True}).encode())["ok"] is False
    assert credentials.main(["set", "--server-id", "fixture", "--url", remote, "--allow-insecure-loopback"]) == 2
    assert len(written) == 2
    capsys.readouterr()


def test_vault_unavailability_has_no_plaintext_fallback(tmp_path, monkeypatch):
    def unavailable(*args):
        raise credentials.CredentialError(credentials.UNAVAILABLE)
    monkeypatch.setattr(credentials, "write", unavailable)
    response = execute(tmp_path / "guard.sqlite3", json.dumps({
        "action": "store_http_credential", "server_id": "fixture",
        "url": "https://example.com/mcp", "secret": "authored-test-secret"}).encode())
    assert response["data"]["available"] is False
    monkeypatch.setattr(credentials, "read", unavailable)
    with pytest.raises(TransportError):
        HttpConfig("fixture", "https://example.com/mcp", use_os_vault=True).token()


def test_http_vault_retrieval_is_endpoint_bound_and_exclusive(monkeypatch):
    calls = []
    monkeypatch.setattr(credentials, "read", lambda server, endpoint: calls.append((server, endpoint)) or "authored-test-token")
    profile = HttpConfig("fixture", "https://example.com/mcp", use_os_vault=True)
    assert profile.token() == "authored-test-token"
    assert calls == [("fixture", "https://example.com/mcp")]
    with pytest.raises(ValueError):
        HttpConfig("fixture", "https://example.com/mcp", use_os_vault=True, auth_token_env="TOKEN")


@pytest.mark.skipif(sys.platform != "darwin" and os.name != "nt",
                    reason="Native macOS/Windows store integration; Linux requires an unlocked Secret Service session")
def test_actual_native_vault_roundtrip_updates_and_deletes_only_fixture_account():
    server = "ci-fixture-" + uuid.uuid4().hex
    endpoint = "https://fixture.invalid/mcp"
    try:
        assert credentials.read(server, endpoint) is None
        credentials.write(server, endpoint, "authored-first-fixture-token")
        assert credentials.read(server, endpoint) == "authored-first-fixture-token"
        assert credentials.read(server, endpoint + "/different") is None
        credentials.write(server, endpoint, "authored-second-fixture-token")
        assert credentials.read(server, endpoint) == "authored-second-fixture-token"
    finally:
        credentials.write(server, endpoint, None)
    assert credentials.read(server, endpoint) is None
