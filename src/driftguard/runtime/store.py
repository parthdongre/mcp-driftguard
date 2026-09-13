from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Protocol

from ..models import ToolSnapshot
from .audit import ReviewEvent

ToolKey = tuple[str, str]


class SnapshotStore(Protocol):
    """Storage boundary used by the runtime."""

    def get_trusted(self, server_id: str, tool_name: str) -> ToolSnapshot | None: ...

    def put_observed(self, snapshot: ToolSnapshot) -> None: ...

    def get_observed(
        self,
        server_id: str,
        tool_name: str,
        sha256: str,
    ) -> ToolSnapshot | None: ...

    def trust(self, snapshot: ToolSnapshot) -> None: ...

    def history(self, server_id: str, tool_name: str) -> list[ToolSnapshot]: ...

    def record_review(self, event: ReviewEvent) -> None: ...

    def reviews(self, server_id: str, tool_name: str) -> list[ReviewEvent]: ...


class InMemorySnapshotStore:
    """Small deterministic store for tests, demos, and local development."""

    def __init__(self) -> None:
        self._trusted: dict[ToolKey, ToolSnapshot] = {}
        self._history: dict[ToolKey, list[ToolSnapshot]] = defaultdict(list)
        self._reviews: dict[ToolKey, list[ReviewEvent]] = defaultdict(list)

    @staticmethod
    def _key(server_id: str, tool_name: str) -> ToolKey:
        return server_id, tool_name

    def get_trusted(self, server_id: str, tool_name: str) -> ToolSnapshot | None:
        return self._trusted.get(self._key(server_id, tool_name))

    def put_observed(self, snapshot: ToolSnapshot) -> None:
        self._history[self._key(snapshot.server_id, snapshot.tool_name)].append(snapshot)

    def get_observed(
        self,
        server_id: str,
        tool_name: str,
        sha256: str,
    ) -> ToolSnapshot | None:
        for snapshot in reversed(self._history.get(self._key(server_id, tool_name), [])):
            if snapshot.sha256 == sha256:
                return snapshot
        return None

    def trust(self, snapshot: ToolSnapshot) -> None:
        self._trusted[self._key(snapshot.server_id, snapshot.tool_name)] = snapshot.model_copy(
            update={"approval_state": "approved"}
        )

    def history(self, server_id: str, tool_name: str) -> list[ToolSnapshot]:
        return list(self._history.get(self._key(server_id, tool_name), []))

    def record_review(self, event: ReviewEvent) -> None:
        self._reviews[self._key(event.server_id, event.tool_name)].append(event)

    def reviews(self, server_id: str, tool_name: str) -> list[ReviewEvent]:
        return list(self._reviews.get(self._key(server_id, tool_name), []))


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

                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    reason TEXT,
                    reviewed_at TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_review_events_tool
                ON review_events(server_id, tool_name, id);
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

    def get_observed(
        self,
        server_id: str,
        tool_name: str,
        sha256: str,
    ) -> ToolSnapshot | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT snapshot_json
                FROM observations
                WHERE server_id = ? AND tool_name = ? AND sha256 = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (server_id, tool_name, sha256),
            ).fetchone()
        if row is None:
            return None
        return ToolSnapshot.model_validate_json(row[0])

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

    def record_review(self, event: ReviewEvent) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO review_events (
                    server_id,
                    tool_name,
                    sha256,
                    decision,
                    reviewer,
                    reason,
                    reviewed_at,
                    event_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.server_id,
                    event.tool_name,
                    event.sha256,
                    event.decision.value,
                    event.reviewer,
                    event.reason,
                    event.reviewed_at.isoformat(),
                    event.model_dump_json(),
                ),
            )

    def reviews(self, server_id: str, tool_name: str) -> list[ReviewEvent]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_json
                FROM review_events
                WHERE server_id = ? AND tool_name = ?
                ORDER BY id ASC
                """,
                (server_id, tool_name),
            ).fetchall()
        return [ReviewEvent.model_validate_json(row[0]) for row in rows]
