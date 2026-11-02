"""Fixed stdio-to-loopback adapter; its data token cannot approve tools."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from pathlib import Path

from .live_connection import LiveError, read_private


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', type=Path, required=True)
    parser.add_argument('--trace-tag', default='')
    args = parser.parse_args(argv)
    try:
        endpoint = read_private(args.connection)
        port, token = endpoint['port'], endpoint['token']
        if (type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str)
                or len(token) != 64 or len(args.trace_tag) > 128):
            raise ValueError
        with socket.create_connection(('127.0.0.1', port), timeout=5) as peer:
            peer.settimeout(None)
            peer.sendall(json.dumps({'kind': 'mcp', 'token': token, 'trace_tag': args.trace_tag}).encode() + b'\n')
            done = threading.Event()

            def incoming():
                try:
                    while chunk := os.read(sys.stdin.fileno(), 65536):
                        peer.sendall(chunk)
                    peer.shutdown(socket.SHUT_WR)
                except OSError:
                    done.set()

            def outgoing():
                try:
                    while chunk := peer.recv(65536):
                        view = memoryview(chunk)
                        while view:
                            written = os.write(sys.stdout.fileno(), view)
                            if not written:
                                return
                            view = view[written:]
                except OSError:
                    pass
                finally:
                    done.set()

            threading.Thread(target=incoming, daemon=True).start()
            threading.Thread(target=outgoing, daemon=True).start()
            done.wait()
        return 0
    except (OSError, KeyError, ValueError, TypeError, LiveError):
        print('DriftGuard connection is unavailable. Reconnect from the desktop app.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
