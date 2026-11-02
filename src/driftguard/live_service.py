"""App-owned authenticated loopback gateway shared by reconnecting MCP clients."""
from __future__ import annotations

import argparse
import hmac
import json
import secrets
import socket
import socketserver
import sqlite3
import subprocess
import threading
from pathlib import Path

from .gateway import GateError, GuardStore
from .gateway_transport import (
    DownstreamSession,
    ProtectedGateway,
    StdioConfig,
    TransportError,
    decode_message,
)
from .live_connection import MAX_FRAME, SERVER_ID, LiveError, _run_codex_task, paths, save_private


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate field')
        result[name] = value
    return result


class Service(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, db: Path):
        self.db = db
        self.local = paths(db)
        self.store = GuardStore(db)
        self.reader = GuardStore(db)
        self.guard = None
        try:
            self.guard = ProtectedGateway(StdioConfig.from_file(self.local['profile']), self.store)
            super().__init__(('127.0.0.1', 0), Handler)
        except Exception:
            if self.guard:
                self.guard.close()
            self.reader.close()
            self.store.close()
            raise
        self.token, self.control_token = secrets.token_hex(32), secrets.token_hex(32)
        self.state_lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(16)
        self.clients: set[Handler] = set()
        self.calls: dict[str, int] = {}
        self.verified_version = None
        self.job = {'stage': 'idle'}
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.stopping = threading.Event()
        self.initial_token = self.reader.catalog_state_token(SERVER_ID)
        self.notifier = threading.Thread(target=self.notify, daemon=True)
        self.notifier.start()

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # The local app reports safe status; raw protocol/auth data is never logged.
        pass

    def status(self):
        row = self.reader.get_tool(SERVER_ID, 'read_text_file')
        version = (row['sha256'], row['revision'])
        with self.state_lock:
            return {'running': not self.guard._closed, 'clients': len(self.clients),
                    'verified': row['status'] == 'approved' and self.verified_version == version,
                    'tool': {key: row[key] for key in ('sha256', 'revision', 'status', 'definition')}, 'job': dict(self.job)}

    def controller(self, request):
        action = request.get('action')
        allowed = {'verify': {'action', 'expected_sha256', 'expected_revision'},
                   'probe_result': {'action', 'tag'}}.get(action, {'action'})
        if set(request) != allowed:
            raise LiveError('Invalid connection operation.')
        if action == 'status':
            return self.status()
        if action == 'stop':
            self.cancel.set()
            threading.Thread(target=self.shutdown, daemon=True).start()
            return {'stopping': True}
        if action == 'verify':
            digest, revision = request['expected_sha256'], request['expected_revision']
            if not isinstance(digest, str) or type(revision) is not int or revision < 1:
                raise LiveError('Reload the current tool version before approving.')
            self.guard.refresh_catalog()
            row = self.store.get_tool(SERVER_ID, 'read_text_file')
            if row['sha256'] != digest or row['revision'] != revision:
                raise LiveError('The tool changed. Reload and review its current version.')
            if row['status'] != 'approved':
                self.store.approve(SERVER_ID, 'read_text_file', expected_hash=digest,
                                   expected_revision=revision, actor='desktop-user')
            result = self.guard.call('read_text_file', {'path': str(self.local['sample'])})
            expected = self.local['sample'].read_bytes()
            actual = ''.join(part['text'] for part in result.get('content', []) if part.get('type') == 'text')
            if result.get('isError') or len(expected) > 4096 or actual != expected.decode('utf-8'):
                raise LiveError('The sample read did not match the local file. Review the connection.')
            row = self.store.get_tool(SERVER_ID, 'read_text_file')
            with self.state_lock:
                self.verified_version = (row['sha256'], row['revision'])
            return self.status()
        if action == 'probe_result':
            tag = request['tag']
            if not isinstance(tag, str) or len(tag) > 128:
                raise LiveError('Invalid connection test.')
            with self.state_lock:
                return {'completed_reads': self.calls.get(tag, 0)}
        if action == 'run_codex':
            with self.state_lock:
                if not self.status()['verified']:
                    raise LiveError('Approve and test the local read first.')
                if self.worker and self.worker.is_alive():
                    raise LiveError('A Codex test is already running.')
                tool = self.status()['tool']
                version = {'sha256': tool['sha256'], 'revision': tool['revision']}
                self.cancel = threading.Event()
                self.job = {'stage': 'running', **version}
                self.worker = threading.Thread(target=self.run_job, args=(version,), daemon=True)
                self.worker.start()
            return self.status()
        if action == 'cancel_codex':
            self.cancel.set()
            return self.status()
        raise LiveError('Unknown connection operation.')

    def run_job(self, version):
        try:
            result = _run_codex_task(self.db, self.cancel)
        except (LiveError, OSError, ValueError, GateError, subprocess.SubprocessError):
            result = {'stage': 'cancelled' if self.cancel.is_set() else 'failed',
                      'message': 'Codex test cancelled.' if self.cancel.is_set() else
                      'No successful MCP sample read was verified. Check the Codex CLI version and sign-in, then retry.'}
        with self.state_lock:
            self.job = {**result, **version}

    def notify(self):
        previous = self.initial_token
        try:
            while not self.stopping.wait(0.25):
                current = self.reader.catalog_state_token(SERVER_ID)
                if current != previous:
                    previous = current
                    with self.state_lock:
                        clients = list(self.clients)
                    for client in clients:
                        if client.session.legacy_ready:
                            try:
                                client.emit({'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})
                            except OSError:
                                pass
        except (GateError, OSError, sqlite3.Error):
            self.stopping.set()

    def cleanup(self):
        self.stopping.set()
        self.cancel.set()
        if self.worker:
            self.worker.join(timeout=5)
        self.notifier.join(timeout=1)
        with self.state_lock:
            for client in list(self.clients):
                try:
                    client.request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.server_close()
        self.guard.close()
        self.reader.close()
        self.store.close()


class Handler(socketserver.StreamRequestHandler):
    def emit(self, value):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(payload) > MAX_FRAME:
            raise OSError('Response exceeds limit')
        with self.output_lock:
            self.wfile.write(payload)
            self.wfile.flush()

    def read(self):
        raw = self.rfile.readline(MAX_FRAME + 1)
        if not raw:
            return None
        if len(raw) > MAX_FRAME or not raw.endswith(b'\n'):
            raise ValueError('Invalid frame')
        return raw

    def handle(self):
        service: Service = self.server
        self.output_lock = threading.Lock()
        self.request.settimeout(5)
        auth = json.loads(self.read(), object_pairs_hook=_unique)
        if not isinstance(auth, dict) or set(auth) - {'kind', 'token', 'trace_tag'}:
            return
        kind, token = auth.get('kind'), auth.get('token')
        expected = service.control_token if kind == 'control' else service.token
        if kind not in {'control', 'mcp'} or not isinstance(token, str) or not hmac.compare_digest(token, expected):
            return
        if kind == 'control':
            raw = self.read()
            try:
                message = json.loads(raw, object_pairs_hook=_unique)
                if not isinstance(message, dict):
                    raise TypeError
                result = service.controller(message)
                self.emit({'ok': True, 'data': result})
            except (LiveError, GateError, ValueError, TypeError, KeyError, TransportError, OSError, sqlite3.Error):
                self.emit({'ok': False, 'message': 'Connection operation could not complete. Refresh its current version and retry.'})
            return
        tag = auth.get('trace_tag', '')
        if not isinstance(tag, str) or len(tag) > 128:
            return
        self.session = DownstreamSession(service.guard)
        self.request.settimeout(None)
        with service.state_lock:
            service.clients.add(self)
        try:
            while raw := self.read():
                message = decode_message(raw, max_bytes=MAX_FRAME)
                reply = self.session.handle(message)
                params = message.get('params', {})
                if (tag and message.get('method') == 'tools/call' and params.get('name') == 'read_text_file'
                        and params.get('arguments', {}).get('path') == str(service.local['sample'])
                        and reply and 'result' in reply and not reply['result'].get('isError')):
                    with service.state_lock:
                        if tag not in service.calls and len(service.calls) >= 128:
                            service.calls.pop(next(iter(service.calls)))
                        service.calls[tag] = service.calls.get(tag, 0) + 1
                if reply is not None:
                    self.emit(reply)
        finally:
            with service.state_lock:
                service.clients.discard(self)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args(argv)
    service = None
    try:
        service = Service(args.db)
        for name, token in [('client', service.token), ('control', service.control_token)]:
            save_private(service.local[name], json.dumps({'port': service.server_address[1], 'token': token}).encode())
        service.serve_forever(poll_interval=0.1)
        return 0
    except (OSError, ValueError, TransportError, sqlite3.Error, GateError):
        return 2
    finally:
        if service:
            service.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
