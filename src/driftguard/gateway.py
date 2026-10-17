"""Opt-in host-side consent gate. This module does not intercept other applications."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, TypeVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .baselines import rule_baseline
from .canonicalize import exact_hash, exact_json, make_snapshot
from .diff import build_delta
from .features import extract_pair_features
from .models import ChangeClass
from .temporal import SequentialDriftMonitor

T = TypeVar("T")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class GateError(ValueError):
    """A request could not be safely authorized."""


class IdentityMismatch(GateError):
    """A stale connection attempted to alter another configured identity's state."""


@dataclass(frozen=True)
class ServerIdentity:
    server_id: str
    fingerprint: str
    auth_context: str
    protocol_version: str = "2026-07-28"
    display_name: str = ""

    def __post_init__(self) -> None:
        for name in ("server_id", "fingerprint", "auth_context", "protocol_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 1024:
                raise GateError(f"{name} must be a nonempty bounded identifier")


@dataclass(frozen=True)
class GuardPolicy:
    revision: str = "exact-consent-v1"
    max_catalog_tools: int = 500
    max_tool_bytes: int = 65536
    max_catalog_bytes: int = 2097152
    max_depth: int = 48

    def __post_init__(self) -> None:
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise GateError("A policy revision is required")
        for value in (
            self.max_catalog_tools,
            self.max_tool_bytes,
            self.max_catalog_bytes,
            self.max_depth,
        ):
            if type(value) is not int or value < 1:
                raise GateError("Policy limits must be positive integers")


@dataclass(frozen=True)
class CallPermit:
    server_id: str
    tool_name: str
    sha256: str
    revision: int
    server_revision: int
    policy_revision: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check_depth(value: Any, limit: int, depth: int = 0) -> None:
    if depth > limit:
        raise GateError("Tool definition exceeds the nesting limit")
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, limit, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, limit, depth + 1)


def _prepare_database_file(path: Path) -> None:
    """Create only our new state paths privately; preserve permissions on existing paths."""

    missing: list[Path] = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        if parent == parent.parent:
            raise GateError("Database directory has no existing ancestor")
        parent = parent.parent
    if not parent.is_dir():
        raise GateError("Database parent must be a directory")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise GateError("Database parent must be a directory") from None

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise GateError("Database path must be a regular file, never a symlink") from None
    else:
        os.close(descriptor)


class GuardStore:
    """SQLite-backed trust state for explicitly integrated hosts.

    Trust covers an observed definition and configured identity, not server behavior.
    The database and the application supplying identity bindings are trusted locally.
    """

    def __init__(self, path: str | Path = ":memory:", *, policy: GuardPolicy | None = None) -> None:
        self.policy = policy or GuardPolicy()
        self._healthy = True
        self._lock = threading.RLock()
        if str(path) != ":memory:":
            _prepare_database_file(Path(path))
        self._db = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS guard_runtime(
                server_id TEXT PRIMARY KEY, heartbeat_at TEXT NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS guard_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS guard_servers(
                server_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, auth_context TEXT NOT NULL,
                protocol_version TEXT NOT NULL, display_name TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1, catalog_valid INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS guard_tools(
                server_id TEXT NOT NULL REFERENCES guard_servers(server_id), tool_name TEXT NOT NULL,
                definition TEXT NOT NULL, sha256 TEXT NOT NULL, semantic_hash TEXT NOT NULL,
                status TEXT NOT NULL, classification TEXT NOT NULL, reasons TEXT NOT NULL,
                temporal TEXT NOT NULL, revision INTEGER NOT NULL, observed_at TEXT NOT NULL,
                present INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(server_id,tool_name));
            CREATE TABLE IF NOT EXISTS guard_approvals(
                id INTEGER PRIMARY KEY, server_id TEXT NOT NULL, tool_name TEXT NOT NULL,
                sha256 TEXT NOT NULL, definition TEXT NOT NULL, fingerprint TEXT NOT NULL,
                auth_context TEXT NOT NULL, protocol_version TEXT NOT NULL, policy_revision TEXT NOT NULL,
                approved_at TEXT NOT NULL, actor TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS guard_quarantines(
                server_id TEXT NOT NULL, tool_name TEXT NOT NULL, sha256 TEXT NOT NULL,
                PRIMARY KEY(server_id,tool_name,sha256));
            CREATE TABLE IF NOT EXISTS guard_history(
                id INTEGER PRIMARY KEY, server_id TEXT NOT NULL, tool_name TEXT NOT NULL,
                sha256 TEXT NOT NULL, definition TEXT NOT NULL, revision INTEGER NOT NULL,
                observed_at TEXT NOT NULL, classification TEXT NOT NULL, reasons TEXT NOT NULL,
                temporal TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS guard_events(
                id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, server_id TEXT,
                tool_name TEXT, timestamp TEXT NOT NULL, details TEXT NOT NULL);
        """)
        with self._transaction():
            stored = self._db.execute("SELECT value FROM guard_meta WHERE key='policy'").fetchone()
            if stored:
                if policy is None:
                    self.policy = replace(self.policy, revision=stored[0])
                elif stored[0] != self.policy.revision:
                    raise GateError("Stored policy differs; use set_policy_revision explicitly")
            else:
                self._db.execute(
                    "INSERT INTO guard_meta VALUES('policy',?)", (self.policy.revision,)
                )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            nested = self._db.in_transaction
            if not nested:
                self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                if not nested:
                    self._db.rollback()
                raise
            else:
                if not nested:
                    self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _event(
        self,
        event_type: str,
        server_id: str | None = None,
        tool_name: str | None = None,
        **details: Any,
    ) -> None:
        self._db.execute(
            "INSERT INTO guard_events(event_type,server_id,tool_name,timestamp,details) VALUES(?,?,?,?,?)",
            (event_type, server_id, tool_name, _now(), exact_json(details)),
        )

    def record_event(
        self,
        event_type: str,
        server_id: str | None = None,
        tool_name: str | None = None,
        **details: Any,
    ) -> None:
        """Record bounded metadata; callers must not pass raw arguments, results or secrets."""
        if len(exact_json(details).encode("utf-8")) > 8192:
            raise GateError("Audit metadata is too large")
        with self._transaction():
            self._event(event_type, server_id, tool_name, **details)

    def _server(self, server_id: str) -> sqlite3.Row:
        row = self._db.execute(
            "SELECT * FROM guard_servers WHERE server_id=?", (server_id,)
        ).fetchone()
        if row is None:
            raise GateError("Unknown configured server")
        return row

    def _require_policy(self) -> None:
        if not self._healthy:
            raise GateError("Trust store is unavailable after an invalidation failure")
        row = self._db.execute("SELECT value FROM guard_meta WHERE key='policy'").fetchone()
        if row is None or row[0] != self.policy.revision:
            raise GateError("Active policy changed; reopen the trust store")

    def register_server(self, identity: ServerIdentity) -> dict[str, Any]:
        with self._transaction():
            self._require_policy()
            old = self._db.execute(
                "SELECT * FROM guard_servers WHERE server_id=?", (identity.server_id,)
            ).fetchone()
            binding = (identity.fingerprint, identity.auth_context, identity.protocol_version)
            if old is None:
                self._db.execute(
                    "INSERT INTO guard_servers(server_id,fingerprint,auth_context,protocol_version,"
                    "display_name) VALUES(?,?,?,?,?)",
                    (identity.server_id, *binding, identity.display_name or identity.server_id),
                )
                self._event("server_registered", identity.server_id)
            else:
                if binding != (old["fingerprint"], old["auth_context"], old["protocol_version"]):
                    self._invalidate_server(
                        identity.server_id, "Server identity or authorization changed"
                    )
                    self._db.execute("DELETE FROM guard_runtime WHERE server_id=?",
                                     (identity.server_id,))
                self._db.execute(
                    "UPDATE guard_servers SET fingerprint=?,auth_context=?,protocol_version=?,"
                    "display_name=? WHERE server_id=?",
                    (*binding, identity.display_name or identity.server_id, identity.server_id),
                )
            return dict(self._server(identity.server_id))

    def mark_gateway(self, identity: ServerIdentity, *, active: bool) -> None:
        """Record process heartbeat metadata; this never grants or proves consent."""
        if type(active) is not bool:
            raise TypeError("Gateway activity must be boolean")
        with self._transaction():
            server = self._server(identity.server_id)
            if (identity.fingerprint, identity.auth_context, identity.protocol_version) != (
                server["fingerprint"], server["auth_context"], server["protocol_version"]
            ):
                raise IdentityMismatch("Heartbeat connection identity is no longer current")
            self._db.execute(
                "INSERT INTO guard_runtime VALUES(?,?,?) ON CONFLICT(server_id) DO UPDATE SET "
                "heartbeat_at=excluded.heartbeat_at,active=excluded.active",
                (identity.server_id, _now(), int(active)),
            )

    def gateway_health(self) -> list[dict[str, Any]]:
        """Historical heartbeats, not proof of upstream health or client routing."""
        with self._lock:
            return [dict(row) for row in self._db.execute(
                "SELECT r.server_id,r.heartbeat_at,r.active FROM guard_runtime r "
                "JOIN guard_servers s ON s.server_id=r.server_id ORDER BY r.server_id"
            )]

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(row)
                for row in self._db.execute("SELECT * FROM guard_servers ORDER BY server_id")
            ]

    def _invalidate_server(self, server_id: str, reason: str) -> None:
        self._server(server_id)
        self._db.execute(
            "UPDATE guard_servers SET catalog_valid=0,revision=revision+1 WHERE server_id=?",
            (server_id,),
        )
        self._db.execute(
            "UPDATE guard_tools SET status='revoked',revision=revision+1 WHERE server_id=?",
            (server_id,),
        )
        self._db.execute("UPDATE guard_approvals SET active=0 WHERE server_id=?", (server_id,))
        self._event("server_invalidated", server_id, reason=reason)

    def invalidate_server(
        self,
        server_id: str,
        reason: str = "Catalog invalidated",
        *,
        identity: ServerIdentity | None = None,
    ) -> None:
        with self._transaction():
            server = self._server(server_id)
            if identity and (
                identity.server_id,
                identity.fingerprint,
                identity.auth_context,
                identity.protocol_version,
            ) != (
                server_id,
                server["fingerprint"],
                server["auth_context"],
                server["protocol_version"],
            ):
                raise IdentityMismatch("Invalidation connection identity is no longer current")
            self._invalidate_server(server_id, reason)

    def _invalidate_all(self, reason: str) -> None:
        for row in self._db.execute("SELECT server_id FROM guard_servers").fetchall():
            self._invalidate_server(row[0], reason)

    def set_policy_revision(self, revision: str) -> None:
        if not isinstance(revision, str) or not revision.strip():
            raise GateError("A nonempty policy revision is required")
        with self._transaction():
            self._invalidate_all("Policy revision changed")
            self._db.execute("INSERT OR REPLACE INTO guard_meta VALUES('policy',?)", (revision,))
            self.policy = GuardPolicy(
                revision=revision,
                max_catalog_tools=self.policy.max_catalog_tools,
                max_tool_bytes=self.policy.max_tool_bytes,
                max_catalog_bytes=self.policy.max_catalog_bytes,
                max_depth=self.policy.max_depth,
            )

    def _validate_catalog(self, tools: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
        if not isinstance(tools, list) or len(tools) > self.policy.max_catalog_tools:
            raise GateError("Catalog must be a bounded complete list")
        checked = []
        names: set[str] = set()
        total_bytes = 0
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise GateError("Each tool requires a string name")
            name = tool["name"]
            if not _NAME.fullmatch(name) or name in names:
                raise GateError("Tool names must be unique bounded MCP identifiers")
            if not isinstance(tool.get("inputSchema"), dict):
                raise GateError("Each tool requires an inputSchema JSON object")
            if "outputSchema" in tool and not isinstance(tool["outputSchema"], dict):
                raise GateError("outputSchema must be a JSON object")
            if "description" in tool and not isinstance(tool["description"], str):
                raise GateError("description must be text")
            if "annotations" in tool and not isinstance(tool["annotations"], dict):
                raise GateError("annotations must be a JSON object")
            _check_depth(tool, self.policy.max_depth)
            encoded = exact_json(tool)
            size = len(encoded.encode("utf-8"))
            total_bytes += size
            if size > self.policy.max_tool_bytes or total_bytes > self.policy.max_catalog_bytes:
                raise GateError("Tool catalog exceeds the size limit")
            for schema_name in ("inputSchema", "outputSchema"):
                schema = tool.get(schema_name)
                if schema is None:
                    continue
                declared = schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
                if declared not in {
                    "https://json-schema.org/draft/2020-12/schema",
                    "https://json-schema.org/draft/2020-12/schema#",
                }:
                    raise GateError("Only JSON Schema 2020-12 is supported by this gateway")
                try:
                    # Check against the bundled metaschema, never against user arguments.
                    # Disable formats so attacker regex patterns are not evaluated/compiled.
                    Draft202012Validator.check_schema(schema, format_checker=None)
                except SchemaError as error:
                    raise GateError(
                        f"{schema_name} is not a valid JSON Schema 2020-12 object"
                    ) from error
            checked.append((json.loads(encoded), encoded))
            names.add(name)
        return checked

    def _active_approval(
        self, server: sqlite3.Row, tool_name: str, *, include_inactive: bool = False
    ) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM guard_approvals WHERE server_id=? AND tool_name=? AND (? OR active=1) "
            "AND fingerprint=? AND auth_context=? AND protocol_version=? AND policy_revision=? "
            "ORDER BY id DESC LIMIT 1",
            (
                server["server_id"],
                tool_name,
                int(include_inactive),
                server["fingerprint"],
                server["auth_context"],
                server["protocol_version"],
                self.policy.revision,
            ),
        ).fetchone()

    def _assess(
        self,
        server: sqlite3.Row,
        tool: dict[str, Any],
        previous: sqlite3.Row | None,
        *,
        allow_scoring: bool = True,
    ) -> tuple[str, list[str], dict[str, Any]]:
        # Revoking invocation authority must not erase historical comparison evidence.
        approval = self._active_approval(server, tool["name"], include_inactive=True)
        if approval is None:
            return "unreviewed", ["No approved definition exists for this identity and policy."], {}
        if not allow_scoring or (
            max(
                len(exact_json(tool).encode("utf-8")),
                len(approval["definition"].encode("utf-8")),
                len(previous["definition"].encode("utf-8")) if previous else 0,
            )
            > 8192
        ):
            return (
                "C2",
                [
                    (
                        "Exact definition changed; the comparison budget requires manual review. "
                        "Lexical and temporal scoring was skipped to bound computation."
                    )
                ],
                {},
            )
        baseline = make_snapshot(
            server_id=server["server_id"], tool=json.loads(approval["definition"])
        )
        current = make_snapshot(server_id=server["server_id"], tool=tool)
        assessment = rule_baseline(build_delta(baseline, current))
        monitor = SequentialDriftMonitor(baseline)
        if previous:
            monitor.previous = make_snapshot(
                server_id=server["server_id"], tool=json.loads(previous["definition"])
            )
            past = json.loads(previous["temporal"])
            monitor.cusum_score = float(past.get("cusum_score", 0.0))
            monitor.versions_seen = int(past.get("versions_seen", 1))
        temporal = monitor.observe(current).model_dump(mode="json")
        reasons = assessment.reasons + temporal["reasons"]
        classification = assessment.change_class.value
        if temporal["alerted"]:
            classification = ChangeClass.MALICIOUS_DRIFT.value
        return classification, reasons, temporal

    def ingest_catalog(
        self, server_id: str, tools: list[dict[str, Any]], *, identity: ServerIdentity | None = None
    ) -> list[dict[str, Any]]:
        """Atomically ingest a complete catalog. Any failure invalidates prior invocation trust."""
        try:
            with self._transaction():
                self._require_policy()
                server = self._server(server_id)
                if identity and (
                    identity.server_id,
                    identity.fingerprint,
                    identity.auth_context,
                    identity.protocol_version,
                ) != (
                    server_id,
                    server["fingerprint"],
                    server["auth_context"],
                    server["protocol_version"],
                ):
                    raise IdentityMismatch("Catalog connection identity is no longer current")
                checked = self._validate_catalog(tools)
                self._db.execute(
                    "UPDATE guard_servers SET revision=revision+1 WHERE server_id=?", (server_id,)
                )
                self._db.execute("UPDATE guard_tools SET present=0 WHERE server_id=?", (server_id,))
                scored_bytes = 0
                for tool, encoded in checked:
                    name = tool["name"]
                    digest = exact_hash(tool)
                    old = self._db.execute(
                        "SELECT * FROM guard_tools WHERE server_id=? AND tool_name=?",
                        (server_id, name),
                    ).fetchone()
                    if old and old["sha256"] == digest:
                        # Reobservation neither resets a denial nor accumulates fake drift.
                        self._db.execute(
                            "UPDATE guard_tools SET present=1,observed_at=? "
                            "WHERE server_id=? AND tool_name=?",
                            (_now(), server_id, name),
                        )
                        continue
                    scored_bytes += len(encoded.encode("utf-8")) + (
                        len(old["definition"].encode("utf-8")) if old else 0
                    )
                    classification, reasons, temporal = self._assess(
                        server, tool, old, allow_scoring=scored_bytes <= 65536
                    )
                    status = "quarantined" if classification == "C3" else "pending"
                    if status == "quarantined":
                        self._db.execute(
                            "INSERT OR IGNORE INTO guard_quarantines VALUES(?,?,?)",
                            (server_id, name, digest),
                        )
                    revision = old["revision"] + 1 if old else 1
                    observed = _now()
                    semantic_hash = make_snapshot(server_id=server_id, tool=tool).sha256
                    values = (
                        server_id,
                        name,
                        encoded,
                        digest,
                        semantic_hash,
                        status,
                        classification,
                        exact_json(reasons),
                        exact_json(temporal),
                        revision,
                        observed,
                    )
                    self._db.execute(
                        "INSERT OR REPLACE INTO guard_tools(server_id,tool_name,definition,"
                        "sha256,semantic_hash,status,classification,reasons,temporal,revision,"
                        "observed_at,present) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                        values,
                    )
                    self._db.execute(
                        "INSERT INTO guard_history(server_id,tool_name,sha256,definition,"
                        "revision,observed_at,classification,reasons,temporal) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            server_id,
                            name,
                            digest,
                            encoded,
                            revision,
                            observed,
                            classification,
                            exact_json(reasons),
                            exact_json(temporal),
                        ),
                    )
                    self._event(
                        "definition_observed",
                        server_id,
                        name,
                        sha256=digest,
                        status=status,
                        revision=revision,
                    )
                # Removal revokes consent so remove/re-add cannot silently resurrect approval.
                self._db.execute(
                    "UPDATE guard_approvals SET active=0 WHERE server_id=? AND tool_name IN "
                    "(SELECT tool_name FROM guard_tools WHERE server_id=? AND present=0)",
                    (server_id, server_id),
                )
                self._db.execute(
                    "UPDATE guard_tools SET status='revoked',revision=revision+1 "
                    "WHERE server_id=? AND present=0 AND status!='revoked'",
                    (server_id,),
                )
                self._db.execute(
                    "UPDATE guard_servers SET catalog_valid=1 WHERE server_id=?", (server_id,)
                )
                self._event("catalog_observed", server_id, tools=len(checked))
        except Exception as error:
            if isinstance(error, IdentityMismatch):
                # No state was changed. A stale connection cannot revoke the new binding.
                raise
            try:
                self.invalidate_server(server_id, "Catalog validation or assessment failed")
            except Exception as invalidation_error:
                self._healthy = False
                raise GateError(
                    "Unable to persist trust invalidation; this store is disabled"
                ) from invalidation_error
            if isinstance(error, GateError):
                raise
            raise GateError("Catalog could not be safely assessed") from error
        return self.list_tools(server_id)

    def _tool(self, server_id: str, tool_name: str) -> sqlite3.Row:
        row = self._db.execute(
            "SELECT * FROM guard_tools WHERE server_id=? AND tool_name=?", (server_id, tool_name)
        ).fetchone()
        if row is None:
            raise GateError("Unknown observed tool")
        if exact_hash(json.loads(row["definition"])) != row["sha256"]:
            raise GateError("Stored tool definition failed its integrity check")
        return row

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        definition = json.loads(record.pop("definition"))
        record.update(
            definition=definition,
            new_tool=definition,
            exact_hash=record["sha256"],
            state=record["status"],
            description=definition.get("description", ""),
        )
        for field in ("reasons", "temporal"):
            record[field] = json.loads(record[field])
        return record

    def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            sql = "SELECT * FROM guard_tools WHERE present=1"
            args: tuple[str, ...] = ()
            if server_id is not None:
                sql += " AND server_id=?"
                args = (server_id,)
            return [
                self._record(row)
                for row in self._db.execute(sql + " ORDER BY server_id,tool_name", args)
            ]

    def get_tool(self, server_id: str, tool_name: str) -> dict[str, Any]:
        with self._lock:
            row = self._tool(server_id, tool_name)
            record = self._record(row)
            approval = self._active_approval(
                self._server(server_id), tool_name, include_inactive=True
            )
            record["old_tool"] = json.loads(approval["definition"]) if approval else None
            if (
                approval
                and max(
                    len(row["definition"].encode("utf-8")),
                    len(approval["definition"].encode("utf-8")),
                )
                <= 8192
            ):
                old = make_snapshot(server_id=server_id, tool=record["old_tool"])
                new = make_snapshot(server_id=server_id, tool=record["definition"])
                record["capability_delta"] = extract_pair_features(
                    build_delta(old, new)
                ).capability_delta.model_dump()
            else:
                record["capability_delta"] = {}
            return record

    def _review(
        self,
        server_id: str,
        tool_name: str,
        action: str,
        *,
        expected_hash: str,
        expected_revision: int | None = None,
        actor: str = "local-user",
    ) -> dict[str, Any]:
        with self._transaction():
            self._require_policy()
            server = self._server(server_id)
            row = self._tool(server_id, tool_name)
            if type(expected_revision) is not int:
                raise GateError("An exact current review revision is required")
            if row["sha256"] != expected_hash or (
                expected_revision is not None and row["revision"] != expected_revision
            ):
                raise GateError("Review is stale; reload the current tool definition")
            if not row["present"] or not server["catalog_valid"]:
                raise GateError("A complete current catalog is required for review")
            previously_quarantined = self._db.execute(
                "SELECT 1 FROM guard_quarantines WHERE server_id=? AND tool_name=? AND sha256=?",
                (server_id, tool_name, row["sha256"]),
            ).fetchone()
            if action == "approved" and (row["status"] == "quarantined" or previously_quarantined):
                raise GateError("Quarantined definitions cannot be approved")
            if action == "quarantined":
                self._db.execute(
                    "INSERT OR IGNORE INTO guard_quarantines VALUES(?,?,?)",
                    (server_id, tool_name, row["sha256"]),
                )
            self._db.execute(
                "UPDATE guard_approvals SET active=0 WHERE server_id=? AND tool_name=?",
                (server_id, tool_name),
            )
            if action == "approved":
                self._db.execute(
                    "INSERT INTO guard_approvals(server_id,tool_name,sha256,definition,"
                    "fingerprint,auth_context,protocol_version,policy_revision,approved_at,actor) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        server_id,
                        tool_name,
                        expected_hash,
                        row["definition"],
                        server["fingerprint"],
                        server["auth_context"],
                        server["protocol_version"],
                        self.policy.revision,
                        _now(),
                        actor,
                    ),
                )
            self._db.execute(
                "UPDATE guard_tools SET status=?,revision=revision+1,temporal=? "
                "WHERE server_id=? AND tool_name=?",
                (action, "{}", server_id, tool_name),
            )
            self._event("tool_" + action, server_id, tool_name, sha256=expected_hash, actor=actor)
        return self.get_tool(server_id, tool_name)

    def approve(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        expected_revision: int | None = None,
        actor: str = "local-user",
    ) -> dict[str, Any]:
        return self._review(
            server_id,
            tool_name,
            "approved",
            expected_hash=expected_hash,
            expected_revision=expected_revision,
            actor=actor,
        )

    def deny(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        expected_revision: int | None = None,
        actor: str = "local-user",
    ) -> dict[str, Any]:
        return self._review(
            server_id,
            tool_name,
            "denied",
            expected_hash=expected_hash,
            expected_revision=expected_revision,
            actor=actor,
        )

    def revoke(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        expected_revision: int | None = None,
        actor: str = "local-user",
    ) -> dict[str, Any]:
        return self._review(
            server_id,
            tool_name,
            "revoked",
            expected_hash=expected_hash,
            expected_revision=expected_revision,
            actor=actor,
        )

    def quarantine(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        expected_revision: int | None = None,
        actor: str = "local-user",
    ) -> dict[str, Any]:
        return self._review(
            server_id,
            tool_name,
            "quarantined",
            expected_hash=expected_hash,
            expected_revision=expected_revision,
            actor=actor,
        )

    def authorize_call(
        self,
        server_id: str,
        tool_name: str,
        *,
        expected_hash: str,
        expected_revision: int | None = None,
        identity: ServerIdentity | None = None,
    ) -> CallPermit:
        with self._transaction():
            self._require_policy()
            server = self._server(server_id)
            row = self._tool(server_id, tool_name)
            if type(expected_revision) is not int:
                raise GateError("An exact current invocation revision is required")
            if identity and (
                identity.server_id,
                identity.fingerprint,
                identity.auth_context,
                identity.protocol_version,
            ) != (
                server_id,
                server["fingerprint"],
                server["auth_context"],
                server["protocol_version"],
            ):
                raise GateError("Connection identity no longer matches the configured server")
            if not server["catalog_valid"] or not row["present"] or row["status"] != "approved":
                raise GateError("Tool is not approved in a complete current catalog")
            if row["sha256"] != expected_hash or (
                expected_revision is not None and row["revision"] != expected_revision
            ):
                raise GateError("Invocation uses a stale definition or review revision")
            policy = self._db.execute("SELECT value FROM guard_meta WHERE key='policy'").fetchone()
            if policy is None or policy[0] != self.policy.revision:
                raise GateError("Active policy changed; reload trust state")
            approval = self._active_approval(server, tool_name)
            if approval is None or approval["sha256"] != row["sha256"]:
                raise GateError("Exact approval does not match the current identity and policy")
            return CallPermit(
                server_id,
                tool_name,
                row["sha256"],
                row["revision"],
                server["revision"],
                self.policy.revision,
            )

    def dispatch(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invoke: Callable[[str, dict[str, Any]], T],
        *,
        expected_hash: str,
        expected_revision: int,
        identity: ServerIdentity | None = None,
    ) -> T:
        """Check and dispatch under a local store lock; remote behavior remains unverified."""
        if not isinstance(arguments, dict):
            raise GateError("Tool arguments must be a JSON object")
        safe_arguments = json.loads(exact_json(arguments))
        error: Exception | None = None
        result: Any = None
        with self._transaction():
            self.authorize_call(
                server_id,
                tool_name,
                expected_hash=expected_hash,
                expected_revision=expected_revision,
                identity=identity,
            )
            self._event(
                "call_authorized",
                server_id,
                tool_name,
                sha256=expected_hash,
                revision=expected_revision,
            )
            try:
                result = invoke(tool_name, safe_arguments)
            except Exception as caught:  # noqa: BLE001 - persist callback failure without its content
                error = caught
                self._event("call_failed", server_id, tool_name, error_type=type(caught).__name__)
            else:
                self._event("call_completed", server_id, tool_name)
        if error is not None:
            raise error
        return result

    def history(self, server_id: str, tool_name: str) -> list[dict[str, Any]]:
        with self._lock:
            records = []
            for row in self._db.execute(
                "SELECT * FROM guard_history WHERE server_id=? AND tool_name=? ORDER BY id",
                (server_id, tool_name),
            ):
                item = dict(row)
                for field in ("definition", "reasons", "temporal"):
                    item[field] = json.loads(item[field])
                records.append(item)
            return records

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise GateError("Event limit must be between 1 and 10000")
        with self._lock:
            result = []
            for row in self._db.execute(
                "SELECT * FROM guard_events ORDER BY id DESC LIMIT ?", (limit,)
            ):
                item = dict(row)
                item["details"] = json.loads(item["details"])
                result.append(item)
            return result
