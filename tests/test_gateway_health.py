from __future__ import annotations

import pytest

from driftguard.gateway import GuardStore, IdentityMismatch, ServerIdentity


def test_heartbeat_never_creates_consent_and_is_bound_to_live_identity(tmp_path):
    with GuardStore(tmp_path / "guard.sqlite3") as store:
        first = ServerIdentity("fixture", "config-one", "session-one")
        store.register_server(first)
        assert store.gateway_health() == []
        store.mark_gateway(first, active=True)
        assert store.gateway_health()[0]["active"] == 1
        assert store.list_tools() == []
        replacement = ServerIdentity("fixture", "config-one", "session-two")
        store.register_server(replacement)
        assert store.gateway_health() == []
        with pytest.raises(IdentityMismatch):
            store.mark_gateway(first, active=False)
        store.mark_gateway(replacement, active=True)
        with pytest.raises(IdentityMismatch):
            store.mark_gateway(first, active=True)
        assert store.gateway_health()[0]["active"] == 1
        store.mark_gateway(replacement, active=False)
        assert store.gateway_health()[0]["active"] == 0
