from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

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

    @model_validator(mode="after")
    def validate_identity(self) -> HumanAnnotation:
        for value in (self.annotation_id, self.candidate_id, self.annotator_id, self.rationale):
            if not value.strip():
                raise ValueError("Annotation identifiers and rationale must not be blank")
        return self


class AdjudicationRecord(BaseModel):
    """Final reviewed decision after comparing independent annotations."""

    candidate_id: str
    annotation_ids: list[str] = Field(min_length=2)
    annotator_ids: list[str] = Field(min_length=2)
    final_label: ChangeClass
    final_evidence: list[EvidenceTag] = Field(default_factory=list)
    adjudicator_id: str
    rationale: str

    @model_validator(mode="after")
    def validate_independent_references(self) -> AdjudicationRecord:
        if len(self.annotation_ids) != len(self.annotator_ids):
            raise ValueError("annotation_ids and annotator_ids must have equal length")
        if len(set(self.annotation_ids)) != len(self.annotation_ids):
            raise ValueError("Adjudication requires distinct annotation IDs")
        if len(set(self.annotator_ids)) != len(self.annotator_ids):
            raise ValueError("Adjudication requires independent, distinct annotator IDs")
        if any(not value.strip() for value in (
            self.candidate_id, self.adjudicator_id, self.rationale,
            *self.annotation_ids, *self.annotator_ids,
        )):
            raise ValueError("Adjudication identifiers and rationale must not be blank")
        return self


@dataclass(frozen=True)
class AnnotationAgreement:
    matched_candidates: int
    raw_agreement: float
    cohen_kappa: float | None
    disagreements: int
    c2_c3_disagreements: int
    labels: tuple[str, ...] = ()
    confusion_matrix: tuple[tuple[int, ...], ...] = ()
    unmatched_left: int = 0
    unmatched_right: int = 0


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
    annotation_ids: set[str] = set()
    for annotation in annotations:
        if annotation.candidate_id in result:
            raise ValueError(
                "Each annotation sequence may contain at most one decision per candidate"
            )
        if annotation.annotation_id in annotation_ids:
            raise ValueError("Human annotation IDs must be unique")
        annotation_ids.add(annotation.annotation_id)
        result[annotation.candidate_id] = annotation
    return result


def _independent_annotation_sets(
    annotations_a: Iterable[HumanAnnotation],
    annotations_b: Iterable[HumanAnnotation],
) -> tuple[dict[str, HumanAnnotation], dict[str, HumanAnnotation]]:
    left = _by_candidate(annotations_a)
    right = _by_candidate(annotations_b)
    left_raters = {item.annotator_id for item in left.values()}
    right_raters = {item.annotator_id for item in right.values()}
    if len(left_raters) > 1 or len(right_raters) > 1:
        raise ValueError("Cohen's kappa requires one consistent annotator per input sequence")
    if left_raters & right_raters:
        raise ValueError("Agreement requires two independent annotators")
    if {item.annotation_id for item in left.values()} & {
        item.annotation_id for item in right.values()
    }:
        raise ValueError("Independent annotation sequences must not reuse annotation IDs")
    return left, right


def _cohen_kappa(left: list[ChangeClass], right: list[ChangeClass]) -> float | None:
    if not left:
        return None
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(
        (left_counts[label] / len(left)) * (right_counts[label] / len(right))
        for label in ChangeClass
    )
    if expected == 1.0:
        # With both raters assigning only one class, chance agreement is one:
        # (observed - expected)/(1 - expected) is undefined, not perfect kappa.
        return None
    return (observed - expected) / (1.0 - expected)


def annotation_agreement(
    annotations_a: Iterable[HumanAnnotation],
    annotations_b: Iterable[HumanAnnotation],
) -> AnnotationAgreement:
    """Compute agreement only over candidates independently labeled by both annotators."""

    left_by_id, right_by_id = _independent_annotation_sets(annotations_a, annotations_b)
    candidate_ids = sorted(set(left_by_id) & set(right_by_id))
    if not candidate_ids:
        return AnnotationAgreement(
            matched_candidates=0,
            raw_agreement=0.0,
            cohen_kappa=None,
            disagreements=0,
            c2_c3_disagreements=0,
            labels=tuple(label.value for label in ChangeClass),
            confusion_matrix=tuple(tuple(0 for _ in ChangeClass) for _ in ChangeClass),
            unmatched_left=len(left_by_id),
            unmatched_right=len(right_by_id),
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
    kappa = _cohen_kappa(left, right)
    return AnnotationAgreement(
        matched_candidates=len(candidate_ids),
        raw_agreement=round(raw, 6),
        cohen_kappa=round(kappa, 6) if kappa is not None else None,
        disagreements=disagreements,
        c2_c3_disagreements=c2_c3_disagreements,
        labels=tuple(label.value for label in ChangeClass),
        confusion_matrix=tuple(
            tuple(sum(a is row and b is column for a, b in zip(left, right, strict=True))
                  for column in ChangeClass)
            for row in ChangeClass
        ),
        unmatched_left=len(set(left_by_id) - set(right_by_id)),
        unmatched_right=len(set(right_by_id) - set(left_by_id)),
    )


def disagreement_candidate_ids(
    annotations_a: Iterable[HumanAnnotation],
    annotations_b: Iterable[HumanAnnotation],
    *,
    c2_c3_only: bool = False,
) -> list[str]:
    left, right = _independent_annotation_sets(annotations_a, annotations_b)
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
    *,
    annotations: Iterable[HumanAnnotation] | None = None,
) -> list[PairDatasetRecord]:
    """Create reviewed pair records without silently inventing missing adjudications."""

    candidates = list(candidates)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    if len(candidate_by_id) != len(candidates):
        raise ValueError("Duplicate annotation candidate ID")
    annotation_by_id: dict[str, HumanAnnotation] | None = None
    if annotations is not None:
        annotations = list(annotations)
        annotation_by_id = {item.annotation_id: item for item in annotations}
        if len(annotation_by_id) != len(annotations):
            raise ValueError("Duplicate human annotation ID")
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
        if annotation_by_id is not None:
            for annotation_id, annotator_id in zip(
                adjudication.annotation_ids, adjudication.annotator_ids, strict=True
            ):
                annotation = annotation_by_id.get(annotation_id)
                if annotation is None:
                    raise ValueError(f"Adjudication references unknown annotation {annotation_id}")
                if (annotation.candidate_id != candidate.candidate_id
                        or annotation.annotator_id != annotator_id):
                    raise ValueError("Adjudication annotation reference does not match its source")
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
                old_version_id=candidate.old_version_id,
                new_version_id=candidate.new_version_id,
                old_committed_at=candidate.old_committed_at,
                new_committed_at=candidate.new_committed_at,
                annotators=[*adjudication.annotator_ids, adjudication.adjudicator_id],
                notes=adjudication.rationale,
            )
        )
    return records
