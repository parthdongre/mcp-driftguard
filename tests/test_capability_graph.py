import pytest

from driftguard.capability_graph import (
    CapabilityGraph,
    EvidenceKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    newly_reachable_exposures,
)


def nodes():
    return [
        GraphNode("secret", NodeKind.RESOURCE, sensitive=True),
        GraphNode("reader", NodeKind.TOOL),
        GraphNode("uploader", NodeKind.TOOL),
        GraphNode("remote", NodeKind.DESTINATION, external=True),
        GraphNode("local", NodeKind.DESTINATION),
    ]


def edge(source, target):
    return GraphEdge(source, target, "flow", EvidenceKind.DESCRIPTOR, "snapshot:test-v1")


def test_new_cross_tool_path_exposes_sensitive_resource_with_evidence():
    old_edges = [edge("secret", "reader"), edge("uploader", "remote")]
    before = CapabilityGraph(nodes(), old_edges)
    after = CapabilityGraph(nodes(), old_edges + [edge("reader", "uploader")])
    found = newly_reachable_exposures(before, after)
    assert len(found) == 1
    assert (found[0].resource, found[0].destination) == ("secret", "remote")
    assert len(found[0].edges) == 3
    assert found[0].includes_descriptor_inference
    assert all(e.provenance == "snapshot:test-v1" for e in found[0].edges)


def test_cycles_are_bounded_and_incremental_removal_revokes_path():
    bridge = edge("reader", "uploader")
    graph = CapabilityGraph(nodes(), [edge("secret", "reader"), bridge,
                                    edge("uploader", "reader"), edge("uploader", "remote")])
    assert len(graph.exposure_paths()) == 1
    graph.update(remove=[bridge])
    assert not graph.exposure_paths()
    with pytest.raises(ValueError, match="budget"):
        graph.exposure_paths(max_nodes=2)


def test_invalid_increment_is_atomic_and_local_sink_is_not_external():
    graph = CapabilityGraph(nodes(), [edge("secret", "reader")])
    with pytest.raises(ValueError, match="endpoint"):
        graph.update(add=[edge("reader", "remote"), edge("unknown", "local")])
    assert not graph.exposure_paths()
    graph.update(add=[edge("reader", "local")])
    assert not graph.exposure_paths()


def test_requires_distinct_identities_and_provenance():
    with pytest.raises(ValueError, match="Duplicate"):
        CapabilityGraph([nodes()[0], nodes()[0]])
    with pytest.raises(ValueError, match="provenance"):
        GraphEdge("a", "b", "flow", EvidenceKind.OBSERVED, "")


def test_deserialized_enum_strings_retain_evidence_semantics():
    graph = CapabilityGraph([
        GraphNode("secret", "resource", sensitive=True),
        GraphNode("sink", "destination", external=True),
    ], [GraphEdge("secret", "sink", "flow", "descriptor_inferred", "snapshot:1")])
    assert graph.exposure_paths()[0].includes_descriptor_inference
    with pytest.raises(ValueError):
        GraphNode("bad", "unsupported-kind")


def test_bounds_edge_count_and_witness_output():
    graph = CapabilityGraph(nodes(), [edge("secret", "reader"), edge("reader", "remote")])
    with pytest.raises(ValueError, match="budget"):
        graph.exposure_paths(max_edges=1)
    with pytest.raises(ValueError, match="Witness"):
        graph.exposure_paths(max_witness_edges=1)
