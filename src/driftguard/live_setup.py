"""Prepare a local Filesystem MCP connection without editing harness settings."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def desktop_state() -> Path:
    if sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    elif os.name == 'nt':
        base = Path(os.environ.get('APPDATA', str(Path.home() / 'AppData' / 'Roaming')))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share')))
    return base / 'io.driftguard.desktop' / 'guard.sqlite3'


def _save_new(path: Path, text: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or not path.is_file() or path.read_text(encoding='utf-8') != text:
            raise ValueError(f'{path.name} already exists with different contents; choose another --output directory.') from None
    else:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)


def prepare(server: Path, output: Path, state: Path) -> dict[str, Path]:
    state = state.expanduser().absolute()
    if not server.is_file():
        raise ValueError('Install the test server first: npm install --prefix live-validation --ignore-scripts --save-exact @modelcontextprotocol/server-filesystem@2.0.1')
    node = shutil.which('node')
    if node is None:
        raise ValueError('Install Node.js 24 or newer, then retry.')
    version = subprocess.run([node, '--version'], capture_output=True, text=True, check=True, timeout=5)
    if int(version.stdout.strip().removeprefix('v').split('.')[0]) < 24:
        raise ValueError('Filesystem MCP 2.0.1 requires Node.js 24 or newer.')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    allowed = output / 'files'
    allowed.mkdir(exist_ok=True, mode=0o700)
    sample = allowed / 'check.txt'
    _save_new(sample, 'DriftGuard live integration check\n')
    profile = output / 'filesystem-source.json'
    _save_new(profile, json.dumps({'server_id': 'live-filesystem',
        'argv': [node, str(server.resolve()), str(allowed)], 'cwd': str(allowed),
        'protocol_version': '2025-11-25', 'timeout_seconds': 30}, indent=2) + '\n')
    # Keep the venv executable's lexical path; resolving its symlink loses packages.
    command = os.path.abspath(sys.executable)
    args = ['-I', '-m', 'driftguard.gateway_cli', 'serve', '--config', str(profile),
            '--state', str(state)]
    codex = output / 'codex-gateway.toml'
    _save_new(codex, '[mcp_servers."live-filesystem"]\ncommand = ' + json.dumps(command, ensure_ascii=False) +
              '\nargs = ' + json.dumps(args, ensure_ascii=False) + '\nstartup_timeout_sec = 90\n')
    claude = output / 'claude-gateway.json'
    _save_new(claude, json.dumps({'mcpServers': {'live-filesystem': {
        'command': command, 'args': args}}}, indent=2) + '\n')
    return {'codex': codex, 'claude': claude, 'profile': profile, 'sample': sample, 'state': state}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', type=Path, default=Path('live-validation/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js'))
    parser.add_argument('--output', type=Path, default=Path('live-demo'))
    parser.add_argument('--state', type=Path, default=desktop_state())
    args = parser.parse_args(argv)
    try:
        paths = prepare(args.server, args.output, args.state)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print('Prepared one local connection. Harness configuration was not changed.')
    print(f'Codex: merge {paths["codex"]} into ~/.codex/config.toml')
    print(f'Claude Code: merge {paths["claude"]} into your project .mcp.json')
    print(f'Shared desktop state: {paths["state"]}')
    print('Start the client and keep that session open. Refresh DriftGuard and approve')
    print('read_text_file under live-filesystem (not an import: or harness: source).')
    print(f'Then ask the client to use live-filesystem to read {paths["sample"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
