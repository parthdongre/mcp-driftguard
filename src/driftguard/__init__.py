"""MCP DriftGuard research core package."""

from .canonicalize import make_snapshot
from .corpus import historical_versions_to_candidates
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

__all__ = [
    "ChangeClass",
    "EvidenceTag",
    "GitManifestHistoryMiner",
    "GitSourceHistoryMiner",
    "LabelDecision",
    "LogisticPairClassifier",
    "PythonDecoratorToolExtractor",
    "SequentialDriftMonitor",
    "SplitManifest",
    "TemporalConfig",
    "ToolDelta",
    "ToolSnapshot",
    "TypeScriptRegisterToolExtractor",
    "adjacent_version_pairs",
    "apply_split_manifest",
    "build_delta",
    "build_low_and_slow_trajectory",
    "build_split_manifest",
    "evaluate_standard_baselines",
    "extract_pair_features",
    "historical_versions_to_candidates",
    "make_snapshot",
    "recommended_label",
    "record_features",
    "repository_group_split",
]
__version__ = "0.4.0"
