from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from ..graph import CrossToolGraphEvidence, analyze_tool_graph
from ..revisions import SurfaceObservation
from ..runtime import DriftGuardService, EnforcementAction, ObservationResult

_SAFE_FORWARD_ACTIONS = {
    EnforcementAction.ALLOW,
    EnforcementAction.ALLOW_AND_LOG,
}


class ToolsListInterception(BaseModel):
    """Result of applying DriftGuard before tools are exposed to an MCP host/LLM."""

    payload: dict[str, Any]
    observations: list[ObservationResult] = Field(default_factory=list)
    forwarded_tools: list[str] = Field(default_factory=list)
    withheld_tools: list[str] = Field(default_factory=list)
    graph_evidence: CrossToolGraphEvidence | None = None
    surface: SurfaceObservation | None = None


def extract_tools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidate = payload.get("result", payload)
    if not isinstance(candidate, dict):
        return []

    tools = candidate.get("tools", [])
    if not isinstance(tools, list):
        return []

    return [tool for tool in tools if isinstance(tool, dict)]


def _replace_tools(payload: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    forwarded = deepcopy(payload)
    candidate = forwarded.get("result", forwarded)
    if isinstance(candidate, dict):
        candidate["tools"] = deepcopy(tools)
    return forwarded


def intercept_tools_list(
    *,
    payload: dict[str, Any],
    server_id: str,
    service: DriftGuardService,
    protocol_version: str | None = None,
) -> ToolsListInterception:
    """Inspect and version a tools/list response before exposing tools to the host."""

    observations: list[ObservationResult] = []
    forwarded: list[dict[str, Any]] = []
    forwarded_names: list[str] = []
    withheld_names: list[str] = []
    tools = extract_tools(payload)
    graph_evidence = analyze_tool_graph(tools)
    surface = service.observe_surface(
        server_id=server_id,
        tools=tools,
        protocol_version=protocol_version,
    )

    for tool in tools:
        observation = service.observe_tool(
            server_id=server_id,
            tool=tool,
            protocol_version=protocol_version,
        )
        observations.append(observation)

        if observation.decision.action in _SAFE_FORWARD_ACTIONS:
            forwarded.append(tool)
            forwarded_names.append(observation.snapshot.tool_name)
        else:
            withheld_names.append(observation.snapshot.tool_name)

    return ToolsListInterception(
        payload=_replace_tools(payload, forwarded),
        observations=observations,
        forwarded_tools=forwarded_names,
        withheld_tools=withheld_names,
        graph_evidence=graph_evidence,
        surface=surface,
    )
