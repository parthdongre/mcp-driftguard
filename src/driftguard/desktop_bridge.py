"""One-request JSON bridge for the native desktop shell.

The trusted native host chooses the database path. The renderer can send only
allowlisted operations. Harness collection reads known configuration files and
starts only a freshly discovered selection. No arbitrary executable/file request,
tool call, policy change or HTTP listener is exposed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .canonicalize import exact_hash
from .gateway import GateError, GuardStore, ServerIdentity

MAX_REQUEST_BYTES = 2_100_000
ACTIONS = frozenset({
    "overview", "list_tools", "review", "history", "activity",
    "import_definitions", "approve", "deny", "quarantine",
    "store_http_credential", "remove_http_credential",
    "harness_scan", "harness_fetch",
})


def _reject_constant(_: str) -> None:
    raise ValueError("Non-finite numbers are not JSON")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON object members are not accepted")
        result[name] = value
    return result


def _text(request: dict[str, Any], name: str, *, maximum: int = 1024) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty text within its size limit")
    return value


def handle_request(store: GuardStore, request: dict[str, Any]) -> Any:
    if not isinstance(request, dict) or request.get("action") not in ACTIONS:
        raise ValueError("Unknown desktop action")
    action = request["action"]
    if action in {"harness_scan", "harness_fetch"}:
        from .harnesses import fetch, scan
        allowed = {"action", "project_dir"}
        if action == "harness_fetch":
            allowed |= {"source_id", "config_digest"}
        if set(request) - allowed:
            raise ValueError("Unexpected harness request fields")
        project = request.get("project_dir")
        if project is not None and not isinstance(project, str):
            raise ValueError("Invalid project directory")
        if action == "harness_scan":
            return scan(project)
        return fetch(store, _text(request, "source_id", maximum=64),
                     _text(request, "config_digest", maximum=64), project)
    if action == "overview":
        servers = store.list_servers()
        tools = store.list_tools()
        counts = Counter(tool["status"] for tool in tools)
        # Historical catalog freshness is not a liveness/forwarding health signal.
        recent = store.events(limit=1000)
        last = next((event["timestamp"] for event in recent
                     if event["event_type"] == "catalog_observed"), None)
        return {
            "protection_status": "review_only", "servers": len(servers), "tools": len(tools),
            "pending": counts["pending"], "approved": counts["approved"],
            "quarantined": counts["quarantined"], "last_verification": last,
            "server_list": servers,
            "gateway_health": store.gateway_health(),
            "scope": "Only clients explicitly configured to route through the gateway are "
                     "protected. Imported definitions are review-only. Desktop status does "
                     "not establish that a gateway process is running.",
            "research": {"paper_claim_eligible": False, "human_labels_verified": False,
                         "cloud_analysis_enabled": False},
        }
    if action == "list_tools":
        server_id = request.get("server_id")
        if server_id is not None:
            server_id = _text(request, "server_id")
        return store.list_tools(server_id)
    if action == "activity":
        return [{**event, "event": event["event_type"], "detail": event["details"]}
                for event in store.events(limit=request.get("limit", 200))]
    server_id = _text(request, "server_id")
    if action == "import_definitions":
        identity = _text(request, "identity")
        tools = request.get("tools")
        # Manual imports cannot replace a live/configured server identity. They use
        # a separate namespace; importing an identical name is never live consent.
        if not server_id.startswith("import:"):
            server_id = "import:" + server_id
        store.register_server(ServerIdentity(
            server_id=server_id, fingerprint=identity, auth_context="manual-import",
            protocol_version="2026-07-28", display_name=server_id.removeprefix("import:"),
        ))
        return store.ingest_catalog(server_id, tools)
    if action in {"store_http_credential", "remove_http_credential"}:
        from .credentials import CredentialError, write
        from .gateway_http import HttpConfig
        endpoint = _text(request, "url", maximum=4096)
        HttpConfig(server_id, endpoint)  # Native credential setup requires HTTPS.
        secret = _text(request, "secret", maximum=2048) if action == "store_http_credential" else None
        try:
            write(server_id, endpoint, secret)
        except CredentialError:
            return {"stored": False, "available": False,
                    "message": "Unlock the OS credential store; no plaintext fallback is used."}
        return {"stored": secret is not None, "available": True}
    tool_name = _text(request, "tool_name", maximum=128)
    if action == "review":
        return store.get_tool(server_id, tool_name)
    if action == "history":
        baseline = store.get_tool(server_id, tool_name).get("old_tool")
        baseline_hash = exact_hash(baseline) if baseline else None
        return [{**item, "raw_tool": item["definition"],
                 "status": "approved_reference" if item["sha256"] == baseline_hash else "observed",
                 "description": item["definition"].get("description", ""),
                 **item.get("temporal", {})}
                for item in store.history(server_id, tool_name)]
    digest = _text(request, "expected_sha256", maximum=64)
    revision = request.get("expected_revision")
    if type(revision) is not int or revision < 1:
        raise ValueError("expected_revision is required; reload the current review")
    return getattr(store, action)(
        server_id, tool_name, expected_hash=digest, expected_revision=revision,
        actor="desktop-user",
    )


def execute(db_path: str | Path, raw: bytes) -> dict[str, Any]:
    """Bound input, reject ambiguous JSON, and return safe structured errors."""
    from .harnesses import HarnessError
    try:
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("Desktop request is empty or exceeds the size limit")
        request = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                             object_pairs_hook=_unique_object)
        with GuardStore(db_path) as store:
            data = handle_request(store, request)
        return {"ok": True, "data": data}
    except HarnessError as error:
        return {"ok": False, "error": {"code": "harness_unavailable", "message": str(error)}}
    except GateError as error:
        return {"ok": False, "error": {"code": "review_rejected", "message": str(error)}}
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        # Avoid echoing arbitrary untrusted parser text or submitted definitions.
        return {"ok": False, "error": {"code": "invalid_request",
                                        "message": "Invalid desktop request; check the fields and reload."}}
    except (sqlite3.Error, OSError):
        return {"ok": False, "error": {"code": "storage_unavailable",
                                        "message": "The local review store is unavailable."}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    result = execute(args.db, raw)
    # The IPC contract is UTF-8 bytes, independent of a Windows/locale text codec.
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
