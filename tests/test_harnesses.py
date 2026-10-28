"""Harness integration contracts, using real child processes and disposable homes."""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from driftguard import harnesses
from driftguard.desktop_bridge import execute
from driftguard.gateway import GuardStore
from driftguard.harnesses import HarnessError, fetch, scan

FIXTURE = r'''
import json, os, pathlib, sys, time
mode = sys.argv[1]
trace = pathlib.Path(os.environ['TEST_TRACE'])
for line in sys.stdin:
    msg = json.loads(line)
    with trace.open('a') as log:
        log.write(json.dumps({**msg, '_pid': os.getpid()}) + '\n')
    if 'id' not in msg:
        continue
    method = msg['method']
    if method == 'initialize':
        result = {'userAgent': 'fixture'} if mode.startswith('codex') else {
            'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
            'serverInfo': {'name': 'fixture', 'version': '1.0'}}
    elif method == 'tools/list':
        if mode == 'hang': time.sleep(10)
        name = 'page_two' if msg.get('params', {}).get('cursor') else 'page_one'
        tool = {'name': name, 'description': os.environ.get('TEST_DESCRIPTION', 'Read local records'),
                'inputSchema': {'type': 'object', 'properties': {'id': {'type': 'string'}}}}
        result = {'tools': [tool]}
        if mode == 'echo': tool['description'] = os.environ['PRIVATE_TOKEN']
        if mode == 'bad': tool['inputSchema'] = False
        if mode == 'edit':
            path = pathlib.Path(os.environ['CONFIG_PATH'])
            path.write_text(path.read_text() + ' ')
        if mode == 'loop' or name == 'page_one': result['nextCursor'] = 'page2'
    elif method == 'mcpServerStatus/list':
        assert 'jsonrpc' not in msg, 'Codex is not MCP'
        tool = {'name': 'read', 'description': 'Read through Codex', 'inputSchema': {'type': 'object'}}
        cursor = msg.get('params', {}).get('cursor')
        if mode == 'codex-timeout' and cursor:
            time.sleep(2)
        result = {'data': [{'name': 'second' if cursor else 'first', 'tools': {'read': tool},
                            'authStatus': 'notLoggedIn' if mode == 'codex-auth' else 'loggedIn'}],
                  'nextCursor': None if cursor else 'next'}
        if mode == 'codex-auth': result['data'][0]['tools'] = {}
        if mode == 'codex-error':
            print(json.dumps({'id': msg['id'], 'error': {'code': -32601, 'message': 'PRIVATE_ERROR_MUST_NOT_LEAK'}}), flush=True)
            continue
        if mode == 'codex-partial' and not cursor:
            result['data'][0]['tools'] = {}
            result['data'][0]['toolsError'] = 'PRIVATE_SERVER_ERROR'
        if mode == 'codex-notifications':
            for index in range(80):
                print(json.dumps({'method': 'startup/updated', 'params': {'index': index}}), flush=True)
        if mode == 'codex-bad': result['data'][0]['tools'] = {'wrong_name': tool}
    else:
        raise RuntimeError('Discovery must never call tools or start a turn')
    output = {'id': msg['id'], 'result': result}
    if mode == 'codex-header': output['jsonrpc'] = '2.0'
    if not mode.startswith('codex'): output['jsonrpc'] = '2.0'
    print(json.dumps(output), flush=True)
'''


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    project = tmp_path / 'project'
    home.mkdir(); project.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.delenv('CODEX_HOME', raising=False)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    # Do not discover installed user harnesses or launch their configured servers.
    actual_which = shutil.which
    monkeypatch.setattr(harnesses.shutil, 'which', lambda name, **kwargs:
                        None if name in {'codex', 'claude'} else actual_which(name, **kwargs))
    script = tmp_path / 'fixture.py'
    script.write_text(FIXTURE)
    return home, project, script, tmp_path / 'trace.jsonl'


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def configured(workspace, mode='pages', env=None):
    home, project, script, trace = workspace
    path = home / '.claude.json'
    write_json(path, {'mcpServers': {'notes': {
        'command': sys.executable, 'args': [str(script), mode], 'env': {'TEST_TRACE': str(trace), **(env or {})},
    }}})
    return scan(str(project))['sources'][0]


def collect(store, source, project):
    return fetch(store, source['source_id'], source['config_digest'], str(project))


def test_scan_is_read_only_and_never_launches_a_configured_command(workspace):
    _, project, _, trace = workspace
    item = configured(workspace, env={'PRIVATE_TOKEN': 'never-export-this-token'})
    assert item['ready'] and item['transport'] == 'stdio'
    assert 'never-export-this-token' not in json.dumps(scan(str(project)))
    assert not trace.exists()


def test_real_stdio_discovery_pagination_review_history_and_refresh(workspace, tmp_path):
    home, project, _, trace = workspace
    source = configured(workspace)
    original = (home / '.claude.json').read_bytes()
    with GuardStore(tmp_path / 'state.db') as store:
        result = collect(store, source, project)
        assert result['tools'] == 2
        records = store.list_tools()
        assert {record['tool_name'] for record in records} == {'page_one', 'page_two'}
        assert all(record['status'] == 'pending' and record['server_id'].startswith('harness:') for record in records)
        assert store.gateway_health() == []
        record = records[0]
        store.approve(record['server_id'], record['tool_name'], expected_hash=record['sha256'],
                      expected_revision=record['revision'])
        collect(store, source, project)
        assert store.get_tool(record['server_id'], record['tool_name'])['status'] == 'approved'
        assert len(store.history(record['server_id'], record['tool_name'])) == 1
    messages = [json.loads(line) for line in trace.read_text().splitlines()]
    assert {message['method'] for message in messages} == {'initialize', 'notifications/initialized', 'tools/list'}
    assert (home / '.claude.json').read_bytes() == original


def test_scope_precedence_env_expansion_and_disabled_entries(workspace, monkeypatch):
    home, project, _, _ = workspace
    monkeypatch.setenv('TEST_EXECUTABLE', sys.executable)
    write_json(home / '.claude.json', {'mcpServers': {'same': {'command': 'missing-user'}},
        'projects': {str(project): {'mcpServers': {'same': {'command': '${TEST_EXECUTABLE}'}},
                                   'disabledMcpServers': ['disabled']}}})
    write_json(project / '.mcp.json', {'mcpServers': {
        'same': {'command': 'missing-project'}, 'disabled': {'command': sys.executable},
        'missing-var': {'command': '${NOT_SET_DRIFTGUARD_TEST}'},
        'default-var': {'command': '${NOT_SET_DRIFTGUARD_TEST:-' + sys.executable + '}'},
    }})
    rows = {row['name']: row for row in scan(str(project))['sources']}
    assert rows['same']['scope'] == 'local' and rows['same']['ready']
    assert not rows['disabled']['ready'] and not rows['missing-var']['ready']
    assert rows['default-var']['ready']


def test_codex_toml_project_override_and_custom_config_home(workspace, monkeypatch):
    home, project, _, _ = workspace
    monkeypatch.setenv('CODEX_HOME', str(home / 'custom-codex'))
    user = home / 'custom-codex/config.toml'
    user.parent.mkdir()
    user.write_text('[mcp_servers.notes]\ncommand="missing-user"\n')
    local = project / '.codex/config.toml'
    local.parent.mkdir()
    local.write_text('[mcp_servers.notes]\ncommand=' + json.dumps(sys.executable) + '\n')
    rows = scan(str(project))['sources']
    assert len(rows) == 1 and rows[0]['scope'] == 'project' and rows[0]['ready']
    local.write_text('[mcp_servers.notes]\ncommand=' + json.dumps(sys.executable) + '\nenabled=false\n')
    assert not scan(str(project))['sources'][0]['ready']


def test_installed_runtime_discovery_uses_current_commands_without_launch(workspace, monkeypatch):
    _, project, _, trace = workspace
    configured(workspace)
    underlying = harnesses.shutil.which
    monkeypatch.setattr(harnesses.shutil, 'which', lambda name, **kwargs:
                        sys.executable if name in {'codex', 'claude'} else underlying(name, **kwargs))
    sources, _ = harnesses._sources(project)
    runtime = {source.harness: source for source in sources if source.kind == 'runtime'}
    assert runtime['codex'].settings['args'] == ['app-server']
    assert runtime['claude-code'].settings['args'] == ['mcp', 'serve']
    result = scan(str(project))
    assert len(result['sources']) == 3 and all(item['ready'] for item in result['sources'])
    assert not trace.exists()


@pytest.mark.parametrize('mode', ['loop', 'bad', 'echo', 'edit'])
def test_failed_collection_never_saves_partial_catalog(workspace, tmp_path, mode):
    home, project, _, _ = workspace
    source = configured(workspace, mode, {'PRIVATE_TOKEN': 'private-token-123456',
                                        'CONFIG_PATH': str(home / '.claude.json')})
    with GuardStore(tmp_path / 'state.db') as store:
        with pytest.raises((HarnessError, ValueError)):
            collect(store, source, project)
        assert store.list_tools() == []
        assert store.list_servers() == []


def test_config_changed_since_scan_is_rejected_before_process_launch(workspace, tmp_path):
    home, project, _, trace = workspace
    source = configured(workspace)
    path = home / '.claude.json'
    path.write_text(path.read_text() + ' ')
    with GuardStore(tmp_path / 'state.db') as store, pytest.raises(HarnessError, match='Scan again|scan again'):
        collect(store, source, project)
    assert not trace.exists()


def test_collection_deadline_closes_real_child(workspace, tmp_path, monkeypatch):
    _, project, _, trace = workspace
    source = configured(workspace, 'hang')
    monkeypatch.setattr(harnesses, 'FETCH_SECONDS', 0.25)
    start = time.monotonic()
    with GuardStore(tmp_path / 'state.db') as store, pytest.raises(HarnessError):
        collect(store, source, project)
    assert time.monotonic() - start < 3
    assert trace.exists()
    if os.name == 'posix':
        pid = json.loads(trace.read_text().splitlines()[0])['_pid']
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_malformed_higher_priority_config_does_not_fall_back(workspace):
    _, project, _, _ = workspace
    configured(workspace)
    (project / '.mcp.json').write_text('{"mcpServers": {}, "mcpServers": {}}')
    result = scan(str(project))
    assert result['sources'] == [] and result['warnings']


def codex_runtime(workspace, monkeypatch, mode):
    _, project, script, trace = workspace
    sources, _ = harnesses._sources(project)
    assert not sources
    source = harnesses._Source('codex', 'Codex MCP catalog', 'runtime', Path(sys.executable),
        project, {'command': sys.executable, 'args': [str(script), mode], 'env': {'TEST_TRACE': str(trace)}}, 'fixture', 'runtime')
    monkeypatch.setattr(harnesses, '_sources', lambda project: ([source], []))
    return scan(str(project))['sources'][0]


def test_codex_app_server_real_jsonl_contract_and_separate_catalogs(workspace, tmp_path, monkeypatch):
    _, project, _, trace = workspace
    source = codex_runtime(workspace, monkeypatch, 'codex')
    assert source['transport'] == 'codex-app-server'
    with GuardStore(tmp_path / 'state.db') as store:
        result = collect(store, source, project)
        assert result['servers'] == result['tools'] == 2
        assert len(result['server_ids']) == 2
        assert {tool['tool_name'] for tool in store.list_tools()} == {'read'}
    messages = [json.loads(line) for line in trace.read_text().splitlines()]
    assert all('jsonrpc' not in message for message in messages)
    assert {message['method'] for message in messages} == {'initialize', 'initialized', 'mcpServerStatus/list'}


@pytest.mark.parametrize('mode', ['codex-auth', 'codex-bad'])
def test_codex_invalid_or_unauthenticated_catalog_not_saved(workspace, tmp_path, monkeypatch, mode):
    _, project, _, _ = workspace
    source = codex_runtime(workspace, monkeypatch, mode)
    with GuardStore(tmp_path / 'state.db') as store, pytest.raises(HarnessError):
        collect(store, source, project)


@pytest.mark.parametrize('mode', ['codex-header', 'codex-notifications'])
def test_codex_wire_compatibility_and_notification_bursts(workspace, tmp_path, monkeypatch, mode):
    _, project, _, _ = workspace
    source = codex_runtime(workspace, monkeypatch, mode)
    with GuardStore(tmp_path / 'state.db') as store:
        assert collect(store, source, project)['tools'] == 2


def test_codex_failed_server_does_not_erase_healthy_catalog(workspace, tmp_path, monkeypatch):
    _, project, _, _ = workspace
    source = codex_runtime(workspace, monkeypatch, 'codex-partial')
    with GuardStore(tmp_path / 'state.db') as store:
        result = collect(store, source, project)
        assert result['servers'] == result['tools'] == 1
        assert len(result['warnings']) == 1
        assert 'PRIVATE_SERVER_ERROR' not in json.dumps(result)
        assert len(store.list_servers()) == 1


def test_codex_keeps_complete_catalogs_when_a_later_server_times_out(workspace, tmp_path, monkeypatch):
    _, project, _, _ = workspace
    source = codex_runtime(workspace, monkeypatch, 'codex-timeout')
    monkeypatch.setattr(harnesses, 'FETCH_SECONDS', 0.3)
    with GuardStore(tmp_path / 'state.db') as store:
        result = collect(store, source, project)
        assert result['servers'] == result['tools'] == 1
        assert len(store.list_servers()) == 1
        assert any('timed out' in warning for warning in result['warnings'])


def test_codex_unsupported_method_has_actionable_nonsecret_error(workspace, tmp_path, monkeypatch):
    _, project, _, _ = workspace
    source = codex_runtime(workspace, monkeypatch, 'codex-error')
    with GuardStore(tmp_path / 'state.db') as store, pytest.raises(HarnessError) as caught:
        collect(store, source, project)
    assert 'does not support mcpServerStatus/list' in str(caught.value)
    assert 'PRIVATE_ERROR_MUST_NOT_LEAK' not in str(caught.value)


def test_bridge_discovery_rejects_arbitrary_commands_and_hides_secret_errors(workspace, tmp_path):
    _, project, _, _ = workspace
    source = configured(workspace, 'echo', {'PRIVATE_TOKEN': 'never-export-this-value'})
    db = tmp_path / 'state.db'
    result = execute(db, json.dumps({'action': 'harness_scan', 'project_dir': str(project)}).encode())
    assert result['ok'] and result['data']['sources'][0]['source_id'] == source['source_id']
    payload = {'action': 'harness_fetch', 'project_dir': str(project),
               'source_id': source['source_id'], 'config_digest': source['config_digest']}
    failure = execute(db, json.dumps(payload).encode())
    assert not failure['ok'] and failure['error']['code'] == 'harness_unavailable'
    assert 'never-export-this-value' not in json.dumps(failure)
    assert not execute(db, json.dumps({**payload, 'command': 'whoami'}).encode())['ok']


@pytest.mark.parametrize('entry', [
    {'type': 'sse', 'url': 'https://example.invalid/sse'},
    {'type': 'http', 'url': 'https://example.invalid/mcp', 'headersHelper': 'whoami'},
    {'type': 'http', 'url': 'https://example.invalid/mcp', 'headers': {'X-Api-Key': 'private-key'}},
    {'type': 'http', 'url': 'https://example.invalid/mcp?token=private-key'},
    {'type': 'http', 'url': 'http://127.0.0.1:9999/mcp'},
])
def test_unsupported_auth_and_transports_are_visible_without_execution(workspace, entry):
    home, project, _, trace = workspace
    write_json(home / '.claude.json', {'mcpServers': {'unsupported': entry}})
    result = scan(str(project))['sources'][0]
    assert not result['ready'] and result['issue']
    assert 'private-key' not in json.dumps(result)
    assert not trace.exists()


def test_direct_http_collection_reuses_bearer_and_never_invokes_tools(workspace, tmp_path, monkeypatch):
    from dataclasses import replace

    from test_gateway_http import server

    home, project, _, _ = workspace
    token = 'local-fixture-token-123456'
    write_json(home / '.claude.json', {'mcpServers': {'remote': {
        'type': 'http', 'url': 'https://fixture.invalid/mcp',
        'headers': {'Authorization': 'Bearer ' + token},
    }}})
    source = scan(str(project))['sources'][0]
    assert source['ready'] and token not in json.dumps(source)
    original_config = harnesses._config
    # The existing real loopback transport fixture uses HTTP. Only this test
    # replaces its endpoint; production config still rejects plaintext endpoints.
    with server() as (url, state):
        monkeypatch.setattr(harnesses, '_config', lambda item:
                            replace(original_config(item), url=url, allow_insecure_loopback=True))
        with GuardStore(tmp_path / 'state.db') as store:
            result = collect(store, source, project)
            assert result['tools'] == 1 and not store.gateway_health()
        assert state['calls'] == 0
        assert all(headers.get('Authorization') == 'Bearer ' + token for _, headers in state['requests'])


def test_special_config_file_is_rejected_without_blocking(workspace):
    if os.name != 'posix':
        pytest.skip('POSIX FIFO check')
    home, project, _, _ = workspace
    os.mkfifo(home / '.claude.json')
    start = time.monotonic()
    result = scan(str(project))
    assert result['warnings'] and not result['sources']
    assert time.monotonic() - start < 1


def test_real_codex_cli_catalog_and_targeted_discovery(workspace, tmp_path, monkeypatch):
    """Opt-in vendor-binary test, isolated from the user's Codex configuration."""
    executable = os.environ.get('DRIFTGUARD_TEST_CODEX')
    if not executable or not Path(executable).is_file():
        pytest.skip('Set DRIFTGUARD_TEST_CODEX to an installed Codex CLI for vendor integration')
    _, project, script, trace = workspace
    config_dir = tmp_path / 'codex-fixture'
    config_dir.mkdir()
    config = config_dir / 'config.toml'
    config.write_text(
        '[mcp_servers.fixture]\ncommand=' + json.dumps(sys.executable) +
        '\nargs=' + json.dumps([str(script), 'pages']) +
        '\n[mcp_servers.fixture.env]\nTEST_TRACE=' + json.dumps(str(trace)) +
        '\n[mcp_servers.unavailable]\ncommand=' + json.dumps(sys.executable) +
        '\nargs=["-c", "raise SystemExit(2)"]\n'
    )
    before = config.read_bytes()
    monkeypatch.setenv('CODEX_HOME', str(config_dir))
    underlying = harnesses.shutil.which
    monkeypatch.setattr(harnesses.shutil, 'which', lambda name, **kwargs:
                        executable if name == 'codex' else underlying(name, **kwargs))
    sources = scan(str(project))['sources']
    runtime = next(source for source in sources if source['kind'] == 'runtime')
    selected = next(source for source in sources if source['name'] == 'fixture')
    assert selected['transport'] == 'codex-app-server'
    with GuardStore(tmp_path / 'real-codex.db') as store:
        result = collect(store, runtime, project)
        assert result['tools'] == 2 and result['servers'] == 1 and result['warnings']
        targeted = collect(store, selected, project)
        assert targeted['tools'] == 2 and targeted['servers'] == 1
        assert not targeted['warnings']
    assert config.read_bytes() == before
    methods = {json.loads(line)['method'] for line in trace.read_text().splitlines()}
    assert methods <= {'initialize', 'notifications/initialized', 'tools/list'}


def test_codex_runtime_forwards_only_configured_credential_references(workspace, monkeypatch):
    home, project, _, _ = workspace
    config = home / '.codex/config.toml'
    config.parent.mkdir()
    config.write_text('[mcp_servers.remote]\nurl="https://fixture.invalid/mcp"\nbearer_token_env_var="FIXTURE_AUTH_TOKEN"\n')
    monkeypatch.setenv('FIXTURE_AUTH_TOKEN', 'private-configured-token')
    monkeypatch.setenv('UNRELATED_PRIVATE_TOKEN', 'must-not-forward')
    underlying = harnesses.shutil.which
    monkeypatch.setattr(harnesses.shutil, 'which', lambda name, **kwargs:
                        sys.executable if name == 'codex' else underlying(name, **kwargs))
    sources, _ = harnesses._sources(project)
    runtime = next(source for source in sources if source.kind == 'runtime')
    environment = harnesses._config(runtime).environment()
    assert environment['FIXTURE_AUTH_TOKEN'] == 'private-configured-token'
    assert 'UNRELATED_PRIVATE_TOKEN' not in environment
    assert 'private-configured-token' not in json.dumps(scan(str(project)))
