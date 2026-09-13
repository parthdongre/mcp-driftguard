from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Protocol

from ..models import ToolSnapshot

ToolKey = tuple[str, str]


class SnapshotStore(Protocol):
    """Storage boundary used by the runtime."""

    def get_trusted(self, server_id: str, tool_name: str) -> ToolSnapshot | None: ...

    def put_observed(self, snapshot: ToolSnapshot) -> None: ...

    def trust(self, snapshot: ToolSnapshot) -> None: ...

    def history(self, server_id: str, tool_name: str) -> list[ToolSnapshot]: ...


class InMemorySnapshotStore:
    """Small deterministic store for tests, demos, and local development."""

    def __init__(self) -> None:
        self._trusted: dict[ToolKey, ToolSnapshot] = {}
        self._history: dict[ToolKey, list[ToolSnapshot]] = defaultdict(list)

    @staticmethod
    def _key(server_id: str, tool_name: str) -> ToolKey:
        return server_id, tool_name

    def get_trusted(self, server_id: str, tool_name: str) -> ToolSnapshot | None:
        return self._trusted.get(self._key(server_id, tool_name))

    def put_observed(self, snapshot: ToolSnapshot) -> None:
        self._history[self._key(snapshot.server_id, snapshot.tool_name)].append(snapshot)

    def trust(self, snapshot: ToolSnapshot) -> None:
        self._trusted[self._key(snapshot.server_id, snapshot.tool_name)] = snapshot.model_copy(
            update={"approval_state": "approved"}
        )

    def history(self, server_id: str, tool_name: str) -> list[ToolSnapshot]:
        return list(self._history.get(self._key(server_id, tool_name), []))


class SQLiteSnapshotStore:
    """Durable local snapshot store backed only by Python's sqlite3 module."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_observations_tool
                ON observations(server_id, tool_name, id);

                CREATE TABLE IF NOT EXISTS trusted_snapshots (
                    server_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    trusted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY (server_id, tool_name)
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get_trusted(self, server_id: str, tool_name: str) -> ToolSnapshot | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT snapshot_json
                FROM trusted_snapshots
                WHERE server_id = ? AND tool_name = ?
                """,
                (server_id, tool_name),
            ).fetchone()
        if row is None:
            return None
        return ToolSnapshot.model_validate_json(row[0])

    def put_observed(self, snapshot: ToolSnapshot) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO observations (
                    server_id, tool_name, sha256, observed_at, snapshot_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.server_id,
                    snapshot.tool_name,
                    snapshot.sha256,
                    snapshot.observed_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )

    def trust(self, snapshot: ToolSnapshot) -> None:
        approved = snapshot.model_copy(update={"approval_state": "approved"})
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO trusted_snapshots (
                    server_id, tool_name, sha256, snapshot_json
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server_id, tool_name) DO UPDATE SET
                    sha256 = excluded.sha256,
                    trusted_at = CURRENT_TIMESTAMP,
                    snapshot_json = excluded.snapshot_json
                """,
                (
                    approved.server_id,
                    approved.tool_name,
                    approved.sha256,
                    approved.model_dump_json(),
                ),
            )

    def history(self, server_id: str, tool_name: str) -> list[ToolSnapshot]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT snapshot_json
                FROM observations
                WHERE server_id = ? AND tool_name = ?
                ORDER BY id ASC
                """,
                (server_id, tool_name),
            ).fetchall()
        return [ToolSnapshot.model_validate_json(row[0]) for row in rows]
