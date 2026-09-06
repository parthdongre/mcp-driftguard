from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from .canonicalize import canonicalize_tool, schema_hash
from .source_extractors import SourceToolExtractor


@dataclass(frozen=True)
class HistoricalToolVersion:
    repository_id: str
    commit_sha: str
    path: str
    tool_name: str
    tool: dict[str, Any]
    schema_hash: str
    committed_at: str | None = None
    historical_path: str | None = None


def _looks_like_tool(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    name = value.get("name")
    input_schema = value.get("inputSchema", value.get("input_schema"))
    return isinstance(name, str) and isinstance(input_schema, dict)


def extract_tools_from_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if _looks_like_tool(value):
        found.append(canonicalize_tool(value))
        return found
    if isinstance(value, dict):
        for child in value.values():
            found.extend(extract_tools_from_json(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(extract_tools_from_json(child))
    return found


def parse_tool_manifest(text: str) -> list[dict[str, Any]]:
    return extract_tools_from_json(json.loads(text))


class _GitHistoryBase:
    def __init__(
        self,
        repository_path: str | Path,
        *,
        repository_id: str,
        paths: Iterable[str],
    ) -> None:
        self.repository_path = Path(repository_path).resolve()
        self.repository_id = repository_id
        self.paths = tuple(dict.fromkeys(str(path) for path in paths))
        if not self.paths:
            raise ValueError("At least one path is required")

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repository_path), *args],
            check=check,
            capture_output=True,
            text=True,
        )

    def commits(self) -> list[str]:
        result = self._git("rev-list", "--reverse", "HEAD", "--", *self.paths)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _followed_history(self, path: str) -> list[tuple[str, str]]:
        """Return oldest-first `(commit_sha, blob_path)` entries while following renames."""

        marker = "__DRIFTGUARD_COMMIT__"
        result = self._git(
            "log",
            "--follow",
            f"--format={marker}%H",
            "--name-status",
            "--diff-filter=AMR",
            "HEAD",
            "--",
            path,
            check=False,
        )
        if result.returncode != 0:
            return []

        current_path = path
        current_sha: str | None = None
        status_lines: list[str] = []
        newest_first: list[tuple[str, str]] = []

        def flush() -> None:
            nonlocal current_path, current_sha, status_lines
            if current_sha is None:
                return
            newest_first.append((current_sha, current_path))
            for status_line in status_lines:
                parts = status_line.split("\t")
                if len(parts) != 3 or not parts[0].startswith("R"):
                    continue
                old_path, new_path = parts[1], parts[2]
                if new_path == current_path:
                    current_path = old_path
                    break
            current_sha = None
            status_lines = []

        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line.startswith(marker):
                flush()
                current_sha = line.removeprefix(marker)
            elif line and current_sha is not None:
                status_lines.append(line)
        flush()
        newest_first.reverse()
        return newest_first

    def _commit_timestamp(self, commit_sha: str) -> str | None:
        result = self._git("show", "-s", "--format=%cI", commit_sha, check=False)
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def _file_at_commit(self, commit_sha: str, path: str) -> str | None:
        result = self._git("show", f"{commit_sha}:{path}", check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def _collect(self, extractor: SourceToolExtractor) -> list[HistoricalToolVersion]:
        versions: list[HistoricalToolVersion] = []
        timestamp_by_commit: dict[str, str | None] = {}

        for lineage_path in self.paths:
            last_hash_by_tool: dict[str, str] = {}
            for commit_sha, blob_path in self._followed_history(lineage_path):
                text = self._file_at_commit(commit_sha, blob_path)
                if text is None:
                    continue
                try:
                    tools = extractor.extract(text)
                except (SyntaxError, ValueError, json.JSONDecodeError):
                    continue
                committed_at = timestamp_by_commit.setdefault(
                    commit_sha,
                    self._commit_timestamp(commit_sha),
                )
                for tool in tools:
                    canonical = canonicalize_tool(tool)
                    tool_name = str(canonical["name"])
                    digest = schema_hash(canonical)
                    if last_hash_by_tool.get(tool_name) == digest:
                        continue
                    last_hash_by_tool[tool_name] = digest
                    versions.append(
                        HistoricalToolVersion(
                            repository_id=self.repository_id,
                            commit_sha=commit_sha,
                            path=lineage_path,
                            tool_name=tool_name,
                            tool=canonical,
                            schema_hash=digest,
                            committed_at=committed_at,
                            historical_path=blob_path,
                        )
                    )
        return versions


class _JsonExtractor:
    def extract(self, text: str) -> list[dict[str, Any]]:
        return parse_tool_manifest(text)


class GitManifestHistoryMiner(_GitHistoryBase):
    """Mine versioned JSON MCP tool definitions without executing repository code."""

    def __init__(
        self,
        repository_path: str | Path,
        *,
        repository_id: str,
        manifest_paths: Iterable[str],
    ) -> None:
        super().__init__(
            repository_path,
            repository_id=repository_id,
            paths=manifest_paths,
        )

    @property
    def manifest_paths(self) -> tuple[str, ...]:
        return self.paths

    def mine(self) -> list[HistoricalToolVersion]:
        return self._collect(_JsonExtractor())


class GitSourceHistoryMiner(_GitHistoryBase):
    """Mine versioned tool definitions using a static source-code extractor."""

    def __init__(
        self,
        repository_path: str | Path,
        *,
        repository_id: str,
        source_paths: Iterable[str],
        extractor: SourceToolExtractor,
    ) -> None:
        super().__init__(
            repository_path,
            repository_id=repository_id,
            paths=source_paths,
        )
        self.extractor = extractor

    @property
    def source_paths(self) -> tuple[str, ...]:
        return self.paths

    def mine(self) -> list[HistoricalToolVersion]:
        return self._collect(self.extractor)


def adjacent_version_pairs(
    versions: Iterable[HistoricalToolVersion],
) -> list[tuple[HistoricalToolVersion, HistoricalToolVersion]]:
    grouped: dict[tuple[str, str, str], list[HistoricalToolVersion]] = {}
    for version in versions:
        key = (version.repository_id, version.path, version.tool_name)
        grouped.setdefault(key, []).append(version)
    pairs: list[tuple[HistoricalToolVersion, HistoricalToolVersion]] = []
    for lineage in grouped.values():
        pairs.extend(pairwise(lineage))
    return pairs
