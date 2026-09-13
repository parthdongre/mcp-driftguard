from __future__ import annotations

from typing import Any


def extract_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool definitions from a tools/list result or a JSON-RPC response."""

    candidate = payload.get("result", payload)
    if not isinstance(candidate, dict):
        return []

    tools = candidate.get("tools", [])
    if not isinstance(tools, list):
        return []

    return [tool for tool in tools if isinstance(tool, dict)]
