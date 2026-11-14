"""Install one app-owned stdio connection in supported coding clients."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .live_connection import (
    SERVER_ID,
    LiveError,
    _digest,
    _program,
    engine_args,
    operation_lock,
    paths,
    read_private,
    save_private,
)

CLIENTS = {
    'codex': ('Codex', ('codex',), ('Codex',)),
    'claude': ('Claude Code', ('claude',), ()),
    'cursor': ('Cursor', ('cursor', 'cursor-agent'), ('Cursor',)),
    'antigravity': ('Antigravity', ('agy', 'antigravity'), ('Antigravity',)),
    'gemini': ('Gemini CLI', ('gemini',), ()),
    'opencode': ('OpenCode', ('opencode',), ('OpenCode',)),
    'vscode': ('VS Code / Copilot', ('code', 'code-insiders'), ('Visual Studio Code',)),
}
_COMMENTS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
_COMMAS = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[}\]])')
_DECODER = json.JSONDecoder()


def _home(variable: str) -> Path:
    return Path(os.environ.get(variable) or Path.home()).expanduser().absolute()


def config_path(harness: str) -> Path:
    home = Path.home()
    if harness == 'claude':
        return _home('CLAUDE_CONFIG_DIR') / '.claude.json'
    if harness == 'cursor':
        return home / '.cursor/mcp.json'
    if harness == 'antigravity':
        return home / '.gemini/config/mcp_config.json'
    if harness == 'gemini':
        return _home('GEMINI_CLI_HOME') / '.gemini/settings.json'
    if harness == 'opencode':
        root = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'opencode'
        return root / ('opencode.json' if (root / 'opencode.json').exists()
                       and not (root / 'opencode.jsonc').exists() else 'opencode.jsonc')
    if sys.platform == 'darwin':
        base = home / 'Library/Application Support'
    elif os.name == 'nt':
        base = Path(os.environ.get('APPDATA') or home / 'AppData/Roaming')
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    editor = 'Code - Insiders' if not _program('code') and _program('code-insiders') else 'Code'
    return base / editor / 'User/mcp.json'


def detected(harness: str) -> bool:
    _, programs, apps = CLIENTS[harness]
    if any(_program(program) for program in programs):
        return True
    if sys.platform == 'darwin':
        return any((base / (app + '.app')).is_dir()
                   for base in (Path('/Applications'), Path.home() / 'Applications') for app in apps)
    if os.name == 'nt':
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
        program_files = Path(os.environ.get('ProgramFiles') or 'C:/Program Files')
        binary = {'Codex': 'Codex', 'Cursor': 'Cursor', 'Antigravity': 'Antigravity',
                  'OpenCode': 'OpenCode', 'Visual Studio Code': 'Code'}
        return any((base / app / (binary[app] + '.exe')).is_file()
                   for base in (local / 'Programs', program_files) for app in apps)
    return False


def manifest_path(db: Path, harness: str) -> Path:
    return paths(db)['manifest'] if harness == 'codex' else paths(db)['root'] / f'{harness}-change.json'


def _read(target: Path) -> bytes:
    if target.is_symlink() or (target.exists() and
            (not target.is_file() or target.stat().st_size > 1024 * 1024)):
        raise LiveError('Client settings must be a regular file no larger than 1 MiB.')
    return target.read_bytes() if target.exists() else b''


def _mask(source: str) -> str:
    def blank_comment(match: re.Match[str]) -> str:
        value = match[0]
        return value if value.startswith('"') else re.sub(r'[^\r\n]', ' ', value)

    return _COMMAS.sub(lambda match: ' ' if match[0] == ',' else match[0],
                       _COMMENTS.sub(blank_comment, source))


def _members(source: str, start: int) -> dict[str, tuple[int, int, int]]:
    """Return key start and value bounds for immediate members."""
    result = {}
    index = start + 1
    while True:
        index += len(source[index:]) - len(source[index:].lstrip())
        if source[index] == '}':
            return result
        name, name_end = _DECODER.raw_decode(source, index)
        tail = source[name_end:].lstrip()
        value_start = len(source) - len(tail[1:].lstrip())
        _, value_end = _DECODER.raw_decode(source, value_start)
        if name in result:
            raise LiveError('Client settings contain duplicate keys.')
        result[name] = (index, value_start, value_end)
        index = value_end
        index += len(source[index:]) - len(source[index:].lstrip())
        if source[index] == ',':
            index += 1


def _edit(before: bytes, harness: str, db: Path) -> tuple[bytes, str, tuple[str, ...], dict]:
    source = before.decode('utf-8-sig') or '{}\n'
    jsonc = harness in {'opencode', 'vscode'}
    parsed = _mask(source) if jsonc else source
    if not isinstance(json.loads(parsed), dict):
        raise LiveError('Client settings must contain a JSON object.')
    command, *arguments = engine_args('driftguard.live_client')
    arguments += ['--connection', str(paths(db)['client']), '--trace-tag', f'harness:{harness}']
    entry = {'command': command, 'args': arguments}
    sections = ('mcpServers',)
    if harness == 'opencode':
        sections = ('mcp', 'servers')
        entry = {'type': 'local', 'command': [command, *arguments]}
        current = json.loads(parsed).get('mcp', {})
        if isinstance(current, dict) and current and 'servers' not in current:
            # Existing OpenCode installations may use the earlier flat map.
            sections = ('mcp',)
    if harness == 'vscode':
        sections = ('servers',)
    if harness in {'claude', 'vscode'}:
        entry['type'] = 'stdio'
    start = len(parsed) - len(parsed.lstrip())
    names = (*sections, SERVER_ID)
    for position, name in enumerate(names):
        if parsed[start] != '{':
            raise LiveError('The client MCP settings are not a JSON object.')
        members = _members(parsed, start)
        if name in members:
            if name == SERVER_ID:
                raise LiveError('This client already has a conflicting DriftGuard connection.')
            start = members[name][1]
            continue
        value = entry
        for nested in reversed(names[position + 1:]):
            value = {nested: value}
        index = list(members.values())[-1][2] if members else start + 1
        insertion = (',' if members else '') + '\n  ' + json.dumps(name) + ': ' + json.dumps(value)
        result = source[:index] + insertion + source[index:]
        json.loads(_mask(result) if jsonc else result)
        bom = b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b''
        return bom + result.encode(), insertion, names, entry
    raise AssertionError('Expected a new managed entry')


def install(db: Path, harness: str) -> None:
    target = config_path(harness)
    manifest = manifest_path(db, harness)
    backup = manifest.with_suffix('.backup')
    with operation_lock(target.parent / 'driftguard-config.lock'):
        before = _read(target)
        if manifest.exists():
            saved = read_private(manifest)
            if saved['target'] == str(target):
                try:
                    without_entry = _remove_entry(before, harness, saved['names'], saved['entry'])
                except (ValueError, RecursionError):
                    without_entry = None
                if without_entry is not None and without_entry != before:
                    return
            raise LiveError('Client settings changed. Disconnect to reconcile the managed entry.')
        try:
            merged, insertion, names, entry = _edit(before, harness, db)
        except (ValueError, UnicodeError, RecursionError) as error:
            if isinstance(error, LiveError):
                raise
            raise LiveError('Client settings could not be parsed. Existing settings were preserved.') from None
        existed = target.exists()
        save_private(backup, before)
        save_private(manifest, json.dumps({'target': str(target), 'existed': existed,
            'before': _digest(before), 'installed': _digest(merged), 'insertion': insertion,
            'names': names, 'entry': entry}).encode())
        try:
            if _read(target) != before or target.exists() != existed:
                raise LiveError('Client settings changed during setup. Try connecting again.')
            save_private(target, merged)
        except (OSError, LiveError):
            manifest.unlink()
            backup.unlink()
            raise


def _remove_entry(current: bytes, harness: str, names: list[str], entry: dict) -> bytes | None:
    source = current.decode('utf-8-sig')
    jsonc = harness in {'vscode', 'opencode'}
    parsed = _mask(source) if jsonc else source
    json.loads(parsed)
    start = len(parsed) - len(parsed.lstrip())
    for name in names[:-1]:
        if parsed[start] != '{':
            return None
        members = _members(parsed, start)
        if name not in members:
            return current
        start = members[name][1]
    if parsed[start] != '{':
        return None
    members = _members(parsed, start)
    if SERVER_ID not in members:
        return current
    key_start, value_start, end = members[SERVER_ID]
    if json.loads(parsed[value_start:end]) != entry:
        return None
    after = end + len(parsed[end:]) - len(parsed[end:].lstrip())
    comma = None
    if source[after] == ',':
        comma = after
    else:
        left = parsed[:key_start].rstrip()
        if left.endswith(','):
            comma = len(left) - 1
    if comma is not None and comma < key_start:
        result = source[:comma] + source[comma + 1:key_start] + source[end:]
    elif comma is not None:
        result = source[:key_start] + source[end:comma] + source[comma + 1:]
    else:
        result = source[:key_start] + source[end:]
    json.loads(_mask(result) if jsonc else result)
    bom = b'\xef\xbb\xbf' if current.startswith(b'\xef\xbb\xbf') else b''
    return bom + result.encode()


def restore(db: Path, harness: str) -> bool:
    manifest = manifest_path(db, harness)
    if not manifest.exists():
        return True
    target = config_path(harness)
    backup = manifest.with_suffix('.backup')
    with operation_lock(target.parent / 'driftguard-config.lock'):
        saved = read_private(manifest)
        if saved['target'] != str(target):
            raise LiveError('The client settings location changed. Restore that location first.')
        current = _read(target)
        original = _read(backup)
        if _digest(original) != saved['before']:
            raise LiveError('The settings backup changed. Reconnect after checking the original file.')
        if _digest(current) == saved['installed']:
            if _read(target) != current:
                return False
            if saved['existed']:
                save_private(target, original)
            else:
                target.unlink(missing_ok=True)
        elif current and current != original:
            insertion = saved['insertion'].encode()
            try:
                cleaned = (current.replace(insertion, b'', 1) if current.count(insertion) == 1
                           else _remove_entry(current, harness, saved['names'], saved['entry']))
                if cleaned is None:
                    return False
                source = cleaned.decode('utf-8-sig')
                json.loads(_mask(source) if harness in {'vscode', 'opencode'} else source)
            except (ValueError, RecursionError):
                return False
            if _read(target) != current:
                return False
            save_private(target, cleaned)
        manifest.unlink()
        backup.unlink()
    return True
