"""MCP DriftGuard research core package."""

from .canonicalize import make_snapshot
from .diff import build_delta
from .evaluation import evaluate_standard_baselines
from .features import extract_pair_features
from .history import GitManifestHistoryMiner, adjacent_version_pairs
from .labeling import EvidenceTag, LabelDecision, recommended_label
from .learning import LogisticPairClassifier, record_features, repository_group_split
from .models import ChangeClass, ToolDelta, ToolSnapshot
from .mutations import build_low_and_slow_trajectory
from .temporal import SequentialDriftMonitor, TemporalConfig

__all__ = [
    "ChangeClass",
    "EvidenceTag",
    "GitManifestHistoryMiner",
    "LabelDecision",
    "LogisticPairClassifier",
    "SequentialDriftMonitor",
    "TemporalConfig",
    "ToolDelta",
    "ToolSnapshot",
    "adjacent_version_pairs",
    "build_delta",
    "build_low_and_slow_trajectory",
    "evaluate_standard_baselines",
    "extract_pair_features",
    "make_snapshot",
    "recommended_label",
    "record_features",
    "repository_group_split",
]
__version__ = "0.4.0"
