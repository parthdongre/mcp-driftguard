from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .diff import IMPERATIVE_TERMS, SENSITIVE_TERMS

_TOOL_REF_RE = re.compile(
    r"""(?:tool|function)\s+[`'"]?([A-Za-z0-9_.:-]+)""",
    re.IGNORECASE,
)


class CrossToolEdge(BaseModel):
    source: str
    target: str
    imperative_terms: list[str] = Field(default_factory=list)
    sensitive_target: bool = False


class CrossToolGraphEvidence(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[CrossToolEdge] = Field(default_factory=list)
    unresolved_references: dict[str, list[str]] = Field(default_factory=dict)
    cycles: list[list[str]] = Field(default_factory=list)
    suspicious_sources: list[str] = Field(default_factory=list)


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return ""


def _canonical_cycle(cycle: list[str]) -> tuple[str, ...]:
    if not cycle:
        return ()
    candidates: list[tuple[str, ...]] = []
    for sequence in (cycle, list(reversed(cycle))):
        for index in range(len(sequence)):
            rotated = sequence[index:] + sequence[:index]
            candidates.append(tuple(rotated))
    return min(candidates)


def _find_cycles(nodes: list[str], edges: list[CrossToolEdge]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge.target)

    seen: set[tuple[str, ...]] = set()
    stack: list[str] = []
    active: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            start = stack.index(node)
            cycle = stack[start:]
            canonical = _canonical_cycle(cycle)
            if canonical:
                seen.add(canonical)
            return

        if node in stack:
            return

        stack.append(node)
        active.add(node)
        for target in adjacency.get(node, []):
            visit(target)
        active.remove(node)
        stack.pop()

    for node in nodes:
        visit(node)

    return [list(cycle) for cycle in sorted(seen)]


def _target_looks_sensitive(name: str) -> bool:
    normalized = name.lower().replace("-", "_").replace(".", "_")
    for term in SENSITIVE_TERMS:
        candidate = term.lower().replace(" ", "_")
        if candidate in normalized:
            return True
    return False


def analyze_tool_graph(tools: list[dict[str, Any]]) -> CrossToolGraphEvidence:
    """Build an explicit cross-tool influence graph from one tools/list surface."""

    names = [
        str(tool.get("name"))
        for tool in tools
        if isinstance(tool.get("name"), str) and tool.get("name")
    ]
    canonical_names = {name.lower(): name for name in names}

    edges: list[CrossToolEdge] = []
    unresolved: dict[str, list[str]] = {}

    for tool in tools:
        source = tool.get("name")
        if not isinstance(source, str) or not source:
            continue

        text = _flatten_text(tool)
        lower = text.lower()
        imperative_terms = sorted(term for term in IMPERATIVE_TERMS if term in lower)

        for raw_target in _TOOL_REF_RE.findall(text):
            target = canonical_names.get(raw_target.lower())
            if target is None:
                unresolved.setdefault(source, []).append(raw_target)
                continue
            if target == source:
                continue

            edges.append(
                CrossToolEdge(
                    source=source,
                    target=target,
                    imperative_terms=imperative_terms,
                    sensitive_target=_target_looks_sensitive(target),
                )
            )

    deduped_edges: dict[tuple[str, str], CrossToolEdge] = {}
    for edge in edges:
        key = (edge.source, edge.target)
        previous = deduped_edges.get(key)
        if previous is None:
            deduped_edges[key] = edge
        else:
            previous.imperative_terms = sorted(
                set(previous.imperative_terms) | set(edge.imperative_terms)
            )
            previous.sensitive_target = previous.sensitive_target or edge.sensitive_target

    final_edges = sorted(
        deduped_edges.values(),
        key=lambda edge: (edge.source, edge.target),
    )
    cycles = _find_cycles(names, final_edges)
    cycle_nodes = {node for cycle in cycles for node in cycle}

    suspicious = {
        edge.source
        for edge in final_edges
        if edge.imperative_terms or edge.sensitive_target
    }
    suspicious.update(cycle_nodes)

    return CrossToolGraphEvidence(
        nodes=sorted(names),
        edges=final_edges,
        unresolved_references={
            source: sorted(set(targets))
            for source, targets in sorted(unresolved.items())
        },
        cycles=cycles,
        suspicious_sources=sorted(suspicious),
    )
