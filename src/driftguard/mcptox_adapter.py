from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .dataset import PairDatasetRecord
from .models import ChangeClass

_TOOL_NAME_RE = re.compile(r"Tool:\s*(?P<name>[^\n]+)")
_TOOL_DESC_RE = re.compile(r"Description:\s*(?P<description>.*?)(?:\nArguments:|\Z)", re.DOTALL)


@dataclass(frozen=True)
class MCPToxAttack:
    source_id: str
    server_name: str
    tool_name: str
    poisoned_description: str
    paradigm: str | None
    security_risk: str | None
    query: str | None


def _parse_poisoned_tool(value: str) -> tuple[str, str]:
    text = value.replace("\\n", "\n").replace("\\t", "\t").strip()
    name_match = _TOOL_NAME_RE.search(text)
    if name_match is None:
        raise ValueError("MCPTox poisoned_tool block does not contain a Tool name")
    description_match = _TOOL_DESC_RE.search(text)
    return (
        name_match.group("name").strip(),
        description_match.group("description").strip() if description_match else "",
    )


def parse_mcptox_response_all(payload: Mapping[str, Any]) -> list[MCPToxAttack]:
    """Parse MCPTox's released `response_all.json` without inventing trusted baselines.

    The official release is an attack benchmark and exposes poisoned tool definitions.
    It is not itself a version-history dataset. This parser therefore returns attack
    records first; conversion to DriftGuard old/new pairs is a separate operation that
    requires an independently recovered authentic baseline for the same server/tool.
    """

    servers = payload.get("servers")
    if not isinstance(servers, Mapping):
        raise TypeError("MCPTox payload must contain an object-valued 'servers' field")

    attacks: list[MCPToxAttack] = []
    source_index = 0
    for server_name, raw_server in servers.items():
        if not isinstance(raw_server, Mapping):
            continue
        instances = raw_server.get("malicious_instance", [])
        if not isinstance(instances, list):
            continue
        for instance in instances:
            if not isinstance(instance, Mapping) or instance.get("wrong_data"):
                continue
            poisoned_tool = instance.get("poisoned_tool")
            if not isinstance(poisoned_tool, str):
                continue
            tool_name, poisoned_description = _parse_poisoned_tool(poisoned_tool)
            metadata = instance.get("metadata")
            metadata = metadata if isinstance(metadata, Mapping) else {}
            datas = instance.get("datas")
            query = None
            if isinstance(datas, list) and datas and isinstance(datas[0], Mapping):
                raw_query = datas[0].get("query")
                query = str(raw_query) if raw_query is not None else None
            attacks.append(
                MCPToxAttack(
                    source_id=f"mcptox-{source_index:04d}",
                    server_name=str(server_name),
                    tool_name=tool_name,
                    poisoned_description=poisoned_description,
                    paradigm=(
                        str(metadata.get("paradigm"))
                        if metadata.get("paradigm") is not None
                        else None
                    ),
                    security_risk=(
                        str(metadata.get("security risk"))
                        if metadata.get("security risk") is not None
                        else None
                    ),
                    query=query,
                )
            )
            source_index += 1
    return attacks


def pair_mcptox_with_trusted_baselines(
    attacks: list[MCPToxAttack],
    baselines: Mapping[tuple[str, str], dict[str, Any]],
) -> tuple[list[PairDatasetRecord], list[MCPToxAttack]]:
    """Create independent malicious version pairs only when a real baseline is available.

    `baselines` must be keyed by `(server_name, tool_name)` and should come from the
    authentic MCP server/package or a verifiable historical revision. We deliberately do
    not construct a fake empty/neutral old description because doing so would make the
    resulting external benchmark scientifically misleading.
    """

    paired: list[PairDatasetRecord] = []
    missing: list[MCPToxAttack] = []
    for attack in attacks:
        trusted = baselines.get((attack.server_name, attack.tool_name))
        if trusted is None:
            missing.append(attack)
            continue
        candidate = dict(trusted)
        candidate["description"] = attack.poisoned_description
        candidate.setdefault("name", attack.tool_name)
        paired.append(
            PairDatasetRecord(
                record_id=f"external:mcptox:{attack.source_id}",
                repository_id=f"external/mcptox/{attack.server_name}",
                server_id=attack.server_name,
                tool_name=attack.tool_name,
                old_tool=dict(trusted),
                new_tool=candidate,
                label=ChangeClass.MALICIOUS_DRIFT,
                provenance="synthetic_attack",
                attack_family=f"external/mcptox/{attack.paradigm or 'unknown'}",
                notes=(
                    "MCPTox external attack paired with an independently recovered authentic "
                    f"baseline; security_risk={attack.security_risk or 'unknown'}."
                ),
            )
        )
    return paired, missing
