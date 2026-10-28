"""Bounded, opt-in stdio MCP mediation. This is not a process sandbox.

The supported surface is deliberately tools-only. Unsupported protocol operations
are rejected rather than transparently bypassing the approval boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .gateway import GateError, GuardStore, IdentityMismatch, ServerIdentity

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
HANDSHAKE_VERSIONS = (LEGACY, "2025-06-18", "2025-03-26")
META_PREFIX = "io.modelcontextprotocol/"
SAFE_ENV = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT",
            "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


class TransportError(RuntimeError):
    """Safe diagnostic without upstream content, arguments or credentials."""


class RpcError(TransportError):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code, self.data = code, data


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode_message(data: bytes, *, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
    """Strict UTF-8/JSON, with bounded nesting and no duplicate keys or NaN."""
    if len(data) > max_bytes:
        raise TransportError("Message exceeds the configured byte limit")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        stack = [(value, 0)]
        nodes = 0
        while stack:
            node, depth = stack.pop()
            nodes += 1
            if depth > 64 or nodes > 100000:
                raise ValueError("JSON complexity limit")
            if isinstance(node, dict):
                for key in node:
                    key.encode("utf-8")
                stack.extend((child, depth + 1) for child in node.values())
            elif isinstance(node, list):
                stack.extend((child, depth + 1) for child in node)
            elif isinstance(node, str):
                node.encode("utf-8")
            elif isinstance(node, float) and not math.isfinite(node):
                raise ValueError("nonfinite number")
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
            raise ValueError("not a JSON-RPC object")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise TransportError("Invalid JSON-RPC message") from exc


def encode_message(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def protocol_meta(version: str = MODERN) -> dict[str, Any]:
    return {META_PREFIX + "protocolVersion": version,
            META_PREFIX + "clientInfo": {"name": "driftguard", "version": "0.4.0"},
            META_PREFIX + "clientCapabilities": {}}


@dataclass(frozen=True)
class StdioConfig:
    server_id: str
    argv: tuple[str, ...]
    cwd: str = field(default_factory=os.getcwd)
    protocol_version: str = MODERN
    pass_env: tuple[str, ...] = ()
    timeout_seconds: float = 15.0
    max_message_bytes: int = 1024 * 1024
    max_catalog_bytes: int = 8 * 1024 * 1024
    max_tools: int = 1000
    max_pages: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.server_id, str) or not NAME.fullmatch(self.server_id):
            raise ValueError("server_id must be a short ASCII identifier")
        if not isinstance(self.argv, tuple) or not self.argv or not all(isinstance(arg, str) and arg and "\x00" not in arg
                                    for arg in self.argv):
            raise ValueError("argv must be a nonempty array of nonempty strings")
        if self.protocol_version not in (MODERN, *HANDSHAKE_VERSIONS):
            raise ValueError("Unsupported protocol version")
        if (type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or not 0.05 <= self.timeout_seconds <= 300):
            raise ValueError("timeout_seconds must be between 0.05 and 300")
        if type(self.max_message_bytes) is not int or not 1024 <= self.max_message_bytes <= 16 * 1024 * 1024:
            raise ValueError("Invalid message byte limit")
        if type(self.max_catalog_bytes) is not int or not self.max_message_bytes <= self.max_catalog_bytes <= 64 * 1024 * 1024:
            raise ValueError("Invalid catalog byte limit")
        if (type(self.max_tools) is not int or type(self.max_pages) is not int
                or not 1 <= self.max_tools <= 10000 or not 1 <= self.max_pages <= 1000):
            raise ValueError("Invalid catalog count limit")
        if not isinstance(self.cwd, str) or not Path(self.cwd).is_dir():
            raise ValueError("cwd must be an existing directory")
        if not isinstance(self.pass_env, tuple) or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
               for name in self.pass_env):
            raise ValueError("pass_env contains an invalid environment variable name")

    @classmethod
    def from_file(cls, path: str | Path) -> StdioConfig:
        raw = Path(path).read_bytes()
        if len(raw) > 65536:
            raise ValueError("Configuration exceeds 64 KiB")
        try:
            data = json.loads(raw, object_pairs_hook=_pairs_unique)
        except RecursionError as exc:
            raise ValueError("Configuration nesting limit exceeded") from exc
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("Unknown configuration keys or invalid configuration")
        if not isinstance(data.get("argv"), list):
            raise TypeError("argv must be a JSON array")
        if "pass_env" in data and not isinstance(data["pass_env"], list):
            raise TypeError("pass_env must be a JSON array")
        data["argv"] = tuple(data["argv"])
        data["pass_env"] = tuple(data.get("pass_env", ()))
        return cls(**data)

    def environment(self) -> dict[str, str]:
        return {name: os.environ[name] for name in (*SAFE_ENV, *self.pass_env)
                if name in os.environ}

    def resolved_argv(self) -> tuple[str, ...]:
        executable = self.argv[0]
        if not os.path.isabs(executable) and ("/" in executable or "\\" in executable):
            executable = str(Path(self.cwd, executable).resolve())
        executable = shutil.which(executable, path=self.environment().get("PATH", os.defpath))
        if executable is None:
            raise TransportError("Configured executable is unavailable")
        return (str(Path(executable).resolve()), *self.argv[1:])

    def identity(self) -> ServerIdentity:
        argv = self.resolved_argv()
        files: dict[str, str] = {}
        total_file_bytes = 0
        for arg in argv:
            candidate = Path(arg) if Path(arg).is_absolute() else Path(self.cwd, arg)
            if not candidate.is_file():
                continue
            candidate = candidate.resolve()
            before = candidate.stat()
            if total_file_bytes + before.st_size > 256 * 1024 * 1024:
                raise TransportError("Configured executable and direct file arguments exceed the identity hash limit")
            digest = hashlib.sha256()
            with candidate.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    total_file_bytes += len(chunk)
                    if total_file_bytes > 256 * 1024 * 1024:
                        raise TransportError("Identity hash byte limit exceeded")
                    digest.update(chunk)
            after = candidate.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise TransportError("Configured file changed during identity verification")
            files[str(candidate)] = digest.hexdigest()
        binding = {"argv": argv, "cwd": str(Path(self.cwd).resolve()),
                   "protocol": self.protocol_version, "files": files,
                   "environment": self.environment()}
        fingerprint = hashlib.sha256(json.dumps(binding, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()
        # Only a digest is retained: no argv, environment values or secrets in events.
        return ServerIdentity(self.server_id, fingerprint, "local-user",
                              protocol_version=self.protocol_version,
                              display_name=self.server_id)


class StdioPeer:
    """One fixed-argv subprocess, serialized bounded exchanges, no shell or retries."""
    def _decode_line(self, line: bytes) -> dict[str, Any] | None:
        return decode_message(line, max_bytes=self.config.max_message_bytes)

    def _encode_wire(self, message: dict[str, Any]) -> bytes:
        return encode_message(message)

    def __init__(self, config: StdioConfig):
        self.config = config
        self._config_identity = config.identity()
        # An approval belongs to this live child, not merely a reusable launch
        # configuration. A previous gateway can crash before revoking its state.
        self.identity = replace(self._config_identity,
                                auth_context="local-user:session:" + secrets.token_hex(16))
        self._sequence = 0
        self._lock = threading.Lock()
        self._messages: queue.Queue[dict[str, Any] | TransportError] = queue.Queue(maxsize=32)
        self._closed = False
        self._overflow = threading.Event()
        self.process = subprocess.Popen(config.resolved_argv(), cwd=config.cwd,
                                        env=config.environment(), stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        bufsize=0, shell=False,
                                        start_new_session=os.name == "posix")
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            while not self._closed:
                line = self.process.stdout.readline(self.config.max_message_bytes + 1)
                if not line:
                    raise TransportError("Upstream disconnected")
                if not line.endswith(b"\n"):
                    raise TransportError("Upstream line is incomplete or oversized")
                item = self._decode_line(line)
                if item is not None:
                    self._messages.put_nowait(item)
        except queue.Full:
            self._overflow.set()
        except (TransportError, OSError, ValueError) as exc:
            # Closing the owned pipe can race a reader iteration. FileIO reports
            # that normal shutdown as ValueError on some runtimes/platforms.
            if self._closed:
                return
            try:
                self._messages.put_nowait(exc if isinstance(exc, TransportError)
                                          else TransportError("Upstream read failed"))
            except queue.Full:
                self._overflow.set()

    def verify_identity(self) -> None:
        if self._closed or self.process.poll() is not None:
            raise TransportError("Upstream is unavailable; explicit reconnect is required")
        if self.config.identity() != self._config_identity:
            raise TransportError("Configured executable, arguments or environment changed")

    def _write(self, payload: bytes, done: queue.Queue[Exception | None]) -> None:
        try:
            assert self.process.stdin is not None
            view = memoryview(payload)
            while view:
                count = self.process.stdin.write(view)
                if count is None or count == 0:
                    raise OSError("write failed")
                view = view[count:]
            self.process.stdin.flush()
            done.put_nowait(None)
        except (OSError, ValueError) as exc:
            done.put_nowait(exc)

    def _send(self, message: dict[str, Any], deadline: float) -> None:
        payload = self._encode_wire(message)
        if len(payload) > self.config.max_message_bytes:
            raise TransportError("Outbound message exceeds the configured byte limit")
        done: queue.Queue[Exception | None] = queue.Queue(maxsize=1)
        threading.Thread(target=self._write, args=(payload, done), daemon=True).start()
        try:
            error = done.get(timeout=max(0.001, deadline - time.monotonic()))
            if error is not None:
                raise TransportError("Upstream write failed")
        except queue.Empty as exc:
            raise TransportError("Upstream write timed out") from exc

    def notify(self, method: str) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method},
                       time.monotonic() + self.config.timeout_seconds)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.verify_identity()
            self._sequence += 1
            request_id = self._sequence
            body = dict(params or {})
            if self.config.protocol_version == MODERN:
                body["_meta"] = protocol_meta()
            message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": body}
            deadline = time.monotonic() + self.config.timeout_seconds
            try:
                self._send(message, deadline)
                for _ in range(32):
                    if self._overflow.is_set():
                        raise TransportError("Upstream message queue overflow")
                    reply = self._messages.get(timeout=max(0.001, deadline - time.monotonic()))
                    if isinstance(reply, TransportError):
                        raise reply
                    if "method" in reply:
                        if "id" in reply:
                            raise TransportError("Upstream server-to-client requests are unsupported")
                        if reply.get("method") not in ("notifications/tools/list_changed",
                                                       "notifications/progress", "notifications/message"):
                            raise TransportError("Unsupported upstream notification")
                        continue
                    if (type(reply.get("id")) is not int or reply["id"] != request_id
                            or ("result" in reply) == ("error" in reply)):
                        raise TransportError("Upstream response correlation failed")
                    if "error" in reply:
                        # Peer error strings/data may contain secrets; do not forward them.
                        raise RpcError(-32603, "Upstream rejected the request")
                    result = reply["result"]
                    if not isinstance(result, dict):
                        raise TransportError("Upstream result must be an object")
                    if (self.config.protocol_version == MODERN
                            and result.get("resultType") != "complete"):
                        raise TransportError("Only complete modern results are supported")
                    metadata = result.get("_meta", {})
                    if not isinstance(metadata, dict):
                        raise TransportError("Upstream result metadata must be an object")
                    server_info = metadata.get(META_PREFIX + "serverInfo")
                    if server_info is not None and (
                        not isinstance(server_info, dict)
                        or not isinstance(server_info.get("name"), str)
                        or not isinstance(server_info.get("version"), str)
                    ):
                        raise TransportError("Upstream serverInfo metadata is malformed")
                    return result
                raise TransportError("Too many upstream notifications")
            except queue.Empty as exc:
                self.close()
                raise TransportError("Upstream request timed out") from exc
            except TransportError:
                self.close()
                raise

    def initialize(self) -> None:
        if self.config.protocol_version in HANDSHAKE_VERSIONS:
            result = self.request("initialize", {"protocolVersion": self.config.protocol_version, "capabilities": {},
                                                 "clientInfo": {"name": "driftguard", "version": "0.4.0"}})
            negotiated = result.get("protocolVersion")
            if negotiated not in HANDSHAKE_VERSIONS:
                raise TransportError("Upstream protocol negotiation failed")
            self.identity = replace(self.identity, protocol_version=negotiated)
            self.notify("notifications/initialized")
        else:
            result = self.request("server/discover")
            if MODERN not in result.get("supportedVersions", []):
                raise TransportError("Upstream does not support the configured protocol version")
        if not isinstance(result.get("capabilities"), dict) or "tools" not in result["capabilities"]:
            raise TransportError("Upstream does not advertise tools")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    self.process.kill()
                self.process.wait(timeout=1)
        if self.process.stdout is not None:
            self.process.stdout.close()


class ProtectedGateway:
    def __init__(self, config: StdioConfig, store: GuardStore,
                 peer_factory: Callable[[Any], Any] | None = None):
        self.config, self.store = config, store
        if peer_factory is None:
            if isinstance(config, StdioConfig):
                peer_factory = StdioPeer
            else:
                from .gateway_http import HttpConfig, HttpPeer
                if not isinstance(config, HttpConfig):
                    raise TypeError("Unsupported gateway transport configuration")
                peer_factory = HttpPeer
        self.peer = peer_factory(config)
        self._credentials = tuple(os.environ[name] for name in config.pass_env
                                  if name in os.environ and len(os.environ[name]) >= 8)
        if hasattr(config, "token"):
            token = config.token()
            if token:
                self._credentials = (*self._credentials, token)
        self.identity = self.peer.identity
        self._closed = False
        self._lock = threading.RLock()
        self._heartbeat_stop = threading.Event()
        try:
            self.store.register_server(self.identity)
            self.peer.initialize()
            self.identity = self.peer.identity
            self.store.register_server(self.identity)
            self.refresh_catalog()
            self.store.mark_gateway(self.identity, active=True)
            self._heartbeat = threading.Thread(target=self._watch_heartbeat, daemon=True)
            self._heartbeat.start()
            if getattr(self.peer, "process", None) is not None:
                self._monitor = threading.Thread(target=self._watch_disconnect, daemon=True)
                self._monitor.start()
        except Exception:
            self.close()
            raise

    def _watch_heartbeat(self) -> None:
        while not self._heartbeat_stop.wait(2):
            try:
                self.store.mark_gateway(self.identity, active=True)
            except (GateError, OSError, sqlite3.Error):
                self._heartbeat_stop.set()
                return

    def _watch_disconnect(self) -> None:
        self.peer.process.wait()
        if not self._closed:
            try:
                self.close()
            except (GateError, OSError, sqlite3.Error):
                # The call path independently revalidates and fails closed even
                # if the local review store became unavailable during shutdown.
                self.peer.close()

    def refresh_catalog(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                # Every peer.request rechecks identity immediately before sending.
                tools: list[dict[str, Any]] = []
                names: set[str] = set()
                cursors: set[str] = set()
                cursor = None
                size = 0
                for _ in range(self.config.max_pages):
                    result = self.peer.request("tools/list", {"cursor": cursor} if cursor else {})
                    page = result.get("tools")
                    if not isinstance(page, list):
                        raise TransportError("Malformed upstream tool catalog")
                    size += len(encode_message(result))
                    if size > self.config.max_catalog_bytes:
                        raise TransportError("Upstream catalog byte limit exceeded")
                    for tool in page:
                        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                            raise TransportError("Malformed upstream tool definition")
                        if not NAME.fullmatch(tool["name"]) or tool["name"] in names:
                            raise TransportError("Invalid or duplicate upstream tool name")
                        if not isinstance(tool.get("inputSchema"), dict):
                            raise TransportError("Tool inputSchema must be an object")
                        if self._contains_credential(tool):
                            raise TransportError("Tool definition contains a configured credential")
                        names.add(tool["name"])
                        tools.append(tool)
                    if len(tools) > self.config.max_tools:
                        raise TransportError("Upstream catalog tool limit exceeded")
                    cursor = result.get("nextCursor")
                    if cursor is None:
                        if hasattr(self.peer, "configure_catalog"):
                            tools, rejected = self.peer.configure_catalog(tools)
                            for name in rejected:
                                self.store.record_event(
                                    "gateway_tool_withheld", self.config.server_id, name,
                                    reason="invalid_http_routing_annotation")
                        return self.store.ingest_catalog(self.config.server_id, tools,
                                                         identity=self.identity)
                    if not isinstance(cursor, str) or not cursor or cursor in cursors:
                        raise TransportError("Invalid or repeated pagination cursor")
                    cursors.add(cursor)
                raise TransportError("Upstream catalog page limit exceeded")
            except Exception:
                self.close()
                raise

    def list_approved(self) -> list[dict[str, Any]]:
        records = self.refresh_catalog()
        return [record["definition"] for record in sorted(records, key=lambda x: x["tool_name"])
                if record["status"] == "approved" and "outputSchema" not in record["definition"]]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.refresh_catalog()
            def invoke(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
                # request() performs the final identity check at the wire boundary.
                result = self.peer.request("tools/call", {"name": tool_name, "arguments": args})
                return self._check_result(result)

            try:
                record = self.store.get_tool(self.config.server_id, name)
                if "outputSchema" in record["definition"]:
                    self.store.record_event("gateway_call_blocked", self.config.server_id, name,
                                            reason="unsupported_output_contract")
                    raise RpcError(-32602, "This gateway profile does not support outputSchema contracts")
                return self.store.dispatch(self.config.server_id, name, arguments, invoke,
                                           expected_hash=record["sha256"],
                                           expected_revision=record["revision"], identity=self.identity)
            except GateError:
                self.store.record_event("gateway_call_blocked", self.config.server_id,
                                        name if isinstance(name, str) and NAME.fullmatch(name) else None,
                                        reason="approval_or_policy_check_failed")
                raise
            except TransportError:
                self.close()
                raise

    def _check_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Independent conservative text-only egress checks; no safety guarantee."""
        content = result.get("content")
        if not isinstance(content, list) or len(content) > 256:
            raise TransportError("Tool result content is invalid or exceeds the item limit")
        if "isError" in result and not isinstance(result["isError"], bool):
            raise TransportError("Tool result isError must be boolean")
        clean = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                raise TransportError("Only text tool results are supported by this policy")
            clean.append({"type": "text", "text": item["text"]})
        encoded = json.dumps(clean, ensure_ascii=False)
        if self._contains_credential("".join(item["text"] for item in clean)):
            raise TransportError("Tool result contains a configured credential")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", encoded):
            raise TransportError("Tool result contains private key material")
        # Do not forward arbitrary metadata, embedded resources, URLs for fetching,
        # or structuredContent that could bypass the independent text egress checks.
        return {"content": clean, "isError": result.get("isError", False)}

    def _contains_credential(self, value: Any) -> bool:
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                if any(secret in item for secret in self._credentials):
                    return True
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                stack.extend(item.keys())
                stack.extend(item.values())
        return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._heartbeat_stop.set()
            try:
                try:
                    self.store.mark_gateway(self.identity, active=False)
                    self.store.invalidate_server(self.config.server_id,
                                                 "Gateway disconnected; reconnect requires review",
                                                 identity=self.identity)
                except IdentityMismatch:
                    # Closing a stale process must not revoke its replacement.
                    pass
            finally:
                self.peer.close()


class DownstreamSession:
    """Strict tools-only stdio server facade; approval methods never enter MCP."""
    def __init__(self, gateway: ProtectedGateway):
        self.gateway = gateway
        self.legacy_initialized = False
        self.legacy_ready = False
        self.seen_ids: set[tuple[type, Any]] = set()

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        has_id = "id" in message
        method = message.get("method")
        if (message.get("jsonrpc") != "2.0" or not isinstance(method, str)
                or "result" in message or "error" in message):
            return self.error(request_id, -32600, "Invalid JSON-RPC request")
        if not has_id:
            if method == "notifications/initialized" and self.legacy_initialized:
                self.legacy_ready = True
            # Unknown notifications cannot invoke tools or change approvals.
            return None
        if type(request_id) not in (str, int) or (isinstance(request_id, str) and len(request_id) > 128):
            return self.error(None, -32600, "Request ID must be a string or integer")
        key = (type(request_id), request_id)
        if key in self.seen_ids:
            return self.error(request_id, -32600, "Repeated request ID")
        if len(self.seen_ids) >= 100000:
            return self.error(request_id, -32600, "Request limit reached; reconnect required")
        self.seen_ids.add(key)
        params = message.get("params", {})
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "params must be an object")
        version = LEGACY
        try:
            if method == "initialize":
                if self.legacy_initialized or params.get("protocolVersion") not in HANDSHAKE_VERSIONS:
                    raise RpcError(-32602, "Unsupported handshake protocol version")
                self.legacy_initialized = True
                result = {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                          "serverInfo": {"name": "driftguard", "version": "0.4.0"}}
            else:
                meta = params.get("_meta", {})
                if not isinstance(meta, dict):
                    raise RpcError(-32602, "Invalid request metadata")
                requested = meta.get(META_PREFIX + "protocolVersion")
                if requested is not None:
                    if requested != MODERN:
                        raise RpcError(-32022, "Unsupported protocol version",
                                       {"supported": [MODERN, *HANDSHAKE_VERSIONS], "requested": requested})
                    if not isinstance(meta.get(META_PREFIX + "clientCapabilities"), dict):
                        raise RpcError(-32602, "Modern clientCapabilities metadata is required")
                    version = MODERN
                elif not self.legacy_ready:
                    raise RpcError(-32600, "Initialize legacy MCP or supply modern request metadata")
                if method == "server/discover" and version == MODERN:
                    result = {"supportedVersions": [MODERN, *HANDSHAKE_VERSIONS], "capabilities": {"tools": {}},
                              "ttlMs": 0, "cacheScope": "private",
                              "_meta": {META_PREFIX + "serverInfo": {"name": "driftguard", "version": "0.4.0"}}}
                elif method == "ping":
                    result = {}
                elif method == "tools/list":
                    if set(params) - {"_meta"}:
                        raise RpcError(-32602, "Downstream pagination is unsupported")
                    result = {"tools": self.gateway.list_approved()}
                    if version == MODERN:
                        result.update(ttlMs=0, cacheScope="private")
                elif method == "tools/call":
                    name, arguments = params.get("name"), params.get("arguments", {})
                    if set(params) - {"name", "arguments", "_meta"}:
                        raise RpcError(-32602, "Unsupported call parameter or extension")
                    if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(arguments, dict):
                        raise RpcError(-32602, "Invalid tool name or arguments")
                    result = self.gateway.call(name, arguments)
                else:
                    raise RpcError(-32601, "Method is outside the approved tools-only surface")
            if version == MODERN:
                result["resultType"] = "complete"
                result["_meta"] = {META_PREFIX + "serverInfo": {"name": "driftguard", "version": "0.4.0"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            return self.error(request_id, exc.code, str(exc), exc.data)
        except TransportError:
            return self.error(request_id, -32603, "Gateway verification or upstream transport failed")
        except Exception:  # noqa: BLE001 - protocol boundary must fail closed without secret traces
            # Security-core denials and storage failures must not leak internal state.
            return self.error(request_id, -32603, "Gateway denied the request; inspect local security review")

    @staticmethod
    def error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        if type(request_id) not in (str, int) or (isinstance(request_id, str) and len(request_id) > 128):
            request_id = None
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
