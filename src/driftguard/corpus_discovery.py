from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .history import parse_tool_manifest
from .source_extractors import PythonDecoratorToolExtractor, TypeScriptRegisterToolExtractor

SourceKind = Literal["json", "python", "typescript"]
DiscoveryStatus = Literal["extractable", "unsupported_pattern", "parse_error"]

_PYTHON_TOOL_HINT = re.compile(r"(?:@|\b)[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\.tool\b")
_TYPESCRIPT_TOOL_HINT = re.compile(r"\b[A-Za-z_$][\w$]*\.registerTool\s*\(")
_IGNORED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
}


@dataclass(frozen=True)
class SourceDiscovery:
    path: str
    kind: SourceKind
    status: DiscoveryStatus
    extracted_tools: int
    hint_count: int
    error: str | None = None

    @property
    def extractable(self) -> bool:
        return self.status == "extractable" and self.extracted_tools > 0


def _ignored(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in _IGNORED_PARTS for part in relative.parts)


def _read_text(path: Path, *, max_file_bytes: int) -> str | None:
    try:
        if path.stat().st_size > max_file_bytes:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _python_discovery(path: Path, text: str, root: Path) -> SourceDiscovery | None:
    hints = len(_PYTHON_TOOL_HINT.findall(text))
    if hints == 0:
        return None
    try:
        tools = PythonDecoratorToolExtractor().extract(text)
    except (SyntaxError, ValueError) as exc:
        return SourceDiscovery(
            path=path.relative_to(root).as_posix(),
            kind="python",
            status="parse_error",
            extracted_tools=0,
            hint_count=hints,
            error=str(exc),
        )
    return SourceDiscovery(
        path=path.relative_to(root).as_posix(),
        kind="python",
        status="extractable" if tools else "unsupported_pattern",
        extracted_tools=len(tools),
        hint_count=hints,
    )


def _typescript_discovery(path: Path, text: str, root: Path) -> SourceDiscovery | None:
    hints = len(_TYPESCRIPT_TOOL_HINT.findall(text))
    if hints == 0:
        return None
    try:
        tools = TypeScriptRegisterToolExtractor().extract(text)
    except ValueError as exc:
        return SourceDiscovery(
            path=path.relative_to(root).as_posix(),
            kind="typescript",
            status="parse_error",
            extracted_tools=0,
            hint_count=hints,
            error=str(exc),
        )
    return SourceDiscovery(
        path=path.relative_to(root).as_posix(),
        kind="typescript",
        status="extractable" if tools else "unsupported_pattern",
        extracted_tools=len(tools),
        hint_count=hints,
    )


def _json_discovery(path: Path, text: str, root: Path) -> SourceDiscovery | None:
    if "inputSchema" not in text and "input_schema" not in text:
        return None
    try:
        tools = parse_tool_manifest(text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return SourceDiscovery(
            path=path.relative_to(root).as_posix(),
            kind="json",
            status="parse_error",
            extracted_tools=0,
            hint_count=1,
            error=str(exc),
        )
    if not tools:
        return None
    return SourceDiscovery(
        path=path.relative_to(root).as_posix(),
        kind="json",
        status="extractable",
        extracted_tools=len(tools),
        hint_count=len(tools),
    )


def discover_mcp_sources(
    repository_path: str | Path,
    *,
    max_file_bytes: int = 2_000_000,
) -> list[SourceDiscovery]:
    """Statically discover mineable MCP tool-definition files in a repository.

    Discovery never imports or executes target repository code. It reports files that
    contain registration syntax even when the current conservative extractor cannot
    recover a literal tool definition, which makes extractor coverage gaps measurable.
    """

    root = Path(repository_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")

    discoveries: list[SourceDiscovery] = []
    for path in root.rglob("*"):
        if not path.is_file() or _ignored(path, root):
            continue
        suffix = path.suffix.lower()
        if suffix not in {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json"}:
            continue
        text = _read_text(path, max_file_bytes=max_file_bytes)
        if text is None:
            continue

        discovery: SourceDiscovery | None
        if suffix == ".py":
            discovery = _python_discovery(path, text, root)
        elif suffix == ".json":
            discovery = _json_discovery(path, text, root)
        else:
            discovery = _typescript_discovery(path, text, root)
        if discovery is not None:
            discoveries.append(discovery)

    return sorted(discoveries, key=lambda item: (item.kind, item.path))


def extractable_paths_by_kind(
    discoveries: list[SourceDiscovery],
) -> dict[SourceKind, list[str]]:
    result: dict[SourceKind, list[str]] = {
        "json": [],
        "python": [],
        "typescript": [],
    }
    for discovery in discoveries:
        if discovery.extractable:
            result[discovery.kind].append(discovery.path)
    return result
