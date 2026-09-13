from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .diff import IMPERATIVE_TERMS, SENSITIVE_TERMS

_TOOL_REF_RE = re.compile(
    r"""(?:tool|function)\s+[`'\"]?([A-Za-z0-9_:-]+(?:\.[A-Za-z0-9_:-]+)*)""",
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


class CrossToolGraphDelta(BaseModel):
    """Topology changes between two complete MCP discovery surfaces."""

    added_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    added_edges: list[tuple[str, str]] = Field(default_factory=list)
    removed_edges: list[tuple[str, str]] = Field(default_factory=list)
    added_imperative_edges: list[tuple[str, str]] = Field(default_factory=list)
    added_sensitive_edges: list[tuple[str, str]] = Field(default_factory=list)
    new_cycles: list[list[str]] = Field(default_factory=list)
    resolved_cycles: list[list[str]] = Field(default_factory=list)
    newly_suspicious_sources: list[str] = Field(default_factory=list)
    resolved_suspicious_sources: list[str] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(
            (
                self.added_nodes,
                self.removed_nodes,
                self.added_edges,
                self.removed_edges,
                self.added_imperative_edges,
                self.added_sensitive_edges,
                self.new_cycles,
                self.resolved_cycles,
                self.newly_suspicious_sources,
                self.resolved_suspicious_sources,
            )
        )


class GraphRiskAssessment(BaseModel):
    """Transparent baseline risk assessment over topology drift."""

    risk_score: float = Field(ge=0.0, le=100.0)
    suspicious: bool
    reasons: list[str] = Field(default_factory=list)


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


def diff_tool_graph(
    old: CrossToolGraphEvidence,
    new: CrossToolGraphEvidence,
) -> CrossToolGraphDelta:
    """Compare two discovery graphs and expose topology-level security drift."""

    old_nodes = set(old.nodes)
    new_nodes = set(new.nodes)

    old_edge_map = {(edge.source, edge.target): edge for edge in old.edges}
    new_edge_map = {(edge.source, edge.target): edge for edge in new.edges}
    old_edges = set(old_edge_map)
    new_edges = set(new_edge_map)
    added_edges = new_edges - old_edges

    old_cycles = {_canonical_cycle(cycle) for cycle in old.cycles if cycle}
    new_cycles = {_canonical_cycle(cycle) for cycle in new.cycles if cycle}

    old_suspicious = set(old.suspicious_sources)
    new_suspicious = set(new.suspicious_sources)

    return CrossToolGraphDelta(
        added_nodes=sorted(new_nodes - old_nodes),
        removed_nodes=sorted(old_nodes - new_nodes),
        added_edges=sorted(added_edges),
        removed_edges=sorted(old_edges - new_edges),
        added_imperative_edges=sorted(
            key for key in added_edges if new_edge_map[key].imperative_terms
        ),
        added_sensitive_edges=sorted(
            key for key in added_edges if new_edge_map[key].sensitive_target
        ),
        new_cycles=[list(cycle) for cycle in sorted(new_cycles - old_cycles)],
        resolved_cycles=[list(cycle) for cycle in sorted(old_cycles - new_cycles)],
        newly_suspicious_sources=sorted(new_suspicious - old_suspicious),
        resolved_suspicious_sources=sorted(old_suspicious - new_suspicious),
    )


def graph_rule_baseline(delta: CrossToolGraphDelta) -> GraphRiskAssessment:
    """Transparent graph-drift baseline used before graph evidence affects policy."""

    if not delta.changed:
        return GraphRiskAssessment(
            risk_score=0.0,
            suspicious=False,
            reasons=["Discovery topology is unchanged."],
        )

    score = 0.0
    reasons: list[str] = []

    if delta.added_sensitive_edges:
        contribution = min(45.0, 25.0 + 10.0 * len(delta.added_sensitive_edges))
        score += contribution
        reasons.append(
            "New routes toward sensitive-looking tools: "
            + ", ".join(f"{source}->{target}" for source, target in delta.added_sensitive_edges)
        )

    if delta.added_imperative_edges:
        contribution = min(35.0, 18.0 + 8.0 * len(delta.added_imperative_edges))
        score += contribution
        reasons.append(
            "New imperative cross-tool routes: "
            + ", ".join(f"{source}->{target}" for source, target in delta.added_imperative_edges)
        )

    if delta.new_cycles:
        contribution = min(35.0, 22.0 + 8.0 * len(delta.new_cycles))
        score += contribution
        reasons.append(
            "New cross-tool cycles: "
            + "; ".join(" -> ".join(cycle) for cycle in delta.new_cycles)
        )

    if delta.newly_suspicious_sources:
        contribution = min(20.0, 5.0 * len(delta.newly_suspicious_sources))
        score += contribution
        reasons.append(
            "Tools newly marked suspicious by graph evidence: "
            + ", ".join(delta.newly_suspicious_sources)
        )

    if delta.added_edges and not reasons:
        score += min(15.0, 5.0 * len(delta.added_edges))
        reasons.append("Topology changed through new cross-tool references without high-risk evidence.")

    score = min(100.0, round(score, 2))
    suspicious = score >= 35.0
    return GraphRiskAssessment(
        risk_score=score,
        suspicious=suspicious,
        reasons=reasons or ["Topology changed without a scored high-risk graph signal."],
    )
