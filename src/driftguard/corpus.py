from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .canonicalize import make_snapshot
from .dataset import AnnotationCandidate
from .diff import build_delta
from .history import HistoricalToolVersion, adjacent_version_pairs


def _candidate_id(old: HistoricalToolVersion, new: HistoricalToolVersion) -> str:
    material = (
        f"{old.repository_id}|{old.path}|{old.tool_name}|{old.commit_sha}|"
        f"{new.commit_sha}|{old.schema_hash}|{new.schema_hash}"
    )
    return "hist-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _evidence_suggestions(old: HistoricalToolVersion, new: HistoricalToolVersion) -> list[str]:
    old_snapshot = make_snapshot(server_id=old.repository_id, tool=old.tool)
    new_snapshot = make_snapshot(server_id=new.repository_id, tool=new.tool)
    delta = build_delta(old_snapshot, new_snapshot)
    structural = delta.structural
    evidence: list[str] = []

    if structural.parameters_added:
        evidence.append("parameters_added:" + ",".join(structural.parameters_added))
    if structural.parameters_removed:
        evidence.append("parameters_removed:" + ",".join(structural.parameters_removed))
    if structural.required_added:
        evidence.append("required_added:" + ",".join(structural.required_added))
    if structural.required_removed:
        evidence.append("required_removed:" + ",".join(structural.required_removed))
    if structural.type_changes:
        evidence.append("type_changes:" + ",".join(sorted(structural.type_changes)))
    if structural.default_changes:
        evidence.append("default_changes:" + ",".join(sorted(structural.default_changes)))
    if structural.enum_changes:
        evidence.append("enum_changes:" + ",".join(structural.enum_changes))
    if structural.sensitive_terms_added:
        evidence.append("sensitive_terms_added:" + ",".join(structural.sensitive_terms_added))
    if structural.urls_added:
        evidence.append("urls_added:" + ",".join(structural.urls_added))
    if structural.cross_tool_references_added:
        evidence.append(
            "cross_tool_references_added:" + ",".join(structural.cross_tool_references_added)
        )
    if structural.imperative_terms_added:
        evidence.append("imperative_terms_added:" + ",".join(structural.imperative_terms_added))
    if delta.changed_fields:
        evidence.append("changed_fields:" + ",".join(delta.changed_fields))
    return evidence


def historical_versions_to_candidates(
    versions: Iterable[HistoricalToolVersion],
) -> list[AnnotationCandidate]:
    """Build an unlabeled queue from mined real-history tool transitions.

    Suggested evidence contains deterministic diff facts only. It deliberately does
    not assign C0-C3 labels so the primary reviewed corpus is not auto-labeled by the
    detector it will later evaluate.
    """

    candidates: list[AnnotationCandidate] = []
    for old, new in adjacent_version_pairs(versions):
        candidates.append(
            AnnotationCandidate(
                candidate_id=_candidate_id(old, new),
                repository_id=old.repository_id,
                server_id=old.repository_id,
                tool_name=old.tool_name,
                source_path=old.path,
                old_version_id=old.commit_sha,
                new_version_id=new.commit_sha,
                old_tool=old.tool,
                new_tool=new.tool,
                suggested_evidence=_evidence_suggestions(old, new),
            )
        )
    return candidates
