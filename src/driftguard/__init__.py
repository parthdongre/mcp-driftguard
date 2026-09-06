"""MCP DriftGuard research core package."""

from .canonicalize import make_snapshot
from .diff import build_delta
from .features import extract_pair_features
from .models import ChangeClass, ToolDelta, ToolSnapshot
from .temporal import SequentialDriftMonitor, TemporalConfig

__all__ = [
    "ChangeClass",
    "ToolDelta",
    "ToolSnapshot",
    "SequentialDriftMonitor",
    "TemporalConfig",
    "build_delta",
    "extract_pair_features",
    "make_snapshot",
]
__version__ = "0.2.0"
