"""Opt-in third-party MCP integration. Reads only an authored temporary file."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from driftguard.desktop_bridge import execute
from driftguard.gateway import GuardStore
from driftguard.gateway_transport import LEGACY, RpcError, StdioConfig, StdioPeer
from driftguard.live_setup import prepare


def test_official_filesystem_live_review_read_and_revocation(tmp_path):
    script = os.environ.get('DRIFTGUARD_TEST_FILESYSTEM')
    if not script or not Path(script).is_file() or not shutil.which('node'):
        pytest.skip('Set DRIFTGUARD_TEST_FILESYSTEM to an installed official server dist/index.js')
    db = tmp_path / 'state.db'
    setup = prepare(Path(script), tmp_path / 'connection', db)
    selected, profile = setup['sample'], setup['profile']
    # The client transport hashes fixed program files; a mutable state DB is
    # data, not one of this test client's immutable direct file arguments.
    launcher = tmp_path / 'gateway_client.py'
    launcher.write_text('from driftguard.gateway_cli import main\nraise SystemExit(main(' +
        repr(['serve', '--config', str(profile), '--state', str(db)]) + '))\n')
    client = StdioPeer(StdioConfig('test-client', (sys.executable, str(launcher)), cwd=str(tmp_path),
        protocol_version=LEGACY, timeout_seconds=15))
    try:
        client.initialize()
        assert client.request('tools/list')['tools'] == []
        with GuardStore(db) as store:
            row = store.get_tool('live-filesystem', 'read_text_file')
        approved = execute(db, json.dumps({'action': 'approve', 'server_id': row['server_id'],
            'tool_name': row['tool_name'], 'expected_sha256': row['sha256'],
            'expected_revision': row['revision']}).encode())
        assert approved['ok']
        assert client._messages.get(timeout=5)['method'] == 'notifications/tools/list_changed'
        tools = client.request('tools/list')['tools']
        assert [t['name'] for t in tools] == ['read_text_file']
        result = client.request('tools/call', {'name': 'read_text_file', 'arguments': {'path': str(selected)}})
        assert result['structuredContent'] == {'content': selected.read_text()}
        with GuardStore(db) as store:
            row = store.get_tool('live-filesystem', 'read_text_file')
        denied = execute(db, json.dumps({'action': 'deny', 'server_id': row['server_id'],
            'tool_name': row['tool_name'], 'expected_sha256': row['sha256'],
            'expected_revision': row['revision']}).encode())
        assert denied['ok']
        assert client._messages.get(timeout=5)['method'] == 'notifications/tools/list_changed'
        assert client.request('tools/list')['tools'] == []
        with pytest.raises(RpcError):
            client.request('tools/call', {'name': 'read_text_file', 'arguments': {'path': str(selected)}})
        with GuardStore(db) as store:
            events = store.events()
            assert sum(e['event_type'] == 'call_completed' for e in events) == 1
            assert any(e['event_type'] == 'gateway_call_blocked' for e in events)
    finally:
        client.close()
