"""MCP DriftGuard research core package."""

from .annotation_workflow import (
    AdjudicationRecord,
    AnnotationAgreement,
    HumanAnnotation,
    adjudications_to_pair_records,
    annotation_agreement,
    disagreement_candidate_ids,
)
from .canonicalize import make_snapshot
from .corpus import historical_versions_to_candidates
from .corpus_discovery import SourceDiscovery, discover_mcp_sources, extractable_paths_by_kind
from .diff import build_delta
from .evaluation import evaluate_standard_baselines
from .features import extract_pair_features
from .history import GitManifestHistoryMiner, GitSourceHistoryMiner, adjacent_version_pairs
from .labeling import EvidenceTag, LabelDecision, recommended_label
from .learning import LogisticPairClassifier, record_features, repository_group_split
from .models import ChangeClass, ToolDelta, ToolSnapshot
from .mutations import build_low_and_slow_trajectory
from .source_extractors import PythonDecoratorToolExtractor, TypeScriptRegisterToolExtractor
from .splits import SplitManifest, apply_split_manifest, build_split_manifest
from .temporal import SequentialDriftMonitor, TemporalConfig
from .thresholds import ThresholdSelection, tune_binary_threshold
from .trajectory_evaluation import (
    TrajectoryMetrics,
    TrajectoryRun,
    evaluate_trajectories,
    evaluate_trajectory,
)

__all__ = [
    "AdjudicationRecord",
    "AnnotationAgreement",
    "ChangeClass",
    "EvidenceTag",
    "GitManifestHistoryMiner",
    "GitSourceHistoryMiner",
    "HumanAnnotation",
    "LabelDecision",
    "LogisticPairClassifier",
    "PythonDecoratorToolExtractor",
    "SequentialDriftMonitor",
    "SourceDiscovery",
    "SplitManifest",
    "TemporalConfig",
    "ThresholdSelection",
    "ToolDelta",
    "ToolSnapshot",
    "TrajectoryMetrics",
    "TrajectoryRun",
    "TypeScriptRegisterToolExtractor",
    "adjacent_version_pairs",
    "adjudications_to_pair_records",
    "annotation_agreement",
    "apply_split_manifest",
    "build_delta",
    "build_low_and_slow_trajectory",
    "build_split_manifest",
    "discover_mcp_sources",
    "disagreement_candidate_ids",
    "evaluate_standard_baselines",
    "evaluate_trajectories",
    "evaluate_trajectory",
    "extract_pair_features",
    "extractable_paths_by_kind",
    "historical_versions_to_candidates",
    "make_snapshot",
    "recommended_label",
    "record_features",
    "repository_group_split",
    "tune_binary_threshold",
]
__version__ = "0.4.0"
