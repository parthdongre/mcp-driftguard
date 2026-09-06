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

    def _file_at_commit(self, commit_sha: str, path: str) -> str | None:
        result = self._git("show", f"{commit_sha}:{path}", check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def _collect(self, extractor: SourceToolExtractor) -> list[HistoricalToolVersion]:
        versions: list[HistoricalToolVersion] = []
        last_hash_by_key: dict[tuple[str, str], str] = {}
        for commit_sha in self.commits():
            for path in self.paths:
                text = self._file_at_commit(commit_sha, path)
                if text is None:
                    continue
                try:
                    tools = extractor.extract(text)
                except (SyntaxError, ValueError, json.JSONDecodeError):
                    continue
                for tool in tools:
                    canonical = canonicalize_tool(tool)
                    tool_name = str(canonical["name"])
                    digest = schema_hash(canonical)
                    key = (path, tool_name)
                    if last_hash_by_key.get(key) == digest:
                        continue
                    last_hash_by_key[key] = digest
                    versions.append(
                        HistoricalToolVersion(
                            repository_id=self.repository_id,
                            commit_sha=commit_sha,
                            path=path,
                            tool_name=tool_name,
                            tool=canonical,
                            schema_hash=digest,
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
