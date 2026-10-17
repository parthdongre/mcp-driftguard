"""Bounded Streamable HTTP upstream for explicitly configured tools-only gateways.

No redirects, ambient proxies, automatic retries, OAuth discovery or endpoint
discovery from tool output. HTTPS validates the system trust store. Plain HTTP is
available only with explicit opt-in for a literal loopback address.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import queue
import re
import secrets
import socket
import ssl
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .gateway import ServerIdentity
from .gateway_transport import (
    LEGACY,
    META_PREFIX,
    MODERN,
    RpcError,
    StdioConfig,
    TransportError,
    _pairs_unique,
    decode_message,
    encode_message,
    protocol_meta,
)


@dataclass(frozen=True)
class HttpConfig:
    server_id: str
    url: str
    transport: str = "http"
    protocol_version: str = LEGACY
    auth_token_env: str | None = None
    use_os_vault: bool = False
    allow_insecure_loopback: bool = False
    timeout_seconds: float = 15.0
    max_message_bytes: int = 1024 * 1024
    max_catalog_bytes: int = 8 * 1024 * 1024
    max_tools: int = 1000
    max_pages: int = 100

    def __post_init__(self) -> None:
        # Reuse the existing count, protocol and timeout validation without
        # resolving or launching an executable.
        StdioConfig(self.server_id, ("http-profile-validation",),
                    protocol_version=self.protocol_version,
                    timeout_seconds=self.timeout_seconds,
                    max_message_bytes=self.max_message_bytes,
                    max_catalog_bytes=self.max_catalog_bytes,
                    max_tools=self.max_tools, max_pages=self.max_pages)
        if (self.transport != "http" or type(self.allow_insecure_loopback) is not bool
                or type(self.use_os_vault) is not bool or (self.use_os_vault and self.auth_token_env)):
            raise ValueError("Invalid HTTP transport configuration")
        if not isinstance(self.url, str) or len(self.url) > 4096 or re.search(r"[\x00-\x20\x7f]", self.url):
            raise ValueError("Invalid endpoint")
        parsed = urlsplit(self.url)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or parsed.query or parsed.port == 0):
            raise ValueError("Use an explicit HTTP(S) endpoint without credentials, query or fragment")
        if parsed.scheme == "http":
            try:
                loopback = ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError:
                loopback = False
            if not self.allow_insecure_loopback or not loopback:
                raise ValueError("Plain HTTP requires explicit opt-in and a literal loopback address")
        if self.auth_token_env is not None and (
            not isinstance(self.auth_token_env, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.auth_token_env)
        ):
            raise ValueError("auth_token_env must name an environment variable")

    @property
    def pass_env(self) -> tuple[str, ...]:
        return (self.auth_token_env,) if self.auth_token_env else ()

    def token(self) -> str | None:
        if self.use_os_vault:
            from .credentials import CredentialError, read
            try:
                token = read(self.server_id, self.url) or ""
            except CredentialError as error:
                raise TransportError("Unlock the operating system credential store") from error
        elif self.auth_token_env is None:
            return None
        else:
            token = os.environ.get(self.auth_token_env, "")
        if len(token) < 8 or len(token) > 8192 or re.search(r"[^\x21-\x7e]", token):
            raise TransportError("The configured bearer credential is unavailable or invalid")
        return token

    def identity(self) -> ServerIdentity:
        token = self.token()
        binding = {"endpoint": self.url, "protocol": self.protocol_version,
                   "token_sha256": hashlib.sha256(token.encode()).hexdigest() if token else None}
        fingerprint = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        return ServerIdentity(self.server_id, fingerprint, "http-configured-user",
                              protocol_version=self.protocol_version, display_name=self.server_id)


def load_config(path: str | Path) -> StdioConfig | HttpConfig:
    with Path(path).open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Configuration exceeds 64 KiB")
    try:
        data = json.loads(raw, object_pairs_hook=_pairs_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except RecursionError as error:
        raise ValueError("Configuration nesting limit exceeded") from error
    if not isinstance(data, dict):
        raise TypeError("Configuration must be an object")
    if data.get("transport") == "http":
        if set(data) - set(HttpConfig.__dataclass_fields__):
            raise ValueError("Unknown HTTP configuration keys")
        return HttpConfig(**data)
    return StdioConfig.from_file(path)


class HttpPeer:
    """One HTTP session with serialized exchanges and a caller-visible deadline.

    A daemon worker bounds caller waiting through DNS/TLS/header/body processing.
    Socket close is best-effort cancellation; a timed-out call may have executed.
    Nothing automatically retries or refreshes a session after failure.
    """
    def __init__(self, config: HttpConfig):
        self.config = config
        self._config_identity = config.identity()
        self.identity = ServerIdentity(
            config.server_id, self._config_identity.fingerprint,
            "http-user:session:" + secrets.token_hex(16),
            protocol_version=config.protocol_version, display_name=config.server_id)
        self._session_id: str | None = None
        self._sequence = 0
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._connection: http.client.HTTPConnection | None = None
        self._active_socket: socket.socket | None = None

    def verify_identity(self) -> None:
        if self._closed.is_set():
            raise TransportError("HTTP session is closed; reconnect requires review")
        if self.config.identity().fingerprint != self._config_identity.fingerprint:
            self.close()
            raise TransportError("HTTP authorization configuration changed; reconnect requires review")

    def _accept(self, message: dict[str, Any], request_id: int) -> dict[str, Any] | None:
        if "method" in message:
            if "id" in message or message.get("method") not in {
                "notifications/tools/list_changed", "notifications/progress", "notifications/message"
            }:
                raise TransportError("Unsupported HTTP server-to-client operation")
            return None
        if (type(message.get("id")) is not int or message["id"] != request_id
                or ("result" in message) == ("error" in message)):
            raise TransportError("HTTP response correlation failed")
        if "error" in message:
            raise RpcError(-32603, "Upstream rejected the request")
        result = message["result"]
        if not isinstance(result, dict):
            raise TransportError("HTTP result must be an object")
        if self.config.protocol_version == MODERN and result.get("resultType") != "complete":
            raise TransportError("Only complete modern results are supported")
        metadata = result.get("_meta", {})
        if not isinstance(metadata, dict):
            raise TransportError("HTTP result metadata must be an object")
        info = metadata.get(META_PREFIX + "serverInfo")
        if info is not None and (not isinstance(info, dict)
                                 or not isinstance(info.get("name"), str)
                                 or not isinstance(info.get("version"), str)):
            raise TransportError("HTTP serverInfo metadata is malformed")
        return result

    def _read_result(self, response: http.client.HTTPResponse, request_id: int) -> dict[str, Any]:
        maximum = self.config.max_message_bytes
        encoding = response.getheader("Content-Encoding", "identity")
        if encoding != "identity":
            raise TransportError("Compressed HTTP responses are unsupported")
        length = response.getheader("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > maximum):
            raise TransportError("HTTP response byte limit exceeded")
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type == "application/json":
            raw = response.read(maximum + 1)
            result = self._accept(decode_message(raw, max_bytes=maximum), request_id)
            if result is None:
                raise TransportError("Expected an HTTP request response")
            return result
        if content_type != "text/event-stream":
            raise TransportError("Unsupported HTTP response content type")
        total, events = 0, 0
        data: list[bytes] = []
        while True:
            line = response.readline(maximum + 1)
            total += len(line)
            if total > maximum:
                raise TransportError("HTTP event stream byte limit exceeded")
            if line in {b"\n", b"\r\n", b""}:
                if data:
                    events += 1
                    if events > 32:
                        raise TransportError("Too many HTTP event stream messages")
                    message = decode_message(b"\n".join(data), max_bytes=maximum)
                    result = self._accept(message, request_id)
                    data = []
                    if result is not None:
                        return result
                if not line:
                    raise TransportError("HTTP event stream ended without a response")
            elif line.startswith(b"data:"):
                data.append(line[5:].lstrip(b" ").rstrip(b"\r\n"))

    def _exchange(self, method: str, payload: bytes, request_id: int | None) -> dict[str, Any] | None:
        self.verify_identity()
        parsed = urlsplit(self.config.url)
        if parsed.scheme == "https":
            connection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=self.config.timeout_seconds,
                context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=self.config.timeout_seconds)
        self._connection = connection
        try:
            if self._closed.is_set():
                raise TransportError("HTTP session is closed")
            headers = {"Content-Type": "application/json",
                       "Accept": "application/json, text/event-stream",
                       "MCP-Protocol-Version": self.config.protocol_version}
            token = self.config.token()
            if token:
                headers["Authorization"] = "Bearer " + token
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
            if self._closed.is_set():
                raise TransportError("HTTP session was closed before dispatch")
            connection.connect()
            self._active_socket = connection.sock
            if self._closed.is_set():
                raise TransportError("HTTP session was closed before dispatch")
            connection.request("POST", parsed.path or "/", body=payload, headers=headers)
            response = connection.getresponse()
            # Session values are opaque credentials: bounded, never logged or persisted.
            session = response.getheader("Mcp-Session-Id")
            if session is not None:
                if len(session) > 128 or not session or re.search(r"[^\x21-\x7e]", session):
                    raise TransportError("Invalid HTTP session identifier")
                if self._session_id is not None and session != self._session_id:
                    raise TransportError("HTTP session changed; reconnect requires review")
                if self._session_id is None:
                    if method not in {"initialize", "server/discover"}:
                        raise TransportError("Unexpected new HTTP session")
                    self._session_id = session
            if request_id is None:
                if response.status != 202:
                    raise TransportError("HTTP notification was not accepted")
                return None
            if response.status != 200:
                raise TransportError("HTTP request failed; reconnect and review authorization")
            return self._read_result(response, request_id)
        finally:
            connection.close()
            self._connection = None
            self._active_socket = None

    def _bounded_exchange(self, method: str, payload: bytes, request_id: int | None) -> dict[str, Any] | None:
        if len(payload) > self.config.max_message_bytes:
            raise TransportError("HTTP request byte limit exceeded")
        replies: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                replies.put((True, self._exchange(method, payload, request_id)))
            except (OSError, ValueError, TypeError, TransportError, http.client.HTTPException):
                # Never return upstream response text, TLS diagnostics or URLs with secrets.
                replies.put((False, None))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        failed = True
        try:
            ok, result = replies.get(timeout=self.config.timeout_seconds)
            if not ok:
                raise TransportError("HTTP exchange failed; no automatic retry was attempted")
            failed = False
            return result
        except queue.Empty as error:
            raise TransportError("HTTP request timed out; refresh before retrying") from error
        finally:
            if failed:
                self.close()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self.verify_identity()
            self._sequence += 1
            body = dict(params or {})
            if self.config.protocol_version == MODERN:
                body["_meta"] = protocol_meta()
            message = {"jsonrpc": "2.0", "id": self._sequence, "method": method, "params": body}
            result = self._bounded_exchange(method, encode_message(message), self._sequence)
            if not isinstance(result, dict):
                raise TransportError("Expected an HTTP response object")
            return result

    def notify(self, method: str) -> None:
        with self._lock:
            self.verify_identity()
            self._bounded_exchange(method, encode_message({"jsonrpc": "2.0", "method": method}), None)

    def initialize(self) -> None:
        if self.config.protocol_version == LEGACY:
            result = self.request("initialize", {
                "protocolVersion": LEGACY, "capabilities": {},
                "clientInfo": {"name": "driftguard", "version": "0.4.0"}})
            if result.get("protocolVersion") != LEGACY:
                raise TransportError("HTTP protocol negotiation failed")
            self.notify("notifications/initialized")
        else:
            result = self.request("server/discover")
            if MODERN not in result.get("supportedVersions", []):
                raise TransportError("HTTP protocol discovery failed")
        if not isinstance(result.get("capabilities"), dict) or "tools" not in result["capabilities"]:
            raise TransportError("HTTP server does not advertise tools")

    def close(self) -> None:
        self._closed.set()
        active_socket = self._active_socket
        if active_socket is not None:
            # Closing HTTPResponse's buffered file from another thread can wait
            # on its read lock. Shutdown the socket instead; the worker owns all
            # buffered response cleanup and is never joined by the caller.
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
