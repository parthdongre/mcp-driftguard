from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from driftguard.corpus import historical_versions_to_candidates
from driftguard.corpus_discovery import SourceKind, discover_mcp_sources, extractable_paths_by_kind
from driftguard.dataset import AnnotationCandidate, write_jsonl
from driftguard.history import (
    GitManifestHistoryMiner,
    GitSourceHistoryMiner,
    HistoricalToolVersion,
)
from driftguard.source_extractors import (
    PythonDecoratorToolExtractor,
    TypeScriptRegisterToolExtractor,
)

_TS_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".cjs"}


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _git_output(repository_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo_directory(workspace: Path, repository_id: str) -> Path:
    return workspace / repository_id.replace("/", "__")


def _ensure_repository(
    entry: dict[str, Any],
    *,
    workspace: Path,
    no_network: bool,
    refresh: bool,
) -> Path:
    repository_id = str(entry["repository_id"])
    target = _repo_directory(workspace, repository_id)
    if target.exists():
        if not (target / ".git").is_dir():
            raise RuntimeError(f"Existing corpus path is not a Git repository: {target}")
        if refresh:
            if no_network:
                raise RuntimeError("--refresh cannot be combined with --no-network")
            _run(["git", "fetch", "--all", "--prune", "--tags"], cwd=target)
            _run(["git", "pull", "--ff-only"], cwd=target)
        return target

    if no_network:
        raise RuntimeError(f"Repository is missing in --no-network mode: {repository_id}")

    clone_url = str(entry["clone_url"])
    workspace.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--no-tags", clone_url, str(target)])
    return target


def _kind_for_path(path: str) -> SourceKind | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".py":
        return "python"
    if suffix in _TS_SUFFIXES:
        return "typescript"
    return None


def _paths_for_mining(
    entry: dict[str, Any],
    discoveries: list[dict[str, Any]],
) -> tuple[dict[SourceKind, list[str]], str]:
    verified = entry.get("verified_paths")
    if isinstance(verified, list) and verified:
        paths: dict[SourceKind, list[str]] = {
            "json": [],
            "python": [],
            "typescript": [],
        }
        for raw_path in verified:
            if not isinstance(raw_path, str):
                continue
            kind = _kind_for_path(raw_path)
            if kind is not None:
                paths[kind].append(raw_path)
        return paths, "verified_manifest_paths"

    from driftguard.corpus_discovery import SourceDiscovery

    discovery_objects = [SourceDiscovery(**item) for item in discoveries]
    return extractable_paths_by_kind(discovery_objects), "auto_discovery"


def _mine_repository(
    repository_path: Path,
    repository_id: str,
    entry: dict[str, Any],
) -> tuple[list[HistoricalToolVersion], list[dict[str, Any]], dict[SourceKind, list[str]], str]:
    discovery_objects = discover_mcp_sources(repository_path)
    discoveries = [asdict(item) for item in discovery_objects]
    paths, selection_mode = _paths_for_mining(entry, discoveries)
    versions: list[HistoricalToolVersion] = []

    if paths["json"]:
        versions.extend(
            GitManifestHistoryMiner(
                repository_path,
                repository_id=repository_id,
                manifest_paths=paths["json"],
            ).mine()
        )
    if paths["python"]:
        versions.extend(
            GitSourceHistoryMiner(
                repository_path,
                repository_id=repository_id,
                source_paths=paths["python"],
                extractor=PythonDecoratorToolExtractor(),
            ).mine()
        )
    if paths["typescript"]:
        versions.extend(
            GitSourceHistoryMiner(
                repository_path,
                repository_id=repository_id,
                source_paths=paths["typescript"],
                extractor=TypeScriptRegisterToolExtractor(),
            ).mine()
        )

    return versions, discoveries, paths, selection_mode


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    repositories = payload.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("Corpus manifest must contain a repositories list")
    return [entry for entry in repositories if isinstance(entry, dict)]


def _date_range(candidates: list[AnnotationCandidate]) -> dict[str, str | None]:
    timestamps = [
        timestamp
        for candidate in candidates
        for timestamp in (candidate.old_committed_at, candidate.new_committed_at)
        if timestamp is not None
    ]
    return {
        "earliest": min(timestamps) if timestamps else None,
        "latest": max(timestamps) if timestamps else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Clone public MCP repositories, statically discover tool registrations, "
            "mine Git history, and build an unlabeled annotation queue without "
            "executing target repository code."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/public_corpus_sources.json"),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(".corpus/repos"),
        help="Local clone directory; keep outside committed dataset artifacts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/public_history_candidates.jsonl"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/public_history_summary.json"),
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Repository id to process; repeat for multiple repositories",
    )
    parser.add_argument("--max-repos", type=int, default=None)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    entries = _load_manifest(args.manifest)
    selected = set(args.only)
    if selected:
        entries = [entry for entry in entries if entry.get("repository_id") in selected]
    if args.max_repos is not None:
        entries = entries[: args.max_repos]
    if not entries:
        raise SystemExit("No repositories selected")

    all_candidates: list[AnnotationCandidate] = []
    repository_summaries: list[dict[str, Any]] = []

    for entry in entries:
        repository_id = str(entry["repository_id"])
        repo_path = _ensure_repository(
            entry,
            workspace=args.workspace,
            no_network=args.no_network,
            refresh=args.refresh,
        )
        source_head_sha = _git_output(repo_path, "rev-parse", "HEAD")
        source_origin = _git_output(repo_path, "remote", "get-url", "origin")
        versions, discoveries, mined_paths, selection_mode = _mine_repository(
            repo_path,
            repository_id,
            entry,
        )
        candidates = historical_versions_to_candidates(versions)
        all_candidates.extend(candidates)

        extractable = [
            item for item in discoveries if item["status"] == "extractable"
        ]
        unsupported = [
            item for item in discoveries if item["status"] == "unsupported_pattern"
        ]
        parse_errors = [
            item for item in discoveries if item["status"] == "parse_error"
        ]
        unique_transition_tools = {
            candidate.tool_name for candidate in candidates
        }
        repository_summaries.append(
            {
                "repository_id": repository_id,
                "source_origin": source_origin,
                "source_head_sha": source_head_sha,
                "priority": entry.get("priority"),
                "declared_extractor_readiness": entry.get("extractor_readiness"),
                "path_selection_mode": selection_mode,
                "mined_paths": mined_paths,
                "discovered_source_files": len(discoveries),
                "extractable_source_files": len(extractable),
                "unsupported_pattern_files": len(unsupported),
                "parse_error_files": len(parse_errors),
                "historical_schema_versions": len(versions),
                "annotation_candidates": len(candidates),
                "unique_tools_with_transitions": len(unique_transition_tools),
                "candidate_date_range": _date_range(candidates),
                "discoveries": discoveries,
            }
        )

    write_jsonl(args.output, all_candidates)
    summary = {
        "manifest": str(args.manifest),
        "repositories_processed": len(repository_summaries),
        "annotation_candidates": len(all_candidates),
        "unique_repository_tool_lineages_with_transitions": len(
            {
                (candidate.repository_id, candidate.source_path, candidate.tool_name)
                for candidate in all_candidates
            }
        ),
        "candidate_date_range": _date_range(all_candidates),
        "repositories": repository_summaries,
        "safety": {
            "target_code_executed": False,
            "target_code_imported": False,
            "method": "static source/JSON parsing plus git show over historical blobs",
        },
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
