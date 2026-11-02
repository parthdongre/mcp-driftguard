"""Run a protected tools-only MCP server on this process's stdin/stdout."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

from .gateway import GateError, GuardStore
from .gateway_http import HttpConfig, load_config
from .gateway_transport import (
    DownstreamSession,
    ProtectedGateway,
    StdioConfig,
    TransportError,
    decode_message,
    encode_message,
)


def serve(config: StdioConfig | HttpConfig, store: GuardStore) -> int:
    """Only JSON-RPC goes to stdout. No upstream stderr or raw exception content."""
    gateway = ProtectedGateway(config, store)
    try:
        return _serve_connected(config, store, gateway)
    finally:
        gateway.close()


def _serve_connected(config: StdioConfig | HttpConfig, store: GuardStore, gateway: ProtectedGateway) -> int:
    session = DownstreamSession(gateway)
    output_lock = threading.Lock()
    notification_stop = threading.Event()
    initial_token = store.catalog_state_token(config.server_id)

    def emit(message: dict) -> None:
        payload = encode_message(message)
        if len(payload) > config.max_message_bytes:
            payload = encode_message(session.error(message.get("id"), -32603,
                                                   "Gateway response byte limit exceeded"))
        # One complete frame at a time. Raw writes avoid buffered-stream locks
        # held by a daemon notifier if a client disconnects during shutdown.
        with output_lock:
            view = memoryview(payload)
            while view:
                written = os.write(sys.stdout.fileno(), view)
                if not written:
                    raise OSError("Gateway output closed")
                view = view[written:]

    def watch_reviews() -> None:
        try:
            previous = initial_token
            while not notification_stop.wait(0.25):
                current = store.catalog_state_token(config.server_id)
                if current != previous:
                    previous = current
                    if session.legacy_ready:
                        emit({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except (GateError, OSError, sqlite3.Error):
            # A hint cannot grant permission. Every list/call still verifies the
            # complete catalog and identity independently in the request path.
            notification_stop.set()

    notifier = threading.Thread(target=watch_reviews, daemon=True)
    notifier.start()
    print("DriftGuard stdio gateway active. New tools require local review. "
          "Only clients routed through this process are protected.", file=sys.stderr)
    try:
        while True:
            line = sys.stdin.buffer.readline(config.max_message_bytes + 1)
            if not line:
                return 0
            if len(line) > config.max_message_bytes or not line.endswith(b"\n"):
                reply = session.error(None, -32700, "Inbound message limit or framing violation")
                emit(reply)
                return 2
            try:
                message = decode_message(line, max_bytes=config.max_message_bytes)
                reply = session.handle(message)
            except TransportError:
                reply = session.error(None, -32700, "Invalid JSON-RPC message")
            if reply is not None:
                emit(reply)
    finally:
        notification_stop.set()
        notifier.join(timeout=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("serve", "identity"))
    parser.add_argument("--config", type=Path, required=True,
                        help="Explicit local JSON configuration; argv is never interpreted by a shell")
    parser.add_argument("--state", type=Path,
                        help="Shared GuardStore SQLite file used by the local review app")
    args = parser.parse_args(argv)
    if args.action == "serve" and args.state is None:
        parser.error("serve requires an explicit --state path")
    try:
        config = load_config(args.config)
        if args.action == "identity":
            identity = config.identity()
            print(json.dumps({"server_id": identity.server_id, "fingerprint": identity.fingerprint,
                              "auth_context": identity.auth_context,
                              "protocol_version": identity.protocol_version}, indent=2))
            return 0
        store = GuardStore(str(args.state))
        try:
            return serve(config, store)
        finally:
            store.close()
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, TransportError):
        print("DriftGuard could not start or continue. Check the local configuration, "
              "server availability and security review.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
