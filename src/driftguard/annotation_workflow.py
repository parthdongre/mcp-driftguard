from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from .dataset import AnnotationCandidate, PairDatasetRecord
from .labeling import EvidenceTag
from .models import ChangeClass


class HumanAnnotation(BaseModel):
    """One annotator's independent decision for a real-history transition."""

    annotation_id: str
    candidate_id: str
    annotator_id: str
    label: ChangeClass
    evidence: list[EvidenceTag] = Field(default_factory=list)
    rationale: str
    requires_second_review: bool = False


class AdjudicationRecord(BaseModel):
    """Final reviewed decision after comparing independent annotations."""

    candidate_id: str
    annotation_ids: list[str] = Field(min_length=2)
    annotator_ids: list[str] = Field(min_length=2)
    final_label: ChangeClass
    final_evidence: list[EvidenceTag] = Field(default_factory=list)
    adjudicator_id: str
    rationale: str


@dataclass(frozen=True)
class AnnotationAgreement:
    matched_candidates: int
    raw_agreement: float
    cohen_kappa: float
    disagreements: int
    c2_c3_disagreements: int


def _read_jsonl(path: str | Path, model_type: type[BaseModel]) -> list[BaseModel]:
    records: list[BaseModel] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
                records.append(model_type.model_validate(value))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"Invalid annotation JSONL at line {line_number}: {exc}") from exc
    return records


def read_human_annotations_jsonl(path: str | Path) -> list[HumanAnnotation]:
    return [
        record
        for record in _read_jsonl(path, HumanAnnotation)
        if isinstance(record, HumanAnnotation)
    ]


def read_adjudications_jsonl(path: str | Path) -> list[AdjudicationRecord]:
    return [
        record
        for record in _read_jsonl(path, AdjudicationRecord)
        if isinstance(record, AdjudicationRecord)
    ]


def _by_candidate(annotations: Iterable[HumanAnnotation]) -> dict[str, HumanAnnotation]:
    result: dict[str, HumanAnnotation] = {}
    for annotation in annotations:
        if annotation.candidate_id in result:
            raise ValueError(
                "Each annotation sequence may contain at most one decision per candidate"
            )
        result[annotation.candidate_id] = annotation
    return result


def _cohen_kappa(left: list[ChangeClass], right: list[ChangeClass]) -> float:
    if not left:
        return 0.0
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        (left_counts[label] / len(left)) * (right_counts[label] / len(right))
        for label in ChangeClass
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def annotation_agreement(
    annotations_a: Iterable[HumanAnnotation],
    annotations_b: Iterable[HumanAnnotation],
) -> AnnotationAgreement:
    """Compute agreement only over candidates independently labeled by both annotators."""

    left_by_id = _by_candidate(annotations_a)
    right_by_id = _by_candidate(annotations_b)
    candidate_ids = sorted(set(left_by_id) & set(right_by_id))
    if not candidate_ids:
        return AnnotationAgreement(
            matched_candidates=0,
            raw_agreement=0.0,
            cohen_kappa=0.0,
            disagreements=0,
            c2_c3_disagreements=0,
        )

    left = [left_by_id[candidate_id].label for candidate_id in candidate_ids]
    right = [right_by_id[candidate_id].label for candidate_id in candidate_ids]
    disagreements = sum(a != b for a, b in zip(left, right, strict=True))
    consent_boundary = {
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    }
    c2_c3_disagreements = sum(
        a != b and {a, b} == consent_boundary
        for a, b in zip(left, right, strict=True)
    )
    raw = 1.0 - disagreements / len(candidate_ids)
    return AnnotationAgreement(
        matched_candidates=len(candidate_ids),
        raw_agreement=round(raw, 6),
        cohen_kappa=round(_cohen_kappa(left, right), 6),
        disagreements=disagreements,
        c2_c3_disagreements=c2_c3_disagreements,
    )


def disagreement_candidate_ids(
    annotations_a: Iterable[HumanAnnotation],
    annotations_b: Iterable[HumanAnnotation],
    *,
    c2_c3_only: bool = False,
) -> list[str]:
    left = _by_candidate(annotations_a)
    right = _by_candidate(annotations_b)
    consent_boundary = {
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    }
    disagreements: list[str] = []
    for candidate_id in sorted(set(left) & set(right)):
        label_a = left[candidate_id].label
        label_b = right[candidate_id].label
        if label_a == label_b:
            continue
        if c2_c3_only and {label_a, label_b} != consent_boundary:
            continue
        disagreements.append(candidate_id)
    return disagreements


def adjudications_to_pair_records(
    candidates: Iterable[AnnotationCandidate],
    adjudications: Iterable[AdjudicationRecord],
) -> list[PairDatasetRecord]:
    """Create reviewed pair records without silently inventing missing adjudications."""

    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    records: list[PairDatasetRecord] = []
    seen: set[str] = set()
    for adjudication in adjudications:
        if adjudication.candidate_id in seen:
            raise ValueError("Duplicate adjudication for candidate")
        seen.add(adjudication.candidate_id)
        candidate = candidate_by_id.get(adjudication.candidate_id)
        if candidate is None:
            raise ValueError(
                f"Adjudication references unknown candidate {adjudication.candidate_id}"
            )
        records.append(
            PairDatasetRecord(
                record_id=f"reviewed-{candidate.candidate_id}",
                repository_id=candidate.repository_id,
                server_id=candidate.server_id,
                tool_name=candidate.tool_name,
                old_tool=candidate.old_tool,
                new_tool=candidate.new_tool,
                label=adjudication.final_label,
                provenance="real_history",
                annotators=[*adjudication.annotator_ids, adjudication.adjudicator_id],
                notes=adjudication.rationale,
            )
        )
    return records
