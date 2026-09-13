from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from ..models import ToolSnapshot

ToolKey = tuple[str, str]


class SnapshotStore(Protocol):
    """Storage boundary used by the runtime; durable stores can implement this later."""

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
