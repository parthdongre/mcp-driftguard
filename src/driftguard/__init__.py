"""MCP DriftGuard research core package."""

from .canonicalize import make_snapshot
from .diff import build_delta
from .features import extract_pair_features
from .learning import LogisticPairClassifier, record_features, repository_group_split
from .models import ChangeClass, ToolDelta, ToolSnapshot
from .temporal import SequentialDriftMonitor, TemporalConfig

__all__ = [
    "ChangeClass",
    "LogisticPairClassifier",
    "SequentialDriftMonitor",
    "TemporalConfig",
    "ToolDelta",
    "ToolSnapshot",
    "build_delta",
    "extract_pair_features",
    "make_snapshot",
    "record_features",
    "repository_group_split",
]
__version__ = "0.3.0"
