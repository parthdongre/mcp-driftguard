"""Import descriptive hosted-app metadata without impersonating a live MCP session."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .gateway import GuardStore, ServerIdentity


def import_source(store: GuardStore, source: Any) -> dict[str, Any]:
    if not isinstance(source, dict) or set(source) - {
        "source_id", "name", "description", "tools", "captured_at", "visibility",
    }:
        raise ValueError("Invalid hosted catalog source")
    source_id = source.get("source_id")
    name, description, tools = source.get("name"), source.get("description"), source.get("tools")
    if (not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", source_id)
            or not isinstance(name, str) or not 1 <= len(name) <= 200
            or not isinstance(description, str) or len(description) > 16000
            or not isinstance(tools, list) or len(tools) > 500):
        raise ValueError("Invalid hosted catalog fields")
    captured = source.get("captured_at", "")
    visibility = source.get("visibility", "session_tools")
    if not isinstance(captured, str) or len(captured) > 64 or visibility not in {
        "session_tools", "skills_only", "not_exposed",
    }:
        raise ValueError("Invalid hosted catalog provenance")
    if visibility != "session_tools" and tools:
        raise ValueError("Non-tool app entries cannot contain tool descriptions")
    definitions = []
    for tool in tools:
        if (not isinstance(tool, dict) or set(tool) != {"name", "description"}
                or not isinstance(tool["description"], str)):
            raise ValueError("Hosted imports accept tool names and descriptions only")
        definitions.append({"name": tool["name"], "description": tool["description"],
                            "inputSchema": {"type": "object"},
                            "x-driftguard-input-schema": "not-exported",
                            "x-driftguard-origin": "host-metadata-import"})
    store._validate_catalog(definitions)
    server_id = "host:" + source_id
    identity = ServerIdentity(server_id, hashlib.sha256(source_id.encode()).hexdigest(),
                              "host-metadata-review-only", "host-catalog-v1", name)
    metadata = {"server_id": server_id, "source_id": source_id, "name": name,
                "description": description, "captured_at": captured,
                "visibility": visibility, "tools_count": len(definitions),
                "input_schema_status": "not-exported"}
    with store._transaction():
        store.register_server(identity)
        store.ingest_catalog(server_id, definitions, identity=identity)
        store.save_source_metadata(server_id, metadata)
    return metadata


def list_sources(store: GuardStore) -> list[dict[str, Any]]:
    return [{**source, "tools": [{"name": tool["tool_name"], "description": tool["description"]}
                                  for tool in store.list_tools(source["server_id"])]}
            for source in store.source_metadata() if source["server_id"].startswith("host:")]
