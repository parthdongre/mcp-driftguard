from driftguard.annotation_workflow import (
    AdjudicationRecord,
    HumanAnnotation,
    adjudications_to_pair_records,
    annotation_agreement,
    disagreement_candidate_ids,
)
from driftguard.dataset import AnnotationCandidate
from driftguard.labeling import EvidenceTag
from driftguard.models import ChangeClass


def annotation(annotation_id, candidate_id, annotator_id, label):
    return HumanAnnotation(
        annotation_id=annotation_id,
        candidate_id=candidate_id,
        annotator_id=annotator_id,
        label=label,
        evidence=[EvidenceTag.NEW_CAPABILITY],
        rationale="Reviewed old/new definitions and repository context.",
    )


def candidate(candidate_id="hist-1"):
    old_tool = {
        "name": "search",
        "description": "Search files.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    new_tool = {
        **old_tool,
        "description": "Search files and optionally write a report.",
    }
    return AnnotationCandidate(
        candidate_id=candidate_id,
        repository_id="owner/repo",
        server_id="owner/repo",
        tool_name="search",
        source_path="server.py",
        old_version_id="a" * 40,
        new_version_id="b" * 40,
        old_tool=old_tool,
        new_tool=new_tool,
    )


def test_annotation_agreement_reports_c2_c3_boundary_disagreement():
    left = [
        annotation("a-1", "c1", "alice", ChangeClass.CAPABILITY_EXPANSION),
        annotation("a-2", "c2", "alice", ChangeClass.BENIGN_MAINTENANCE),
    ]
    right = [
        annotation("b-1", "c1", "bob", ChangeClass.MALICIOUS_DRIFT),
        annotation("b-2", "c2", "bob", ChangeClass.BENIGN_MAINTENANCE),
    ]

    metrics = annotation_agreement(left, right)

    assert metrics.matched_candidates == 2
    assert metrics.raw_agreement == 0.5
    assert metrics.disagreements == 1
    assert metrics.c2_c3_disagreements == 1
    assert disagreement_candidate_ids(left, right, c2_c3_only=True) == ["c1"]


def test_perfect_annotation_agreement_has_kappa_one():
    left = [
        annotation("a-1", "c1", "alice", ChangeClass.BENIGN_MAINTENANCE),
        annotation("a-2", "c2", "alice", ChangeClass.MALICIOUS_DRIFT),
    ]
    right = [
        annotation("b-1", "c1", "bob", ChangeClass.BENIGN_MAINTENANCE),
        annotation("b-2", "c2", "bob", ChangeClass.MALICIOUS_DRIFT),
    ]

    metrics = annotation_agreement(left, right)

    assert metrics.raw_agreement == 1.0
    assert metrics.cohen_kappa == 1.0


def test_adjudication_builds_reviewed_real_history_pair():
    item = candidate()
    adjudication = AdjudicationRecord(
        candidate_id=item.candidate_id,
        annotation_ids=["a-1", "b-1"],
        annotator_ids=["alice", "bob"],
        final_label=ChangeClass.CAPABILITY_EXPANSION,
        final_evidence=[EvidenceTag.NEW_CAPABILITY],
        adjudicator_id="reviewer",
        rationale="The new write behavior is legitimate but exceeds prior consent.",
    )

    record = adjudications_to_pair_records([item], [adjudication])[0]

    assert record.label is ChangeClass.CAPABILITY_EXPANSION
    assert record.provenance == "real_history"
    assert record.annotators == ["alice", "bob", "reviewer"]
    assert record.repository_id == "owner/repo"
