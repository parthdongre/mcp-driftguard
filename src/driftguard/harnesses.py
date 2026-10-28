"""Local harness discovery and explicit, definition-only collection.

Scanning only reads known configuration files. Fetching starts a selected process
or connects to its endpoint, performs discovery, then closes it. No tool calls,
model turns, config writes, credential-cache extraction or gateway approvals.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .canonicalize import exact_json
from .gateway import GuardStore, ServerIdentity
from .gateway_http import HttpConfig, HttpPeer
from .gateway_transport import (
    LEGACY,
    NAME,
    SAFE_ENV,
    StdioConfig,
    StdioPeer,
    TransportError,
    _pairs_unique,
    decode_message,
    encode_message,
)

MAX_CONFIG_BYTES = 1024 * 1024
MAX_SOURCES = 200
FETCH_SECONDS = 12.0
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class HarnessError(ValueError):
    """Safe, fixed diagnostic suitable for the local interface."""


@dataclass(frozen=True)
class _Source:
    harness: str
    name: str
    scope: str
    path: Path
    cwd: Path
    settings: dict[str, Any] = field(repr=False)
    file_digest: str
    kind: str = "configured"

    @property
    def source_id(self) -> str:
        return hashlib.sha256(exact_json([
            self.harness, self.name, self.scope, str(self.path), str(self.cwd),
        ]).encode()).hexdigest()

    @property
    def digest(self) -> str:
        return hashlib.sha256(exact_json([
            self.source_id, self.file_digest, self.settings,
        ]).encode()).hexdigest()


@dataclass(frozen=True)
class _LocalConfig(StdioConfig):
    literal_env: tuple[tuple[str, str], ...] = field(default=(), repr=False)

    def environment(self) -> dict[str, str]:
        return {**super().environment(), **dict(self.literal_env)}


@dataclass(frozen=True)
class _BearerConfig(HttpConfig):
    bearer: str | None = field(default=None, repr=False)

    def token(self) -> str | None:
        if self.bearer is None:
            return super().token()
        if not 8 <= len(self.bearer) <= 8192 or re.search(r"[^\x21-\x7e]", self.bearer):
            raise HarnessError("The configured bearer credential is invalid.")
        return self.bearer


class _Budget:
    collection_deadline: float

    def _limit(self) -> None:
        remaining = self.collection_deadline - time.monotonic()
        if remaining < 0.05:
            raise HarnessError("Definition collection timed out; no partial catalog was saved.")
        self.config = replace(self.config, timeout_seconds=remaining)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._limit()
        return super().request(method, params)

    def notify(self, method: str) -> None:
        self._limit()
        super().notify(method)


class _DiscoveryStdioPeer(_Budget, StdioPeer):
    pass


class _DiscoveryHttpPeer(_Budget, HttpPeer):
    pass


class _CodexPeer(_DiscoveryStdioPeer):
    """App Server JSONL has no jsonrpc header; it is not the MCP protocol."""

    def _decode_line(self, line: bytes) -> dict[str, Any]:
        stripped = line.lstrip()
        if not stripped.startswith(b"{"):
            raise TransportError("Invalid Codex response")
        value = decode_message(b'{"jsonrpc":"2.0",' + stripped[1:],
                               max_bytes=self.config.max_message_bytes + 16)
        # Ignore bounded runtime notifications, but never accept server requests.
        if "method" in value and "id" not in value:
            value["method"] = "notifications/message"
        return value

    def _encode_wire(self, message: dict[str, Any]) -> bytes:
        wire = {key: value for key, value in message.items() if key != "jsonrpc"}
        if wire.get("method") == "initialized":
            wire["params"] = {}
        return encode_message(wire)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in {"initialize", "mcpServerStatus/list"}:
            raise HarnessError("Only Codex tool discovery is available.")
        return super().request(method, params)

    def initialize(self) -> None:
        self.request("initialize", {"clientInfo": {
            "name": "driftguard", "title": "DriftGuard definition review", "version": "0.4.0",
        }, "capabilities": {"optOutNotificationMethods": ["mcpServer/startupStatus/updated"]}})
        self.notify("initialized")


def _project(value: str | None) -> Path:
    if value is None or value == "":
        return Path.home().resolve()
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise HarnessError("Choose an existing absolute project directory.")
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise HarnessError("Choose an existing absolute project directory.")
    return path.resolve()


def _read(path: Path) -> tuple[dict[str, Any], str] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise HarnessError("A harness configuration is not a regular file.")
            raw = stream.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(raw) > MAX_CONFIG_BYTES:
        raise HarnessError("A harness configuration exceeds the 1 MiB limit.")
    try:
        data = (tomllib.loads(raw.decode("utf-8")) if path.suffix == ".toml" else
                json.loads(raw, object_pairs_hook=_pairs_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        if not isinstance(data, dict):
            raise TypeError()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise HarnessError("A harness configuration could not be parsed.") from None
    return data, hashlib.sha256(raw).hexdigest()


def _sources(project: Path) -> tuple[list[_Source], list[str]]:
    sources: dict[tuple[str, str], _Source] = {}
    warnings: list[str] = []

    def entries(harness: str, scope: str, path: Path, data: Any, digest: str) -> None:
        if not isinstance(data, dict):
            raise HarnessError("An MCP server table is malformed.")
        if len(data) > MAX_SOURCES:
            raise HarnessError("Too many configured servers; narrow the selected project.")
        for name, settings in data.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 128 or re.search(r"[\x00-\x1f\x7f]", name):
                warnings.append(f"{harness}: a server name is invalid.")
                continue
            sources[harness, name] = _Source(harness, name, scope, path, project,
                                            settings, digest)

    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    claude_path = Path(claude_dir).expanduser() / ".claude.json" if claude_dir else Path.home() / ".claude.json"
    paths = [("codex", "user", codex_home / "config.toml"),
             ("codex", "project", project / ".codex/config.toml"),
             ("claude-code", "user", claude_path),
             ("claude-code", "project", project / ".mcp.json")]
    local: tuple[Path, Any, str] | None = None
    for harness, scope, path in paths:
        try:
            result = _read(path)
            if result is None:
                continue
            data, digest = result
            entries(harness, scope, path, data.get("mcp_servers" if harness == "codex" else "mcpServers", {}), digest)
            if harness == "claude-code" and scope == "user":
                projects = data.get("projects", {})
                if isinstance(projects, dict) and isinstance(projects.get(str(project)), dict):
                    local = path, projects[str(project)], digest
        except (HarnessError, OSError):
            # A broken higher-priority config must not silently expose a fallback.
            warnings.append(f"{harness} {scope}: configuration unavailable or invalid; configured-server collection disabled.")
            sources = {key: value for key, value in sources.items() if key[0] != harness}
            # Keep other harnesses usable without guessing the effective config.
            warnings.append(f"blocked:{harness}")
    if local is not None:
        path, data, digest = local
        entries("claude-code", "local", path, data.get("mcpServers", {}), digest)
        disabled = data.get("disabledMcpServers", [])
        if isinstance(disabled, list):
            for name in disabled:
                if isinstance(name, str) and ("claude-code", name) in sources:
                    source = sources["claude-code", name]
                    if isinstance(source.settings, dict):
                        sources["claude-code", name] = replace(source, settings={**source.settings, "enabled": False})
    blocked = {item.removeprefix("blocked:") for item in warnings if item.startswith("blocked:")}
    sources = {key: value for key, value in sources.items() if key[0] not in blocked}
    warnings = [item for item in warnings if not item.startswith("blocked:")]
    for harness, executable, args in [("codex", "codex", ["app-server"]),
                                      ("claude-code", "claude", ["mcp", "serve"])]:
        if resolved := shutil.which(executable):
            path = Path(resolved).absolute()
            info = path.stat()
            sources[harness, "\x00runtime"] = _Source(
                harness, "Codex MCP catalog" if harness == "codex" else "Claude Code tools",
                "runtime", path, project, {"command": str(path), "args": args,
                                           "env_vars": [name for name in (
                                               "CODEX_HOME" if harness == "codex" else "CLAUDE_CONFIG_DIR",
                                           ) if name in os.environ]},
                f"{info.st_size}:{info.st_mtime_ns}", kind="runtime",
            )
    if len(sources) > MAX_SOURCES:
        raise HarnessError("Too many configured servers; narrow the selected project.")
    return sorted(sources.values(), key=lambda s: (s.kind != "runtime", s.harness, s.name)), warnings


def _expand(value: str) -> str:
    def substitute(match: re.Match[str]) -> str:
        name, default = match.groups()
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise HarnessError("A referenced environment variable is missing; start DriftGuard from the configured terminal.")
    return _VARIABLE.sub(substitute, value)


def _config(source: _Source) -> StdioConfig | HttpConfig:
    raw = source.settings
    if not isinstance(raw, dict):
        raise HarnessError("This server configuration is malformed.")
    if raw.get("enabled", True) is not True or raw.get("disabled", False) is not False:
        raise HarnessError("This server is disabled in the harness configuration.")
    if raw.get("experimental_environment") == "remote":
        raise HarnessError("Remote-executor servers require the Codex runtime connection.")
    expand = _expand if source.harness == "claude-code" else lambda value: value
    server_id = "harness." + source.source_id[:32]
    if source.harness == "codex":
        transport = "http" if "url" in raw else "stdio"
    else:
        transport = raw.get("type", "stdio")
    if transport in {"http", "streamable-http"}:
        endpoint = raw.get("url")
        if not isinstance(endpoint, str):
            raise HarnessError("The configured endpoint is missing.")
        if raw.get("headersHelper"):
            raise HarnessError("Dynamic header helpers are unsupported; no helper was executed.")
        headers = raw.get("http_headers" if source.harness == "codex" else "headers", {})
        env_headers = raw.get("env_http_headers", {})
        if not isinstance(headers, dict) or not isinstance(env_headers, dict):
            raise HarnessError("The configured HTTP headers are malformed.")
        if any(key.lower() != "authorization" for key in (*headers, *env_headers)) or len(headers) + len(env_headers) > 1:
            raise HarnessError("Custom HTTP headers require a separate adapter; nothing was sent.")
        authorization = next(iter(headers.values()), None)
        if env_headers:
            env_name = next(iter(env_headers.values()))
            if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
                raise HarnessError("The configured header environment name is invalid.")
            authorization = os.environ.get(env_name)
            if authorization is None:
                raise HarnessError("The HTTP credential environment variable is missing.")
        bearer = None
        if authorization is not None:
            if not isinstance(authorization, str):
                raise HarnessError("The configured authorization header is invalid.")
            authorization = expand(authorization)
            if not authorization.startswith("Bearer "):
                raise HarnessError("Only bearer authorization is supported for direct collection.")
            bearer = authorization[7:]
        token_env = raw.get("bearer_token_env_var")
        if bearer is not None and token_env is not None:
            raise HarnessError("Multiple HTTP credential sources are unsupported.")
        config = _BearerConfig(server_id, expand(endpoint), protocol_version=LEGACY,
                               auth_token_env=token_env, bearer=bearer, timeout_seconds=FETCH_SECONDS,
                               max_pages=20, max_tools=500, max_catalog_bytes=2 * 1024 * 1024)
        config.token()  # Validate availability without exposing credentials.
        return config
    if transport != "stdio" or "url" in raw:
        raise HarnessError("This transport is unsupported; use a stdio or HTTPS MCP server.")
    command, args = raw.get("command"), raw.get("args", [])
    env, names = raw.get("env", {}), raw.get("env_vars", [])
    if (not isinstance(command, str) or not command or not isinstance(args, list) or len(args) > 64
            or any(not isinstance(arg, str) for arg in args)
            or not isinstance(env, dict) or not isinstance(names, list) or len(env) + len(names) > 128):
        raise HarnessError("The configured process arguments or environment are malformed.")
    forwarded = []
    for name in names:
        if isinstance(name, dict) and name.get("source", "local") == "local":
            name = name.get("name")
        if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
            raise HarnessError("Remote or malformed environment forwarding is unsupported.")
        if name not in os.environ:
            raise HarnessError("A forwarded environment variable is missing; start DriftGuard from the configured terminal.")
        forwarded.append(name)
    if any(not _ENV_NAME.fullmatch(key) or not isinstance(value, str) or "\x00" in value
           for key, value in env.items()):
        raise HarnessError("The configured environment is malformed.")
    overrides = tuple((key, expand(value)) for key, value in env.items())
    cwd = raw.get("cwd", str(source.cwd))
    if not isinstance(cwd, str):
        raise HarnessError("The configured working directory is invalid.")
    directory = Path(expand(cwd)).expanduser()
    if not directory.is_absolute():
        directory = source.cwd / directory
    config = _LocalConfig(server_id, (expand(command), *(expand(arg) for arg in args)),
                          cwd=str(directory.resolve()), protocol_version=LEGACY,
                          pass_env=tuple(forwarded), literal_env=overrides,
                          timeout_seconds=FETCH_SECONDS, max_pages=20, max_tools=500,
                          max_catalog_bytes=2 * 1024 * 1024)
    config.resolved_argv()
    return config


def scan(project_dir: str | None = None) -> dict[str, Any]:
    project = _project(project_dir)
    sources, warnings = _sources(project)
    items = []
    for source in sources:
        issue = None
        try:
            config = _config(source)
            transport = "codex-app-server" if source.kind == "runtime" and source.harness == "codex" else (
                "stdio" if isinstance(config, StdioConfig) else "http")
        except (HarnessError, ValueError, TypeError, OSError, TransportError) as error:
            issue = str(error) if isinstance(error, HarnessError) else "Configuration unsupported or unavailable."
            transport = "unavailable"
        items.append({"source_id": source.source_id, "config_digest": source.digest,
                      "harness": source.harness, "name": source.name, "scope": source.scope,
                      "kind": source.kind, "config_path": str(source.path),
                      "transport": transport, "ready": issue is None, "issue": issue})
    return {"project_dir": str(project), "sources": items, "warnings": warnings,
            "scope": "Definition review only. Collection does not route or protect harness calls."}


def _request(peer: StdioPeer | HttpPeer, method: str, params: dict[str, Any], deadline: float) -> dict[str, Any]:
    remaining = deadline - time.monotonic()
    if remaining < 0.05:
        raise HarnessError("Definition collection timed out; no partial catalog was saved.")
    peer.config = replace(peer.config, timeout_seconds=remaining)
    return peer.request(method, params)


def _catalog(peer: StdioPeer | HttpPeer, deadline: float) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = None
    total = 0
    for _ in range(20):
        page = _request(peer, "tools/list", {"cursor": cursor} if cursor else {}, deadline)
        batch = page.get("tools")
        if not isinstance(batch, list):
            raise HarnessError("The server returned an invalid tool catalog.")
        total += len(encode_message(page))
        tools.extend(batch)
        if total > 2 * 1024 * 1024 or len(tools) > 500:
            raise HarnessError("The tool catalog exceeds the collection limits.")
        cursor = page.get("nextCursor")
        if cursor is None:
            return tools
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise HarnessError("The server returned invalid catalog pagination.")
        seen.add(cursor)
    raise HarnessError("The tool catalog exceeds the page limit.")


def _codex_catalogs(peer: _CodexPeer, deadline: float) -> list[tuple[str, list[dict[str, Any]]]]:
    catalogs = []
    seen: set[str] = set()
    names: set[str] = set()
    cursor = None
    total = 0
    for _ in range(20):
        params: dict[str, Any] = {"limit": 50, "detail": "toolsAndAuthOnly"}
        if cursor:
            params["cursor"] = cursor
        page = _request(peer, "mcpServerStatus/list", params, deadline)
        total += len(encode_message(page))
        rows = page.get("data")
        if not isinstance(rows, list) or total > 2 * 1024 * 1024:
            raise HarnessError("Codex returned an invalid or oversized server catalog.")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not NAME.fullmatch(row["name"]) or row["name"] in names:
                raise HarnessError("Codex returned invalid or duplicate server names.")
            names.add(row["name"])
            tools = row.get("tools")
            if not isinstance(tools, dict) or any(not isinstance(tool, dict) or tool.get("name") != key for key, tool in tools.items()):
                raise HarnessError("Codex returned an invalid tool definition map.")
            if not tools and row.get("authStatus") == "notLoggedIn":
                raise HarnessError("A Codex MCP server needs authentication. Sign in through Codex, then retry.")
            catalogs.append((row["name"], list(tools.values())))
            if len(catalogs) > MAX_SOURCES or sum(len(tools) for _, tools in catalogs) > 500:
                raise HarnessError("Codex tool discovery exceeds the collection limits.")
        cursor = page.get("nextCursor")
        if cursor is None:
            return catalogs
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise HarnessError("Codex returned invalid server pagination.")
        seen.add(cursor)
    raise HarnessError("Codex server discovery exceeds the page limit.")


def fetch(store: GuardStore, source_id: str, config_digest: str,
          project_dir: str | None = None) -> dict[str, Any]:
    project = _project(project_dir)
    sources, _ = _sources(project)
    source = next((item for item in sources if item.source_id == source_id), None)
    if source is None or source.digest != config_digest:
        raise HarnessError("The harness configuration changed. Scan again before connecting.")
    try:
        config = _config(source)
    except (TypeError, ValueError, OSError, TransportError) as error:
        if isinstance(error, HarnessError):
            raise
        raise HarnessError("The selected configuration is unavailable or unsupported. Scan again.") from None
    peer: StdioPeer | HttpPeer | None = None
    deadline = time.monotonic() + FETCH_SECONDS
    try:
        if source.kind == "runtime" and source.harness == "codex":
            peer = _CodexPeer(config)
        else:
            peer = _DiscoveryStdioPeer(config) if isinstance(config, StdioConfig) else _DiscoveryHttpPeer(config)
        peer.collection_deadline = deadline
        peer.initialize()
        catalogs = (_codex_catalogs(peer, deadline) if isinstance(peer, _CodexPeer) else
                    [(source.name, _catalog(peer, deadline))])
        # Treat configured secret values as non-exportable; do not put them in
        # definitions, audit records, or renderer responses if a server echoes one.
        secrets = []
        if isinstance(config, StdioConfig):
            secrets.extend(value for key, value in config.environment().items() if key not in SAFE_ENV)
        elif token := config.token():
            secrets.append(token)
        encoded = exact_json([[name, tools] for name, tools in catalogs])
        if any(len(secret) >= 8 and (secret in encoded or json.dumps(secret)[1:-1] in encoded) for secret in secrets):
            raise HarnessError("A server echoed a configured credential. Its definitions were not saved.")
        # Validate every catalog before saving any, so pagination/validation errors
        # never replace a previous complete observation with a partial catalog.
        for _, tools in catalogs:
            store._validate_catalog(tools)
        # Re-read the selection after discovery; concurrent config edits invalidate it.
        current, _ = _sources(project)
        if not any(item.source_id == source_id and item.digest == config_digest for item in current):
            raise HarnessError("The harness configuration changed during collection. Scan again.")
        records = []
        for name, tools in catalogs:
            suffix = hashlib.sha256(name.encode()).hexdigest()[:16]
            label = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:48]
            server_id = f"harness:{source.harness}:{label}:{source.source_id[:24]}:{suffix}"
            fingerprint = hashlib.sha256(exact_json([peer.identity.fingerprint, config_digest]).encode()).hexdigest()
            identity = ServerIdentity(server_id, fingerprint,
                                      "harness-review-only", peer.identity.protocol_version,
                                      f"{source.harness}: {name}")
            store.register_server(identity)
            records.extend(store.ingest_catalog(server_id, tools, identity=identity))
        return {"servers": len(catalogs), "tools": len(records), "source_id": source_id,
                "server_ids": sorted({record["server_id"] for record in records}),
                "scope": "Definitions collected for review. Harness execution is not mediated."}
    except (TransportError, OSError):
        raise HarnessError("Could not collect definitions. Check the harness version, executable, server availability and authentication.") from None
    finally:
        if peer is not None:
            peer.close()
