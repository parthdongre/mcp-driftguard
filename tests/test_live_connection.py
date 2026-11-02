"""Fixed in-app setup, real subprocess reconnects and actual-call proof checks."""
import json
import os
import shutil
import socket
import sys
import time
import tomllib

import pytest

from driftguard import live_connection as live
from driftguard.desktop_bridge import execute
from driftguard.gateway import GuardStore
from driftguard.gateway_transport import LEGACY, StdioConfig, StdioPeer

FIXTURE = r'''
import json, pathlib, sys
for line in sys.stdin:
    m=json.loads(line)
    if 'id' not in m: continue
    method=m['method']
    if method=='initialize':
        r={'protocolVersion':'2025-11-25','serverInfo':{'name':'owned','version':'1'},'capabilities':{'tools':{}}}
    elif method=='tools/list':
        r={'tools':[{'name':'read_text_file','description':'Read an app-owned file', 'inputSchema':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}}]}
    elif method=='tools/call':
        text=pathlib.Path(m['params']['arguments']['path']).read_text()
        r={'content':[{'type':'text','text':text}]}
    else: r={}
    print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
'''

CODEX = r'''#!/usr/bin/env node
const fs=require('node:fs'), cp=require('node:child_process');
const argv=process.argv.slice(2);
if(!argv.includes('--ignore-user-config') || !argv.includes('read-only') || argv.some(a=>a.includes('dangerously-bypass'))) process.exit(3);
if(process.env.LIVE_TEST_MODE==='claim') { console.log('Read the file successfully'); process.exit(0); }
if(process.env.LIVE_TEST_MODE==='slow') { setInterval(()=>{},1000); } else {
let command,args;
for(let i=0;i<argv.length;i++) {
 if(argv[i]==='-c') {const setting=argv[++i]; const n=setting.indexOf('=');const k=setting.slice(0,n),v=setting.slice(n+1);
 if(k.endsWith('.command')) command=JSON.parse(v); if(k.endsWith('.args')) args=JSON.parse(v); }
}
const child=cp.spawn(command,args,{stdio:['pipe','pipe','ignore']});
let pending='',sent=false;
const send=m=>child.stdin.write(JSON.stringify({jsonrpc:'2.0',...m})+'\n');
child.stdout.on('data', chunk=>{pending+=chunk.toString();let n;
 while((n=pending.indexOf('\n'))>=0){const m=JSON.parse(pending.slice(0,n));pending=pending.slice(n+1);
 if(m.id===1){send({method:'notifications/initialized'});send({id:2,method:'tools/list'});}
 if(m.id===2 && !sent){sent=true;const prompt=argv.at(-1);const path=prompt.split(' to read ')[1].split('. Do not use')[0];send({id:3,method:'tools/call',params:{name:'read_text_file',arguments:{path}}});}
 if(m.id===3){child.stdin.end();child.on('close',()=>process.exit(m.error?4:0));}
 }});
send({id:1,method:'initialize',params:{protocolVersion:'2025-11-25',capabilities:{},clientInfo:{name:'test-codex',version:'1'}}});
setTimeout(()=>{child.kill();process.exit(5)},8000).unref();
}
'''


def send(database, action, **fields):
    return execute(database, json.dumps({'action': action, **fields}).encode())


def wait_for(db, predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = live.status(db)
        if predicate(state):
            return state
        time.sleep(0.05)
    pytest.fail('Connection state did not settle')


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    db = tmp_path / 'app' / 'state.sqlite3'
    fixture = tmp_path / 'fixture.py'
    fixture.write_text(FIXTURE)
    def resources(selected):
        local = live.paths(selected)
        live.save_private(local['sample'], b'DriftGuard live integration check\n')
        live.save_private(local['profile'], json.dumps({'server_id': live.SERVER_ID,
            'argv': [sys.executable, str(fixture)], 'cwd': str(tmp_path),
            'protocol_version': LEGACY, 'timeout_seconds': 3}).encode())
    monkeypatch.setattr(live, '_resources', resources)
    yield db
    live.disconnect(db)
    wait_for(db, lambda s: not s['service_alive'])


def approve(db):
    state = live.status(db)
    return send(db, 'live_verify', expected_sha256=state['tool']['sha256'],
                expected_revision=state['tool']['revision'])


def adapter(db):
    command = tuple(live.engine_args('driftguard.live_client') + ['--connection', str(live.paths(db)['client'])])
    return StdioPeer(StdioConfig('adapter', command, cwd=str(db.parent), protocol_version=LEGACY, timeout_seconds=4))


def test_config_preserves_bytes_and_restores_exact_original(app):
    original = b'# user settings\nmodel = "chosen"\n[mcp_servers.other]\ncommand = "other"\n'
    live.save_private(live.codex_config(), original)
    live.install_config(app)
    installed = live.codex_config().read_bytes()
    assert installed.startswith(original)
    assert tomllib.loads(installed.decode())['mcp_servers'][live.SERVER_ID]['command']
    live.install_config(app)
    assert live.codex_config().read_bytes() == installed
    assert live.restore_config(app)
    assert live.codex_config().read_bytes() == original


@pytest.mark.parametrize('original', [b'invalid = [', b'[mcp_servers.driftguard-filesystem]\ncommand="mine"\n'])
def test_invalid_or_conflicting_config_is_never_overwritten(app, original):
    live.save_private(live.codex_config(), original)
    with pytest.raises(live.LiveError):
        live.install_config(app)
    assert live.codex_config().read_bytes() == original


def test_newer_settings_preserved(app):
    live.install_config(app)
    edited = live.codex_config().read_bytes() + b'\n# new user edit\n'
    live.save_private(live.codex_config(), edited)
    assert not live.restore_config(app)
    assert live.codex_config().read_bytes() == edited


def test_app_approves_current_version_and_downstream_reconnect_keeps_approval(app):
    assert send(app, 'live_connect')['ok']
    before = live.status(app)
    assert before['running'] and not before['verified'] and before['installed']
    assert not send(app, 'live_verify', expected_sha256='0' * 64, expected_revision=1)['ok']
    assert not send(app, 'live_run_codex')['ok']
    assert approve(app)['ok']
    for _ in range(2):
        peer = adapter(app)
        try:
            peer.initialize()
            assert [t['name'] for t in peer.request('tools/list')['tools']] == ['read_text_file']
            result = peer.request('tools/call', {'name': 'read_text_file', 'arguments': {'path': str(live.paths(app)['sample'])}})
            assert result['content'][0]['text'] == live.paths(app)['sample'].read_text()
        finally:
            peer.close()
    assert live.status(app)['verified']
    assert send(app, 'live_connect')['data']['tool']['sha256'] == before['tool']['sha256']


def test_mcp_data_token_cannot_approve_or_use_controller(app):
    live.connect(app)
    endpoint = live.read_private(live.paths(app)['client'])
    with socket.create_connection(('127.0.0.1', endpoint['port']), timeout=2) as peer:
        peer.sendall(json.dumps({'kind': 'control', 'token': endpoint['token']}).encode() + b'\n')
        peer.sendall(b'{"action":"verify"}\n')
        assert not peer.recv(4096)
    assert not live.status(app)['verified']


@pytest.mark.parametrize('field', ['command', 'path', 'db', 'prompt'])
def test_renderer_cannot_select_commands_files_or_prompts(app, field):
    assert not send(app, 'live_connect', **{field: 'arbitrary'})['ok']
    assert not send(app, 'live_run_codex', **{field: 'arbitrary'})['ok']
    assert not send(app, 'live_verify', expected_sha256='0' * 64, expected_revision=True)['ok']


def test_concurrent_setup_rejected(app):
    with live.operation_lock(live.paths(app)['root'] / 'operation.lock'):
        assert not send(app, 'live_connect')['ok']


def test_review_revocation_invalidates_verified_status(app):
    live.connect(app)
    assert approve(app)['ok']
    row = live.status(app)['tool']
    with GuardStore(app) as store:
        store.deny(live.SERVER_ID, 'read_text_file', expected_hash=row['sha256'], expected_revision=row['revision'])
    assert not live.status(app)['verified']
    assert not send(app, 'live_run_codex')['ok']


@pytest.mark.parametrize('mode,expected', [('mcp', 'complete'), ('claim', 'failed'), ('slow', 'cancelled')])
def test_codex_job_requires_actual_mcp_call_and_can_cancel(app, tmp_path, monkeypatch, mode, expected):
    if not shutil.which('node'):
        pytest.skip('Node is required for the authored Codex executable fixture')
    binary = tmp_path / 'bin'
    binary.mkdir()
    if os.name == 'nt':
        (binary / 'codex.cmd').write_text('@echo off\n')
        script = binary / 'node_modules/@openai/codex/bin/codex.js'
        script.parent.mkdir(parents=True)
    else:
        script = binary / 'codex'
    script.write_text(CODEX)
    script.chmod(0o700)
    monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ.get('PATH', ''))
    monkeypatch.setenv('LIVE_TEST_MODE', mode)
    live.connect(app)
    assert approve(app)['ok']
    assert send(app, 'live_run_codex')['ok']
    if mode == 'slow':
        assert send(app, 'live_cancel_codex')['ok']
    state = wait_for(app, lambda s: s['job']['stage'] != 'running')
    assert state['job']['stage'] == expected
    assert state['running'] and state['verified']


def test_official_filesystem_app_setup_and_real_codex_reconnect(tmp_path, monkeypatch):
    if not os.environ.get('DRIFTGUARD_TEST_FILESYSTEM'):
        pytest.skip('Opt-in official server installation test')
    from driftguard.harnesses import _CodexConfig, _CodexPeer
    db = tmp_path / 'app' / 'state.sqlite3'
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex-home'))
    original = b'# Existing user settings\n'
    live.save_private(live.codex_config(), original)
    try:
        assert send(db, 'live_connect')['ok']
        assert approve(db)['ok']
        executable = os.environ.get('DRIFTGUARD_TEST_CODEX')
        if executable:
            for _ in range(2):
                peer = _CodexPeer(_CodexConfig('codex-app', (executable, 'app-server'), cwd=str(tmp_path),
                    protocol_version=LEGACY, pass_env=('CODEX_HOME',), timeout_seconds=20))
                peer.collection_deadline = time.monotonic() + 30
                try:
                    peer.initialize()
                    rows = peer.request('mcpServerStatus/list', {'limit': 10, 'detail': 'toolsAndAuthOnly'})['data']
                    assert len(rows) == 1
                    assert rows[0]['name'] == live.SERVER_ID
                    assert 'read_text_file' in rows[0]['tools']
                finally:
                    peer.close()
                assert live.status(db)['verified']
    finally:
        live.disconnect(db)
        wait_for(db, lambda s: not s['service_alive'])
    assert live.codex_config().read_bytes() == original


def test_restart_requires_fresh_approval(app):
    live.connect(app)
    assert approve(app)['ok']
    live.control(app, 'stop')
    wait_for(app, lambda s: not s['service_alive'])
    live.connect(app)
    assert live.status(app)['tool']['status'] != 'approved'
    assert not live.status(app)['verified']
    assert approve(app)['ok']


def test_setup_failure_stops_new_gateway_and_keeps_settings(app):
    original = b'[mcp_servers.driftguard-filesystem]\ncommand="owned-by-user"\n'
    live.save_private(live.codex_config(), original)
    assert not send(app, 'live_connect')['ok']
    wait_for(app, lambda s: not s['service_alive'])
    assert live.codex_config().read_bytes() == original



def test_javascript_launchers_use_absolute_node_in_gui_environment(tmp_path, monkeypatch):
    script = tmp_path / 'codex.js'
    script.write_text('// Standard JS launcher')
    node = str(tmp_path / 'absolute-node')
    monkeypatch.setattr(live, '_program', lambda name: node if name == 'node' else str(script))
    assert live._node_command('codex') == [node, str(script.resolve())]
