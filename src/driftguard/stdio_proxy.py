from __future__ import annotations

import json
import subprocess
import sys
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from .adapters import intercept_tools_list
from .runtime import DriftGuardService, SQLiteSnapshotStore


def _id_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


class StdioProxyFilter:
    """Track JSON-RPC requests and intercept matching tools/list responses."""

    def __init__(self, *, server_id: str, service: DriftGuardService) -> None:
        self.server_id = server_id
        self.service = service
        self._pending_methods: dict[str, str] = {}
        self._errors: list[str] = []

    def process_client_line(self, line: str) -> str:
        """Observe a client->server JSON-RPC line without modifying it."""

        try:
            message = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return line

        if (
            isinstance(message, dict)
            and "id" in message
            and isinstance(message.get("method"), str)
        ):
            self._pending_methods[_id_key(message["id"])] = message["method"]
        return line

    def process_server_line(self, line: str) -> str:
        """Intercept a server response when it answers a tracked tools/list request."""

        try:
            message = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return line

        if not isinstance(message, dict) or "id" not in message or "method" in message:
            return line

        method = self._pending_methods.pop(_id_key(message["id"]), None)
        if method != "tools/list" or not isinstance(message.get("result"), dict):
            return line

        ending = _line_ending(line)
        try:
            result = intercept_tools_list(
                payload=message,
                server_id=self.server_id,
                service=self.service,
            )
            transformed = result.payload
        except Exception as exc:  # noqa: BLE001 - security boundary must fail closed
            # Any unexpected inspection failure must not expose an unreviewed catalog.
            transformed = deepcopy(message)
            candidate = transformed.get("result")
            if isinstance(candidate, dict):
                candidate["tools"] = []
            self._errors.append(
                f"DriftGuard failed to inspect tools/list response {message.get('id')!r}: {exc}"
            )

        return json.dumps(
            transformed,
            separators=(",", ":"),
            ensure_ascii=False,
        ) + ending

    def pop_errors(self) -> list[str]:
        errors = list(self._errors)
        self._errors.clear()
        return errors


def _copy_stderr(stream) -> None:
    for line in stream:
        sys.stderr.write(line)
        sys.stderr.flush()


def run_stdio_proxy(
    *,
    command: list[str],
    db_path: str | Path,
    server_id: str,
) -> int:
    """Run an MCP server as a child process and transparently guard its stdio traffic."""

    if not command:
        raise ValueError("A child MCP server command is required.")

    store = SQLiteSnapshotStore(db_path)
    service = DriftGuardService(store=store)
    message_filter = StdioProxyFilter(server_id=server_id, service=service)

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if process.stdin is None or process.stdout is None or process.stderr is None:
        store.close()
        process.terminate()
        raise RuntimeError("Failed to create MCP proxy pipes.")

    def forward_client_input() -> None:
        try:
            for line in sys.stdin:
                process.stdin.write(message_filter.process_client_line(line))
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    input_thread = threading.Thread(target=forward_client_input, daemon=True)
    stderr_thread = threading.Thread(
        target=_copy_stderr,
        args=(process.stderr,),
        daemon=True,
    )
    input_thread.start()
    stderr_thread.start()

    try:
        for line in process.stdout:
            transformed = message_filter.process_server_line(line)
            for error in message_filter.pop_errors():
                sys.stderr.write(f"[driftguard] {error}\n")
                sys.stderr.flush()
            try:
                sys.stdout.write(transformed)
                sys.stdout.flush()
            except BrokenPipeError:
                process.terminate()
                break
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()
    finally:
        store.close()
