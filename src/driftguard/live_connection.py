"""Fixed, app-owned Codex connection; no renderer-selected paths or commands."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

SERVER_ID = 'driftguard-filesystem'
PACKAGE = '@modelcontextprotocol/server-filesystem@2.0.1'
BEGIN = '# BEGIN DriftGuard managed connection\n'
END = '# END DriftGuard managed connection\n'
MAX_FRAME = 1024 * 1024


class LiveError(ValueError):
    """Safe message for the desktop interface."""


def paths(db: Path) -> dict[str, Path]:
    root = db.absolute().parent / 'live-connection'
    return {name: root / filename for name, filename in {
        'root': '.', 'client': 'client.json', 'control': 'control.json',
        'profile': 'source.json', 'manifest': 'codex-change.json',
        'backup': 'codex-before.toml', 'sample': 'files/check.txt',
        'server': 'dependencies/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js',
    }.items()}


def engine_args(module: str) -> list[str]:
    if getattr(sys, 'frozen', False):
        return [os.path.abspath(sys.executable), module.rsplit('.', 1)[1].replace('_', '-')]
    return [os.path.abspath(sys.executable), '-I', '-m', module]


def save_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.driftguard-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_private(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_size > 16384:
        raise LiveError('Local connection metadata is unavailable. Reconnect from the app.')
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise LiveError('Local connection metadata is invalid. Reconnect from the app.')
    return value


@contextmanager
def operation_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b'0')
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LiveError('Another connection operation is running. Wait for it to finish.') from None
        yield
    finally:
        os.close(descriptor)


def control(db: Path, action: str, **fields):
    try:
        endpoint = read_private(paths(db)['control'])
        port, token = endpoint['port'], endpoint['token']
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or len(token) != 64:
            raise ValueError
        with socket.create_connection(('127.0.0.1', port), timeout=35 if action == 'verify' else 3) as peer:
            peer.sendall(json.dumps({'kind': 'control', 'token': token}).encode() + b'\n')
            peer.sendall(json.dumps({'action': action, **fields}).encode() + b'\n')
            with peer.makefile('rb') as stream:
                raw = stream.readline(MAX_FRAME + 1)
            if len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
                raise ValueError
            result = json.loads(raw)
            if not result.get('ok'):
                raise LiveError(result.get('message', 'Connection operation failed. Reconnect from the app.'))
            return result['data']
    except LiveError:
        raise
    except (OSError, KeyError, ValueError, TypeError):
        raise LiveError('The local gateway is unavailable. Connect again from the app.') from None


def codex_config() -> Path:
    return Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser().absolute() / 'config.toml'


def _read_config(path: Path) -> bytes:
    if path.is_symlink():
        raise LiveError('Codex configuration is a symbolic link. Choose a regular configuration file first.')
    if not path.exists():
        return b''
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise LiveError('Codex configuration is unavailable or too large.')
    data = path.read_bytes()
    try:
        tomllib.loads(data.decode('utf-8'))
    except (ValueError, UnicodeError):
        raise LiveError('Codex configuration contains invalid TOML. Repair it before connecting.') from None
    return data


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(db: Path) -> bytes:
    command, *arguments = engine_args('driftguard.live_client')
    arguments += ['--connection', str(paths(db)['client'])]
    return (BEGIN + f'[mcp_servers."{SERVER_ID}"]\ncommand = ' + json.dumps(command, ensure_ascii=False) +
            '\nargs = ' + json.dumps(arguments, ensure_ascii=False) + '\nstartup_timeout_sec = 90\n' + END).encode()


def install_config(db: Path) -> None:
    target, local = codex_config(), paths(db)
    with operation_lock(target.parent / 'driftguard-config.lock'):
        before = _read_config(target)
        if local['manifest'].exists():
            saved = read_private(local['manifest'])
            if saved.get('target') == str(target) and saved.get('installed') == _digest(before):
                return
            raise LiveError('Codex settings changed after setup. Disconnect first; your edits will be preserved.')
        parsed = tomllib.loads(before.decode('utf-8'))
        servers = parsed.get('mcp_servers', {})
        if not isinstance(servers, dict) or SERVER_ID in servers or BEGIN.encode() in before:
            raise LiveError('Codex already has a conflicting DriftGuard entry. Resolve it before connecting.')
        merged = before + (b'\n' if before and not before.endswith(b'\n') else b'') + b'\n' + _entry(db)
        tomllib.loads(merged.decode('utf-8'))
        save_private(local['backup'], before)
        manifest = {'target': str(target), 'existed': target.exists(),
                    'before': _digest(before), 'installed': _digest(merged)}
        save_private(local['manifest'], json.dumps(manifest).encode())
        if _read_config(target) != before:
            local['manifest'].unlink()
            raise LiveError('Codex settings changed during setup. Your edits were preserved; retry.')
        save_private(target, merged)


def restore_config(db: Path) -> bool:
    local, target = paths(db), codex_config()
    if not local['manifest'].exists():
        return True
    with operation_lock(target.parent / 'driftguard-config.lock'):
        saved = read_private(local['manifest'])
        if saved.get('target') != str(target):
            raise LiveError('Codex home changed. Restore the original Codex home before disconnecting.')
        before = local['backup'].read_bytes()
        restored = saved.get('installed') == _digest(_read_config(target)) and saved.get('before') == _digest(before)
        if restored:
            if saved.get('existed'):
                save_private(target, before)
            else:
                target.unlink(missing_ok=True)
        local['manifest'].unlink()
        return restored


def _program(name: str) -> str | None:
    search = os.pathsep.join([os.environ.get('PATH', os.defpath), '/opt/homebrew/bin', '/usr/local/bin', str(Path.home() / '.local/bin')])
    found = shutil.which(name, path=search)
    return os.path.abspath(found) if found else None


def _node_command(name: str) -> list[str]:
    program = _program(name)
    if program is None:
        raise LiveError(f'Install {name} and reopen DriftGuard to continue.')
    if Path(program).suffix.lower() in {'.cmd', '.bat', '.ps1'}:
        relative = 'node_modules/npm/bin/npm-cli.js' if name == 'npm' else 'node_modules/@openai/codex/bin/codex.js'
        script = Path(program).parent / relative
        node = _program('node')
        if not script.is_file() or not node:
            raise LiveError(f'The installed {name} launcher is unavailable. Reinstall its standard Node package.')
        return [node, str(script)]
    # npm's macOS/Linux launchers are often JS symlinks. A GUI app's PATH
    # may omit Homebrew, so invoke the selected Node executable explicitly.
    resolved = Path(program).resolve()
    if resolved.suffix.lower() == '.js':
        node = _program('node')
        if not node:
            raise LiveError('Install Node.js 24 or newer and reopen DriftGuard.')
        return [node, str(resolved)]
    return [program]


def _resources(db: Path) -> None:
    local = paths(db)
    node = _program('node')
    if not node:
        raise LiveError('Install Node.js 24 or newer and reopen DriftGuard.')
    try:
        version = subprocess.run([node, '--version'], capture_output=True, timeout=5, check=True)
        if int(version.stdout.decode().strip().lstrip('v').split('.')[0]) < 24:
            raise LiveError('This connection requires Node.js 24 or newer.')
        if not local['server'].is_file():
            install = _node_command('npm') + ['install', '--prefix', str(local['root'] / 'dependencies'),
                '--ignore-scripts', '--save-exact', '--no-audit', '--no-fund', PACKAGE]
            subprocess.run(install, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, check=True, timeout=120)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise LiveError('The local Filesystem dependency could not be prepared. Check Node.js 24 and network access.') from None
    local['sample'].parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not local['sample'].exists():
        save_private(local['sample'], b'DriftGuard live integration check\n')
    profile = {'server_id': SERVER_ID, 'argv': [node, str(local['server']), str(local['sample'].parent)],
               'cwd': str(local['sample'].parent), 'protocol_version': '2025-11-25', 'timeout_seconds': 20}
    save_private(local['profile'], json.dumps(profile).encode())


def status(db: Path) -> dict:
    try:
        result = control(db, 'status')
        result['service_alive'] = True
    except LiveError:
        result = {'running': False, 'service_alive': False, 'clients': 0, 'verified': False,
                  'tool': None, 'job': {'stage': 'idle'}}
    return {**result, 'installed': paths(db)['manifest'].exists(),
            'codex_available': _program('codex') is not None, 'config_path': str(codex_config()),
            'sample_path': str(paths(db)['sample'])}


def connect(db: Path) -> dict:
    with operation_lock(paths(db)['root'] / 'operation.lock'):
        current = status(db)
        started = False
        if not current['running']:
            if current['service_alive']:
                control(db, 'stop')
                time.sleep(0.3)
            _resources(db)
            local = paths(db)
            local['control'].unlink(missing_ok=True)
            env = {**os.environ, 'CODEX_HOME': str(codex_config().parent)}
            options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen(engine_args('driftguard.live_service') + ['--db', str(db.absolute())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **options)
            started = True
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if status(db)['running']:
                    break
                time.sleep(0.1)
            else:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                raise LiveError('The local gateway did not start. Check the engine and reconnect.')
        try:
            install_config(db)
        except Exception:
            if started:
                control(db, 'stop')
            raise
        return status(db)


def disconnect(db: Path) -> dict:
    with operation_lock(paths(db)['root'] / 'operation.lock'):
        try:
            control(db, 'stop')
        except LiveError:
            pass
        restored = restore_config(db)
        return {**status(db), 'settings_restored': restored,
                'message': 'Disconnected. Previous Codex settings restored.' if restored else
                'Disconnected. Newer Codex edits were preserved; its DriftGuard entry remains in the file.'}


def run_codex(db: Path) -> dict:
    return control(db, 'run_codex')


def cancel_codex(db: Path) -> dict:
    return control(db, 'cancel_codex')


def _run_codex_task(db: Path, cancelled: threading.Event) -> dict:
    tag = secrets.token_hex(16)
    command, *arguments = engine_args('driftguard.live_client')
    arguments += ['--connection', str(paths(db)['client']), '--trace-tag', tag]
    prompt = ('Use only the MCP tool mcp__driftguard-filesystem__read_text_file to read ' +
              str(paths(db)['sample']) + '. Do not use shell commands or built-in file tools. Report its text.')
    argv = _node_command('codex') + ['exec', '--ignore-user-config', '--ephemeral', '--json',
        '--skip-git-repo-check', '--sandbox', 'read-only', '-c', 'approval_policy="never"',
        '-c', f'mcp_servers.{SERVER_ID}.command=' + json.dumps(command, ensure_ascii=False),
        '-c', f'mcp_servers.{SERVER_ID}.args=' + json.dumps(arguments, ensure_ascii=False),
        '-c', f'mcp_servers.{SERVER_ID}.startup_timeout_sec=90', prompt]
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.DEVNULL, cwd=paths(db)['sample'].parent, **options)
        except OSError:
            raise LiveError('Codex could not start. Install a current Codex CLI and sign in normally.') from None
        try:
            deadline = time.monotonic() + 90
            while process.poll() is None:
                if cancelled.wait(0.1):
                    raise LiveError('Codex test cancelled. The gateway is still available.')
                if time.monotonic() > deadline or os.fstat(output.fileno()).st_size > 4 * 1024 * 1024:
                    raise LiveError('Codex test reached its time or output limit. The gateway is still available.')
            if cancelled.is_set():
                raise LiveError('Codex test cancelled. The gateway is still available.')
            proof = control(db, 'probe_result', tag=tag)
            if process.returncode != 0 or not proof['completed_reads']:
                raise LiveError('No successful MCP sample read was observed. Check Codex CLI version and sign-in, then retry.')
            return {'stage': 'complete', 'message': 'Codex completed an actual MCP sample read.', 'verified': True}
        finally:
            if process.poll() is None:
                _stop_task(process)


def _stop_task(process: subprocess.Popen) -> None:
    if sys.platform == 'win32':
        # Terminating the npm Node launcher alone leaves its native Codex child
        # running. Target only the process tree created for this app-owned task.
        taskkill = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe')
        try:
            subprocess.run([taskkill, '/PID', str(process.pid), '/T', '/F'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
