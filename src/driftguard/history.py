from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .canonicalize import canonicalize_tool, schema_hash


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


class GitManifestHistoryMiner:
    """Mine versioned JSON MCP tool definitions without executing repository code."""

    def __init__(
        self,
        repository_path: str | Path,
        *,
        repository_id: str,
        manifest_paths: Iterable[str],
    ) -> None:
        self.repository_path = Path(repository_path).resolve()
        self.repository_id = repository_id
        self.manifest_paths = tuple(dict.fromkeys(str(path) for path in manifest_paths))
        if not self.manifest_paths:
            raise ValueError("At least one manifest path is required")

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repository_path), *args],
            check=check,
            capture_output=True,
            text=True,
        )

    def commits(self) -> list[str]:
        result = self._git("rev-list", "--reverse", "HEAD", "--", *self.manifest_paths)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _file_at_commit(self, commit_sha: str, path: str) -> str | None:
        result = self._git("show", f"{commit_sha}:{path}", check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def mine(self) -> list[HistoricalToolVersion]:
        versions: list[HistoricalToolVersion] = []
        last_hash_by_key: dict[tuple[str, str], str] = {}
        for commit_sha in self.commits():
            for path in self.manifest_paths:
                text = self._file_at_commit(commit_sha, path)
                if text is None:
                    continue
                try:
                    tools = parse_tool_manifest(text)
                except json.JSONDecodeError:
                    continue
                for tool in tools:
                    tool_name = str(tool["name"])
                    digest = schema_hash(tool)
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
                            tool=tool,
                            schema_hash=digest,
                        )
                    )
        return versions


def adjacent_version_pairs(
    versions: Iterable[HistoricalToolVersion],
) -> list[tuple[HistoricalToolVersion, HistoricalToolVersion]]:
    grouped: dict[tuple[str, str, str], list[HistoricalToolVersion]] = {}
    for version in versions:
        key = (version.repository_id, version.path, version.tool_name)
        grouped.setdefault(key, []).append(version)
    pairs: list[tuple[HistoricalToolVersion, HistoricalToolVersion]] = []
    for lineage in grouped.values():
        pairs.extend(zip(lineage, lineage[1:]))
    return pairs
