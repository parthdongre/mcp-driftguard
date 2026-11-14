"""Experimental, evidence-labelled attack-path analysis; never a runtime proof.

Edges must be supplied by an extractor or observer with provenance. Descriptor
inference and verified observations remain distinguishable in every returned path.
Reachability answers whether a path exists; shortest-path weights have no justified
security meaning here, so this module uses bounded breadth-first search.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum


class NodeKind(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    CAPABILITY = "capability"
    DESTINATION = "destination"


class EvidenceKind(StrEnum):
    DESCRIPTOR = "descriptor_inferred"
    OBSERVED = "runtime_observed"
    REVIEWED = "human_reviewed"


@dataclass(frozen=True, order=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    sensitive: bool = False
    external: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", NodeKind(self.kind))
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("Graph nodes require a stable, non-empty identity")
        if type(self.sensitive) is not bool or type(self.external) is not bool:
            raise ValueError("Node flags must be booleans")
        if self.external and self.kind is not NodeKind.DESTINATION:
            raise ValueError("Only destination nodes may be external")


@dataclass(frozen=True, order=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    evidence: EvidenceKind
    provenance: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", EvidenceKind(self.evidence))
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.source, self.target, self.relation, self.provenance)):
            raise ValueError("Every edge requires a relation and provenance")


@dataclass(frozen=True)
class ExposurePath:
    resource: str
    destination: str
    edges: tuple[GraphEdge, ...]

    @property
    def includes_descriptor_inference(self) -> bool:
        return any(edge.evidence is EvidenceKind.DESCRIPTOR for edge in self.edges)


class CapabilityGraph:
    """Small typed graph, with explicit incremental edge addition/removal.

    BFS visits O(V+E) per sensitive source, with deterministic adjacency sorting
    adding at most O(E log E), plus the total returned witness length. It returns
    one witness per reachable external destination. A witness is a modelled connection, never
    proof that an MCP server can or will carry out an exfiltration operation.
    """

    def __init__(self, nodes: list[GraphNode], edges: list[GraphEdge] = ()) -> None:
        self.nodes = {node.node_id: node for node in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("Duplicate graph node identities")
        self._edges: set[GraphEdge] = set()
        self._adjacent: dict[str, set[GraphEdge]] = {name: set() for name in self.nodes}
        self.update(add=list(edges))

    def update(
        self, *, add: list[GraphEdge] = (), remove: list[GraphEdge] = ()
    ) -> None:
        # Validate the whole mutation before applying any part.
        for edge in [*add, *remove]:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError("Every edge endpoint must reference an existing node")
        for edge in remove:
            self._edges.discard(edge)
            self._adjacent[edge.source].discard(edge)
        for edge in add:
            self._edges.add(edge)
            self._adjacent[edge.source].add(edge)

    def exposure_paths(
        self, *, max_nodes: int = 10_000, max_edges: int = 100_000,
        max_witness_edges: int = 100_000,
    ) -> tuple[ExposurePath, ...]:
        if (max_nodes < 1 or len(self.nodes) > max_nodes or max_edges < 1
                or len(self._edges) > max_edges or max_witness_edges < 1):
            raise ValueError("Graph exceeds the configured search budget")
        paths: list[ExposurePath] = []
        witness_edges = 0
        for source in sorted(self.nodes):
            origin = self.nodes[source]
            if origin.kind is not NodeKind.RESOURCE or not origin.sensitive:
                continue
            queue = deque([source])
            parent: dict[str, GraphEdge | None] = {source: None}
            while queue:
                current = queue.popleft()
                for edge in sorted(self._adjacent[current]):
                    if edge.target in parent:
                        continue
                    parent[edge.target] = edge
                    queue.append(edge.target)
                    target = self.nodes[edge.target]
                    if target.kind is NodeKind.DESTINATION and target.external:
                        witness: list[GraphEdge] = []
                        cursor = edge.target
                        while parent[cursor] is not None:
                            step = parent[cursor]
                            witness.append(step)
                            cursor = step.source
                            witness_edges += 1
                            if witness_edges > max_witness_edges:
                                raise ValueError("Witness output exceeds the search budget")
                        paths.append(ExposurePath(source, target.node_id, tuple(reversed(witness))))
        return tuple(paths)


def newly_reachable_exposures(
    before: CapabilityGraph, after: CapabilityGraph
) -> tuple[ExposurePath, ...]:
    """Return newly reachable source/sink pairs, retaining their evidence witnesses."""
    existing = {(path.resource, path.destination) for path in before.exposure_paths()}
    return tuple(
        path for path in after.exposure_paths()
        if (path.resource, path.destination) not in existing
    )
