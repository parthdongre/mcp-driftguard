#!/usr/bin/env python3
"""Build an auditable, group-disjoint description-change corpus.

This script reads public HISTOR JSONL as text. It never starts or connects to
an MCP server and does not inspect or execute packages named by the snapshot.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import gzip
import hashlib
import itertools
import json
import random
import re
import sys
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "windows-mcp-description-training"
CACHE = OUT / "source_cache"
DATA = OUT / "data"
SNAPSHOT_DATE = "2026-11-16"
SNAPSHOT_BASE = f"https://histor.modelmarket.dev/datasets/{SNAPSHOT_DATE}"
EXPECTED = {
    "servers.jsonl.gz": "ab428f72a7b6be1922f5962d2fad2fc0c4251f17b0d54a71c547c3e71a59f924",
    "changes.jsonl.gz": "58759f93498c5293b799f52f1e73f7196e33c862c5ddd3e2e861dcfe5a607ecd",
}
LABEL_NAMES = {0: "same_or_narrower", 1: "broader", 2: "unclear"}
LABEL_IDS = {value: key for key, value in LABEL_NAMES.items()}
SEED = 42
PUBLISHER_CAP = 250
TIME_CHALLENGE_AFTER = "2026-11-09T00:00:00Z"
MODEL_ID = "cross-encoder/nli-deberta-v3-small"
CAPGATE_URL = "https://github.com/TANG-YB/mcp-rugpull-dataset"
CAPGATE_DATA = CACHE / "capgate_dataset.json"
CAPGATE_REPO = ROOT / ".runtime" / "capgate"
CAPGATE_ALIASES = {
    "github-mcp-server": {"github/github-mcp-server", "modelcontextprotocol/servers"},
    "awslabs/mcp": {"awslabs/mcp", "awslabs/aws-mcp", "awslabs/mcp-server"},
    "chrome-devtools-mcp": {"chrome-devtools/chrome-devtools-mcp", "modelcontextprotocol/servers"},
    "mcp-server-kubernetes": {"containers/kubernetes-mcp-server", "modelcontextprotocol/servers"},
    "modelcontextprotocol/servers": {"modelcontextprotocol/servers"},
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
            count += 1
    return count


def fetch_if_missing(name: str, offline: bool) -> Path:
    path = CACHE / name
    if path.exists():
        expected = EXPECTED.get(name)
        actual = sha256_file(path)
        if expected and actual != expected:
            raise ValueError(f"cached {name} hash mismatch: expected {expected}, got {actual}")
        return path
    if offline:
        raise FileNotFoundError(f"offline mode: required source file is missing: {path}")
    CACHE.mkdir(parents=True, exist_ok=True)
    url = f"{SNAPSHOT_BASE}/{name}"
    request = urllib.request.Request(url, headers={"User-Agent": "DriftGuard-research/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as target:
        while block := response.read(1024 * 1024):
            target.write(block)
    actual = sha256_file(path)
    expected = EXPECTED.get(name)
    if expected and actual != expected:
        path.unlink(missing_ok=True)
        raise ValueError(f"downloaded {name} hash mismatch: expected {expected}, got {actual}")
    return path


def read_jsonl_gzip(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with gzip.open(path, "rt", encoding="utf-8", errors="strict") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                yield line_number, json.loads(line)


def reconstruct_diff(chunks: Any) -> tuple[str, str]:
    """Apply HISTOR shared/old/new chunks to produce both original strings."""
    if not isinstance(chunks, list):
        raise ValueError("description diff is not a chunk list")
    old: list[str] = []
    new: list[str] = []
    for chunk in chunks:
        if not isinstance(chunk, list) or len(chunk) != 2:
            raise ValueError("malformed description chunk")
        operation, text = chunk
        if operation not in {"=", "+", "-"} or not isinstance(text, str):
            raise ValueError("unsupported description chunk")
        if operation in {"=", "-"}:
            old.append(text)
        if operation in {"=", "+"}:
            new.append(text)
    return "".join(old), "".join(new)


def self_check_reconstruction() -> None:
    cases = [
        ([ ["=", "caf\u00e9 \U0001f642"], ["-", " old"], ["+", " new"] ], "caf\u00e9 \U0001f642 old", "caf\u00e9 \U0001f642 new"),
        ([ ["+", "new"] ], "", "new"),
        ([ ["-", "old"] ], "old", ""),
        ([], "", ""),
    ]
    for chunks, expected_old, expected_new in cases:
        actual = reconstruct_diff(chunks)
        if actual != (expected_old, expected_new):
            raise AssertionError(f"diff reconstruction failed: {actual!r}")


def self_check_weak_labels() -> None:
    cases = [
        ("Read project notes only in the current project.", "Read project notes in any project.", 1),
        ("Read project notes across any project.", "Read project notes only in the current project.", 0),
        ("Read project notes only in the current project.", "Read project notes within this project only.", 0),
        ("Review notes in the active project.", "Review notes in the shared project.", None),
    ]
    for old, new, expected in cases:
        actual = weak_label(old, new)[0]
        if actual != expected:
            raise AssertionError(f"weak-label consistency check failed: expected {expected}, got {actual} for {old!r} -> {new!r}")


def normal_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _path_key_is_tool_description(key: str) -> bool:
    return key.strip() in {"description", "$.description"}


def _is_schema_or_annotation(key: str) -> bool:
    lowered = key.casefold()
    return any(word in lowered for word in ("schema", "annotation", "title"))


def normalize_repo(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.strip("/")
    if host in {"github.com", "www.github.com"}:
        pieces = [piece.casefold() for piece in path.split("/") if piece]
        if len(pieces) >= 2:
            return "/".join(pieces[:2]).removesuffix(".git")
    if host:
        return (host + "/" + path).rstrip("/").casefold()
    return value.casefold().strip("/ ")


def normalized_publisher(repository: str, endpoint: str, server_id: str) -> str:
    repo = normalize_repo(repository)
    if repo:
        return repo.split("/", 1)[0]
    package = endpoint.strip().casefold()
    if package:
        package = re.sub(r"^(?:npm|pypi|oci|docker):", "", package)
        return "package:" + package.split("/", 1)[0]
    return "unknown:" + server_id


def is_capgate_repository(repository: str, capgate_source_names: set[str]) -> bool:
    normalized = normalize_repo(repository)
    if not normalized:
        return False
    basename = normalized.rsplit("/", 1)[-1]
    known_bases = {name.rsplit("/", 1)[-1] for name in capgate_source_names}
    aliases = set().union(*CAPGATE_ALIASES.values())
    alias_bases = {name.rsplit("/", 1)[-1] for name in aliases}
    return normalized in capgate_source_names or normalized in aliases or basename in known_bases | alias_bases


ACTION_RE = re.compile(r"\b(read|search|list|review|inspect|retrieve|find|view|fetch|query|browse|open|look up|access|write|edit|delete|send|upload|export|share|run|execute|create|update|manage)\b", re.I)
RESTRICTED_RE = re.compile(r"\b(only|limited to|restricted to|current|selected|specific|specified|provided|user[- ]chosen|configured|read[- ]only|local|within this|in this)\b", re.I)
BROAD_RE = re.compile(r"\b(any|all|every|global|worldwide|across all|outside the|other projects?|other workspaces?|other repositories?)\b", re.I)
DESTINATION_RE = re.compile(r"\b(external|third[- ]party|public|any url|any domain|arbitrary url|internet|remote destination)\b|https?://", re.I)
ACTION_SET = {"read", "search", "list", "review", "inspect", "retrieve", "find", "view", "fetch", "query", "browse", "open", "access", "write", "edit", "delete", "send", "upload", "export", "share", "run", "execute", "create", "update", "manage"}
SCOPE_CUE_WORDS = {"only", "limited", "restricted", "current", "selected", "specific", "specified", "provided", "configured", "user", "chosen", "within", "inside", "across", "any", "all", "every", "global", "outside", "other", "the", "this", "in", "for", "one", "to"}


def weak_label(old: str, new: str) -> tuple[int | None, str, str, str, str]:
    """Return only narrow, evidence-backed labels; all other history is review."""
    old_n, new_n = normal_text(old), normal_text(new)
    old_actions = set(ACTION_RE.findall(old_n)) & ACTION_SET
    new_actions = set(ACTION_RE.findall(new_n)) & ACTION_SET
    same_action = bool(old_actions & new_actions)
    added = [token for token in re.findall(r"[\w'-]+", new_n) if token not in set(re.findall(r"[\w'-]+", old_n))]
    removed = [token for token in re.findall(r"[\w'-]+", old_n) if token not in set(re.findall(r"[\w'-]+", new_n))]

    old_broad, new_broad = bool(BROAD_RE.search(old_n)), bool(BROAD_RE.search(new_n))
    old_restricted, new_restricted = bool(RESTRICTED_RE.search(old_n)), bool(RESTRICTED_RE.search(new_n))
    old_core = sorted(word for word in re.findall(r"[\w'-]+", old_n) if word not in SCOPE_CUE_WORDS)
    new_core = sorted(word for word in re.findall(r"[\w'-]+", new_n) if word not in SCOPE_CUE_WORDS)
    same_core = bool(old_core) and old_core == new_core
    if same_action and same_core and not old_broad and new_broad and old_restricted:
        before_phrase = next((m.group(0) for m in RESTRICTED_RE.finditer(old_n)), "restricted scope")
        after_phrase = next((m.group(0) for m in BROAD_RE.finditer(new_n)), "broader scope")
        if DESTINATION_RE.search(new_n) and not DESTINATION_RE.search(old_n):
            dimension = "destination"
        else:
            dimension = "scope"
        return 1, "weak_scope_expansion_v1", dimension, before_phrase, after_phrase
    if same_action and same_core and old_broad and new_restricted and not new_broad:
        before_phrase = next((m.group(0) for m in BROAD_RE.finditer(old_n)), "broad scope")
        after_phrase = next((m.group(0) for m in RESTRICTED_RE.finditer(new_n)), "restricted scope")
        return 0, "weak_scope_narrowing_v1", "scope", before_phrase, after_phrase

    if same_action and same_core and old_restricted and not new_restricted and old_broad is False and new_broad:
        before_phrase = next((m.group(0) for m in RESTRICTED_RE.finditer(old_n)), "restriction")
        after_phrase = next((m.group(0) for m in BROAD_RE.finditer(new_n)), "broader scope")
        return 1, "weak_restriction_removed_v1", "restriction", before_phrase, after_phrase

    if same_action and same_core and old_restricted and new_restricted and not old_broad and not new_broad:
        before_phrase = next((m.group(0) for m in RESTRICTED_RE.finditer(old_n)), "restricted scope")
        after_phrase = next((m.group(0) for m in RESTRICTED_RE.finditer(new_n)), "restricted scope")
        return 0, "weak_equivalent_scope_rewrite_v1", "scope", before_phrase, after_phrase

    ratio = difflib.SequenceMatcher(a=old_n, b=new_n, autojunk=False).ratio()
    if ratio >= 0.94 and old_actions == new_actions and not (new_broad and not old_broad):
        changed = "wording" if old_n != new_n else "none"
        old_phrase, new_phrase = (old[:160], new[:160])
        return 0, "weak_near_identity_v1", changed, old_phrase, new_phrase

    if not same_action or (old_broad == new_broad and old_restricted == new_restricted):
        return None, "review_required", "ambiguous_or_unclassified", "", ""
    return None, "review_required", "ambiguous_or_unclassified", "", ""


def _pair_key(old: str, new: str) -> str:
    sides = sorted((normal_text(old), normal_text(new)))
    return sha256_bytes((sides[0] + "\0" + sides[1]).encode("utf-8"))


def _oriented_pair_key(old: str, new: str) -> str:
    return sha256_bytes((old + "\0" + new).encode("utf-8"))


def _text_shingles(text: str, width: int = 3) -> frozenset[str]:
    words = re.findall(r"[\w'-]+", normal_text(text))
    if len(words) < width:
        return frozenset({" ".join(words)}) if words else frozenset()
    return frozenset(" ".join(words[i : i + width]) for i in range(len(words) - width + 1))


def near_duplicate_clusters(rows: list[dict[str, Any]]) -> list[str]:
    """Conservative LSH + exact shingle check, with controlled families grouped."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    family_first: dict[str, int] = {}
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    shingle_sets: list[frozenset[int]] = []
    normalized_pairs: list[str] = []
    mask = (1 << 64) - 1
    salts = [int.from_bytes(hashlib.sha256(f"near-duplicate-band-{index}".encode()).digest()[:8], "big") for index in range(8)]
    for index, row in enumerate(rows):
        family = row.get("template_family")
        if family:
            if family in family_first:
                union(index, family_first[family])
            else:
                family_first[family] = index
        pair = "\napproved: " + normal_text(row["approved_description"]) + "\ncurrent: " + normal_text(row["current_description"])
        normalized_pairs.append(pair)
        shingles = frozenset(int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big") for value in _text_shingles(pair, 3))
        shingle_sets.append(shingles)
        if not shingles:
            continue
        signature = [min(((value ^ salt) * 0x9E3779B185EBCA87) & mask for value in shingles) for salt in salts]
        for band in range(4):
            key = (band, signature[band * 2], signature[band * 2 + 1])
            for candidate in buckets[key]:
                left, right = shingle_sets[index], shingle_sets[candidate]
                if not left or not right:
                    continue
                jaccard = len(left & right) / len(left | right)
                if jaccard >= 0.92:
                    union(index, candidate)
            buckets[key].append(index)

    root_ids: dict[int, str] = {}
    output: list[str] = []
    for index in range(len(rows)):
        root = find(index)
        if root not in root_ids:
            root_ids[root] = sha256_bytes(normalized_pairs[root].encode("utf-8"))[:20]
        output.append(root_ids[root])
    return output


def load_capgate() -> tuple[list[dict[str, Any]], dict[str, Any], set[str]]:
    if not CAPGATE_DATA.exists() and CAPGATE_REPO.exists():
        source = CAPGATE_REPO / "capgate_dataset.json"
        if source.exists():
            CAPGATE_DATA.parent.mkdir(parents=True, exist_ok=True)
            CAPGATE_DATA.write_bytes(source.read_bytes())
    if not CAPGATE_DATA.exists():
        return [], {"available": False, "reason": "public source checkout not present"}, set()
    rows = json.loads(CAPGATE_DATA.read_text(encoding="utf-8"))
    sha = sha256_file(CAPGATE_DATA)
    revision = "unavailable"
    try:
        import subprocess

        revision = subprocess.check_output(["git", "-C", str(CAPGATE_REPO), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        pass
    sources = {normalize_repo(str(row.get("source", ""))) for row in rows if row.get("source")}
    metadata = {
        "available": True,
        "url": CAPGATE_URL,
        "source_revision": revision,
        "dataset_sha256": sha,
        "rows": len(rows),
        "license": "MIT repository license; per-record source repositories also retained",
        "builder": "rust-version/build_description_corpus.py is not present in the public pinned checkout; used its checked-in capgate_dataset.json directly.",
        "note": "Labels are CAPGATE rule-derived labels, not independent human annotations.",
    }
    return rows, metadata, sources


def load_servers(path: Path) -> dict[str, dict[str, Any]]:
    servers: dict[str, dict[str, Any]] = {}
    for line_number, row in read_jsonl_gzip(path):
        servers[str(row.get("id", ""))] = {"repository": row.get("repository"), "endpoint": row.get("endpoint")}
        if line_number % 25_000 == 0:
            print(f"loaded server metadata: {line_number}", file=sys.stderr, flush=True)
    return servers


def extract_history(changes_path: Path, servers: dict[str, dict[str, Any]], capgate_sources: set[str], counts: Counter[str]) -> Iterator[dict[str, Any]]:
    for line_number, change in read_jsonl_gzip(changes_path):
        counts["change_rows"] += 1
        if line_number % 25_000 == 0:
            print(f"streamed change diffs: {line_number}", file=sys.stderr, flush=True)
        try:
            summary = json.loads(change.get("summaryJson") or "{}")
        except json.JSONDecodeError:
            counts["invalid_summary"] += 1
            continue
        if summary.get("detail") not in (None, "full"):
            counts["truncated_change_summaries"] += 1
            continue
        server = servers.get(str(change.get("serverId", "")), {})
        repository = str(server.get("repository") or "")
        endpoint = str(server.get("endpoint") or "")
        server_id = str(change.get("serverId", ""))
        repo_norm = normalize_repo(repository)
        publisher = normalized_publisher(repository, endpoint, server_id)
        for modified in summary.get("modified", []):
            counts["modified_tool_entries"] += 1
            tool_name = str(modified.get("tool") or "")
            if not tool_name:
                counts["missing_tool_name"] += 1
                continue
            fields = modified.get("fields") or {}
            description_fields = [(key, value) for key, value in fields.items() if _path_key_is_tool_description(str(key))]
            if not description_fields:
                if any(_is_schema_or_annotation(str(key)) for key in fields):
                    counts["schema_or_annotation_only_entries"] += 1
                continue
            if len(description_fields) != 1:
                counts["ambiguous_description_diffs"] += 1
                continue
            other_fields = [str(key) for key in fields if not _path_key_is_tool_description(str(key))]
            if other_fields:
                if any(_is_schema_or_annotation(key) for key in other_fields):
                    counts["simultaneous_schema_or_annotation_transitions"] += 1
                else:
                    counts["simultaneous_other_field_transitions"] += 1
                continue
            try:
                old, new = reconstruct_diff(description_fields[0][1])
            except ValueError:
                counts["unverified_or_truncated_description_diffs"] += 1
                continue
            if old == new:
                counts["no_op_description_diffs"] += 1
                continue
            counts["description_only_transitions"] += 1
            is_external = is_capgate_repository(repository, capgate_sources)
            if is_external:
                counts["capgate_family_excluded"] += 1
            label, method, dimension, before_evidence, after_evidence = weak_label(old, new)
            observed_at = str(change.get("observedAt") or "")
            record = {
                "example_id": "histor:" + sha256_bytes(f"{change.get('id')}:{line_number}:{tool_name}".encode())[:20],
                "source_kind": "observed_history",
                "server_id": server_id,
                "publisher": publisher,
                "normalized_publisher": publisher,
                "repository": repository,
                "repository_family": repo_norm or "unknown:" + server_id,
                "tool": tool_name,
                "observed_at": observed_at,
                "old_toolset_digest": change.get("fromToolSetDigest"),
                "new_toolset_digest": change.get("toToolSetDigest"),
                "approved_description": old,
                "current_description": new,
                "source_revision": {
                    "change_id": change.get("id"),
                    "from_package_version": change.get("fromPackageVersion"),
                    "to_package_version": change.get("toPackageVersion"),
                    "from_server_version": change.get("fromServerVersion"),
                    "to_server_version": change.get("toServerVersion"),
                    "from_registry_version": change.get("fromRegistryVersion"),
                    "to_registry_version": change.get("toRegistryVersion"),
                    "from_subject_digest": change.get("fromSubjectDigest"),
                    "to_subject_digest": change.get("toSubjectDigest"),
                },
                "provenance": {
                    "snapshot_date": SNAPSHOT_DATE,
                    "source_url": f"{SNAPSHOT_BASE}/changes.jsonl.gz",
                    "source_line": line_number,
                    "change_id": change.get("id"),
                    "diff_path": description_fields[0][0],
                    "record_sha256": sha256_bytes(canonical_json(change).encode("utf-8")),
                },
                "rights": {
                    "dataset_license": "CC-BY-4.0",
                    "source_repository": repository,
                    "attribution_required": True,
                    "redistribution": "CC-BY-4.0 snapshot; retain source repository attribution",
                },
                "label": label,
                "label_name": LABEL_NAMES[label] if label is not None else None,
                "label_source": "weak_heuristic" if label is not None else "unresolved_candidate",
                "label_method": method,
                "changed_dimension": dimension,
                "evidence_before": before_evidence,
                "evidence_after": after_evidence,
                "split": None,
                "capgate_family_excluded": is_external,
            }
            yield record


SYN_ACTIONS = ["Read", "Search", "List", "Review", "Inspect", "Retrieve", "Find", "View"]
SYN_RESOURCES = [
    "project notes", "design documents", "source files", "release records", "calendar entries", "team messages",
    "build logs", "support tickets", "invoices", "customer profiles", "database rows", "repository issues",
    "meeting notes", "inventory records", "workspace documents", "saved searches", "contact records", "usage reports",
    "package metadata", "asset records", "change requests", "service alerts", "deployment notes", "test results",
    "budget entries", "vendor records", "project files", "mail folders", "event details", "task descriptions",
    "policy documents", "report drafts", "product listings", "training materials", "account activity", "case notes",
    "branch summaries", "job histories", "resource tags", "incident records",
]
SYN_SCOPES = ["project", "workspace", "repository", "folder", "account", "team", "region", "website", "calendar", "mailbox", "database", "environment", "customer", "service", "branch", "organization"]
SYN_STYLES = ["in", "for", "limited", "configured", "provided", "chosen", "within", "scope"]


def controlled_examples(family_limit: int, seed: int) -> list[dict[str, Any]]:
    """Create transparent, ordinary permission pairs from reviewed rules."""
    combinations = list(itertools.product(SYN_ACTIONS, SYN_RESOURCES, SYN_SCOPES, SYN_STYLES))
    combinations.sort(key=lambda row: hashlib.sha256((str(seed) + "|" + "|".join(row)).encode()).hexdigest())
    output: list[dict[str, Any]] = []
    for index, (action, resource, scope, style) in enumerate(combinations[:family_limit]):
        family_token = hashlib.sha256(f"{seed}|{action}|{resource}|{scope}|{style}".encode()).hexdigest()[:18]
        family = "fictional-family:" + family_token
        if style in {"in", "scope"}:
            narrow = f"only in the current {scope}"
            wide = f"in any {scope}"
            equivalent = f"within this {scope} only"
            old_narrow, new_wide = f"{action} {resource} {narrow}.", f"{action} {resource} {wide}."
            old_equal, new_equal = f"{action} {resource} only in the current {scope}.", f"{action} {resource} {equivalent}."
            old_wide, new_narrow = f"{action} {resource} across any {scope}.", f"{action} {resource} only in the current {scope}."
        elif style == "for":
            narrow = f"for the current {scope} only"
            wide = f"for any {scope}"
            old_narrow, new_wide = f"{action} {resource} {narrow}.", f"{action} {resource} {wide}."
            old_equal, new_equal = f"{action} {resource} only for the current {scope}.", f"{action} {resource} for this {scope} only."
            old_wide, new_narrow = f"{action} {resource} for any {scope}.", f"{action} {resource} for the current {scope} only."
        elif style == "limited":
            old_narrow, new_wide = f"{action} {resource}, limited to the current {scope}.", f"{action} {resource} across all {scope}s."
            old_equal, new_equal = f"{action} {resource} only in the current {scope}.", f"{action} {resource} within the current {scope} only."
            old_wide, new_narrow = f"{action} {resource} across all {scope}s.", f"{action} {resource}, limited to the current {scope}."
        elif style == "configured":
            old_narrow, new_wide = f"{action} {resource} in the configured {scope} only.", f"{action} {resource} in any {scope}."
            old_equal, new_equal = f"{action} {resource} only in the configured {scope}.", f"{action} {resource} in the configured {scope} only."
            old_wide, new_narrow = f"{action} {resource} in any {scope}.", f"{action} {resource} in the configured {scope} only."
        elif style == "provided":
            old_narrow, new_wide = f"{action} {resource} in the {scope} supplied by the user.", f"{action} {resource} in any {scope}."
            old_equal, new_equal = f"{action} {resource} in the user-provided {scope} only.", f"{action} {resource} in the {scope} supplied by the user only."
            old_wide, new_narrow = f"{action} {resource} in any {scope}.", f"{action} {resource} in the user-provided {scope} only."
        elif style == "chosen":
            old_narrow, new_wide = f"{action} {resource} for one chosen {scope} only.", f"{action} {resource} for every {scope}."
            old_equal, new_equal = f"{action} {resource} only for the chosen {scope}.", f"{action} {resource} for one chosen {scope} only."
            old_wide, new_narrow = f"{action} {resource} for every {scope}.", f"{action} {resource} for one chosen {scope} only."
        else:
            old_narrow, new_wide = f"For {resource}, {action.lower()} is limited to the current {scope}.", f"For {resource}, {action.lower()} may include any {scope}."
            old_equal, new_equal = f"For {resource}, {action.lower()} is allowed only in the current {scope}.", f"For {resource}, {action.lower()} is restricted to this {scope}."
            old_wide, new_narrow = f"For {resource}, {action.lower()} may include any {scope}.", f"For {resource}, {action.lower()} is limited to the current {scope}."
        ambiguous_old = f"{action} {resource} in the active {scope}."
        ambiguous_new = f"{action} {resource} in the shared {scope}."
        variants = [
            (old_equal, new_equal, 0, "scope", "current " + scope, "this " + scope, "controlled_equivalent_v1"),
            (old_wide, new_narrow, 0, "scope", "any " + scope, "current " + scope, "controlled_narrowing_v1"),
            (old_narrow, new_wide, 1, "scope", "current " + scope, "any " + scope, "controlled_expansion_v1"),
            (ambiguous_old, ambiguous_new, 2, "scope", "active " + scope, "shared " + scope, "controlled_unclear_v1"),
        ]
        for subindex, (old, new, label, dimension, ev_before, ev_after, method) in enumerate(variants):
            example_id = f"fictional:{family_token}:{subindex}"
            repo = "fictional://" + family_token
            output.append({
                "example_id": example_id,
                "source_kind": "controlled_fictional",
                "server_id": "fictional-server-" + family_token,
                "publisher": repo,
                "normalized_publisher": repo,
                "repository": repo,
                "repository_family": repo,
                "tool": re.sub(r"[^a-z0-9]+", "_", f"{action}_{resource}").strip("_")[:80],
                "observed_at": None,
                "old_toolset_digest": None,
                "new_toolset_digest": None,
                "approved_description": old,
                "current_description": new,
                "source_revision": {"generator": "controlled_fixture_v1", "scenario_index": index},
                "provenance": {"source": "fictional, ordinary access and documentation case", "generator": "prepare.py controlled_fixture_v1", "family": family},
                "rights": {"dataset_license": "original fictional text", "attribution_required": False, "redistribution": "allowed"},
                "label": label,
                "label_name": LABEL_NAMES[label],
                "label_source": "controlled_fictional_reviewed_for_consistency",
                "label_method": method,
                "changed_dimension": dimension,
                "evidence_before": ev_before,
                "evidence_after": ev_after,
                "split": None,
                "template_family": family,
                "capgate_family_excluded": False,
                "review_status": "generator_consistency_checks_passed",
            })
    return output


def deduplicate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    seen: dict[str, int] = {}
    retained: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        key = _pair_key(row["approved_description"], row["current_description"])
        if key in seen:
            counts["exact_or_reversed_duplicate"] += 1
            continue
        seen[key] = len(retained)
        row["definition_pair_hash"] = _oriented_pair_key(row["approved_description"], row["current_description"])
        row["undirected_pair_hash"] = key
        retained.append(row)
    return retained, counts


def _split_for_group(group: str) -> str:
    value = int(hashlib.sha256((f"{SEED}|{group}").encode()).hexdigest()[:8], 16) % 100
    if value < 80:
        return "train"
    if value < 90:
        return "validation"
    return "test"


def split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clusters = near_duplicate_clusters(rows)
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    key_first: dict[str, int] = {}
    for i, row in enumerate(rows):
        keys = [
            "publisher:" + str(row.get("normalized_publisher") or ""),
            "repository:" + str(row.get("repository_family") or ""),
            "pair:" + str(row.get("undirected_pair_hash") or ""),
            "near:" + clusters[i],
        ]
        if row.get("template_family"):
            keys.append("template:" + row["template_family"])
        for key in keys:
            if key.endswith(":"):
                continue
            if key in key_first:
                union(i, key_first[key])
            else:
                key_first[key] = i
    root_clusters: dict[int, set[str]] = defaultdict(set)
    for i in range(len(rows)):
        root_clusters[find(i)].add(clusters[i])
    group_for_root = {
        root: "group:" + hashlib.sha256("|".join(sorted(values)).encode()).hexdigest()[:20]
        for root, values in root_clusters.items()
    }
    for i, row in enumerate(rows):
        root = find(i)
        group = group_for_root[root]
        row["near_duplicate_cluster"] = clusters[i]
        row["split_group"] = group
        row["split"] = _split_for_group(group)
        row["content_sha256"] = sha256_bytes(canonical_json({
            "approved_description": row["approved_description"],
            "current_description": row["current_description"],
            "label": row["label"],
            "example_id": row["example_id"],
        }).encode("utf-8"))

    split_groups: dict[str, set[str]] = defaultdict(set)
    field_groups: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        split_groups[row["split"]].add(row["split_group"])
        for field in ("normalized_publisher", "repository_family", "definition_pair_hash", "near_duplicate_cluster", "template_family"):
            value = row.get(field)
            if value:
                field_groups[field][row["split"]].add(str(value))
    checks = {}
    for field, by_split in field_groups.items():
        overlaps = {}
        names = list(by_split)
        for index, left in enumerate(names):
            for right in names[index + 1 :]:
                overlaps[f"{left}:{right}"] = sorted(by_split[left] & by_split[right])[:5]
        checks[field] = {"disjoint": all(not values for values in overlaps.values()), "overlap_examples": overlaps}
    checks["content_sha256_unique"] = len({row["content_sha256"] for row in rows}) == len(rows)
    checks["split_group_disjoint"] = all(not (split_groups[a] & split_groups[b]) for a, b in itertools.combinations(split_groups, 2))
    if not all(item.get("disjoint", item) if isinstance(item, dict) else item for item in checks.values()):
        raise AssertionError(f"split disjointness check failed: {checks}")
    summary = {"seed": SEED, "group_split": "sha256(group_id) modulo 100; 80/10/10", "checks": checks}
    return rows, summary


def _cap_publishers(rows: list[dict[str, Any]], cap: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counts: Counter[str] = Counter()
    retained: list[dict[str, Any]] = []
    clipped: Counter[str] = Counter()
    ordered = sorted(rows, key=lambda row: hashlib.sha256(str(row["example_id"]).encode()).hexdigest())
    for row in ordered:
        publisher = str(row.get("normalized_publisher") or "unknown")
        if row.get("source_kind") == "controlled_fictional":
            retained.append(row)
            continue
        if counts[publisher] >= cap:
            clipped[publisher] += 1
            continue
        counts[publisher] += 1
        retained.append(row)
    return retained, {
        "per_publisher_cap": cap,
        "publisher_count_before_cap": len({row.get("normalized_publisher") for row in rows if row.get("source_kind") != "controlled_fictional"}),
        "publisher_count_after_cap": len(counts),
        "records_removed_by_cap": sum(clipped.values()),
        "removed_by_publisher": dict(sorted(clipped.items())),
        "retained_by_publisher": dict(sorted(counts.items())),
    }


def eligible(row: dict[str, Any]) -> bool:
    return row.get("label") in LABEL_NAMES and not row.get("capgate_family_excluded")


def count_splits(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(row["split"] for row in rows if eligible(row))


def _make_blinded_queue(rows: list[dict[str, Any]]) -> None:
    path = DATA / "blinded_review_queue.jsonl"
    fields = ["example_id", "split", "source_kind", "approved_description", "current_description", "changed_dimension", "evidence_before", "evidence_after", "provenance", "review_label", "reviewer", "review_note"]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            if row.get("split") not in {"validation", "test"}:
                continue
            # Remove gold/weak labels, model scores, and the rule that produced the label.
            item = {key: row.get(key) for key in fields}
            handle.write(canonical_json(item) + "\n")


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if (DATA / "split_manifest.json").exists() and not args.force:
        raise FileExistsError("split manifest is frozen; pass --force only to intentionally rebuild it")
    self_check_reconstruction()
    self_check_weak_labels()
    manifest_path = CACHE / "histor-2026-11-16-manifest.json"
    if not manifest_path.exists():
        if args.offline:
            raise FileNotFoundError(f"snapshot manifest is missing: {manifest_path}")
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(f"{SNAPSHOT_BASE}/manifest.json", manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for filename, expected in EXPECTED.items():
        manifest_expected = manifest.get("files", {}).get(filename, {}).get("sha256")
        if manifest_expected != expected:
            raise ValueError(f"pinned expected hash does not match downloaded manifest for {filename}")
    server_path = fetch_if_missing("servers.jsonl.gz", args.offline)
    changes_path = fetch_if_missing("changes.jsonl.gz", args.offline)
    capgate_rows, capgate_meta, capgate_sources = load_capgate()
    servers = load_servers(server_path)
    DATA.mkdir(parents=True, exist_ok=True)
    extraction_counts: Counter[str] = Counter()
    main_history: list[dict[str, Any]] = []
    publisher_candidates: Counter[str] = Counter()
    publisher_kept: Counter[str] = Counter()
    publisher_removed: Counter[str] = Counter()
    seen_main_pairs: set[str] = set()
    seen_unresolved_pairs: set[str] = set()
    seen_challenge_pairs: set[str] = set()
    unresolved_count = 0
    time_challenge_count = 0
    capgate_exclusion_count = 0
    history_duplicate_count = 0
    with (DATA / "time_challenge.jsonl").open("w", encoding="utf-8", newline="\n") as challenge_file, \
         (DATA / "unresolved_history_candidates.jsonl").open("w", encoding="utf-8", newline="\n") as unresolved_file, \
         (DATA / "capgate_repository_exclusions.jsonl").open("w", encoding="utf-8", newline="\n") as excluded_file:
        for row in extract_history(changes_path, servers, capgate_sources, extraction_counts):
            pair_key = _pair_key(row["approved_description"], row["current_description"])
            row["undirected_pair_hash"] = pair_key
            row["definition_pair_hash"] = _oriented_pair_key(row["approved_description"], row["current_description"])
            if row.get("capgate_family_excluded"):
                capgate_exclusion_count += 1
                excluded_file.write(canonical_json({
                    "example_id": row["example_id"],
                    "server_id": row["server_id"],
                    "repository": row["repository"],
                    "repository_family": row["repository_family"],
                    "tool": row["tool"],
                    "observed_at": row["observed_at"],
                    "old_toolset_digest": row["old_toolset_digest"],
                    "new_toolset_digest": row["new_toolset_digest"],
                    "definition_pair_hash": row["definition_pair_hash"],
                    "provenance": row["provenance"],
                }) + "\n")
                continue
            if row.get("observed_at") and row["observed_at"] >= TIME_CHALLENGE_AFTER:
                if pair_key in seen_challenge_pairs:
                    extraction_counts["time_challenge_exact_or_reversed_duplicate"] += 1
                    continue
                seen_challenge_pairs.add(pair_key)
                row["split"] = "time_challenge"
                challenge_file.write(canonical_json(row) + "\n")
                time_challenge_count += 1
                continue
            if row.get("label") is None:
                if pair_key in seen_unresolved_pairs:
                    extraction_counts["unresolved_exact_or_reversed_duplicate"] += 1
                    continue
                seen_unresolved_pairs.add(pair_key)
                unresolved_file.write(canonical_json(row) + "\n")
                unresolved_count += 1
                continue
            if pair_key in seen_main_pairs:
                history_duplicate_count += 1
                continue
            seen_main_pairs.add(pair_key)
            publisher = str(row.get("normalized_publisher") or "unknown")
            publisher_candidates[publisher] += 1
            if publisher_kept[publisher] >= PUBLISHER_CAP:
                publisher_removed[publisher] += 1
                continue
            publisher_kept[publisher] += 1
            main_history.append(row)

    deduped, dedup_counts = deduplicate(main_history)
    dedup_counts["exact_or_reversed_duplicate"] += history_duplicate_count
    cap_meta = {
        "per_publisher_cap": PUBLISHER_CAP,
        "cap_application_order": "first unique high-confidence rows in pinned snapshot order",
        "publisher_count_before_cap": len(publisher_candidates),
        "publisher_count_after_cap": len(publisher_kept),
        "records_removed_by_cap": sum(publisher_removed.values()),
        "removed_by_publisher": dict(sorted(publisher_removed.items())),
        "retained_by_publisher": dict(sorted(publisher_kept.items())),
    }
    dedup_counts["unresolved_exact_or_reversed_duplicate"] = extraction_counts["unresolved_exact_or_reversed_duplicate"]
    dedup_counts["time_challenge_exact_or_reversed_duplicate"] = extraction_counts["time_challenge_exact_or_reversed_duplicate"]
    history_counts = count_splits((split_rows(deduped)[0])) if deduped else Counter()
    missing = max(
        0,
        args.train_target - history_counts["train"],
        math_ceil((args.validation_target - history_counts["validation"]) / 0.1),
        math_ceil((args.test_target - history_counts["test"]) / 0.1),
    )
    family_count = min(args.max_synthetic_families, math_ceil(missing / 0.8 / 4) + 200)
    synthetic = controlled_examples(family_count, SEED) if missing else []
    all_rows, synth_dedup = deduplicate(deduped + synthetic)
    all_rows, split_check = split_rows(all_rows)
    counts = count_splits(all_rows)
    if counts["train"] < args.train_target or counts["validation"] < args.validation_target or counts["test"] < args.test_target:
        raise RuntimeError(
            "split targets not reached; increase --max-synthetic-families or adjust the group cap: "
            f"counts={dict(counts)} targets={{'train': {args.train_target}, 'validation': {args.validation_target}, 'test': {args.test_target}}}"
        )

    pair_count = write_jsonl(DATA / "pairs.jsonl", all_rows)
    _make_blinded_queue(all_rows)
    split_manifest = {
        "snapshot_date": SNAPSHOT_DATE,
        "seed": SEED,
        "split_frozen_at": datetime.now(timezone.utc).isoformat(),
        "time_challenge_after": TIME_CHALLENGE_AFTER,
        "label_order": LABEL_NAMES,
        "split_method": "group-disjoint 80/10/10 by publisher, repository, definition pair, near-duplicate cluster, and controlled template family",
        "targets": {"train": args.train_target, "validation_candidates": args.validation_target, "test_candidates": args.test_target},
        "counts": dict(sorted(counts.items())),
        "label_counts_by_split": {split: dict(Counter(LABEL_NAMES[row["label"]] for row in all_rows if row.get("split") == split and row.get("label") in LABEL_NAMES)) for split in ("train", "validation", "test")},
        "provenance_counts_by_split": {split: dict(Counter(row["label_source"] for row in all_rows if row.get("split") == split and eligible(row))) for split in ("train", "validation", "test")},
        "source_kind_counts": dict(Counter(row["source_kind"] for row in all_rows)),
        "template_family_count": len({row["template_family"] for row in all_rows if row.get("template_family")}),
        "unique_pair_count": len({row["undirected_pair_hash"] for row in all_rows}),
        "scope_only_counts": dict(Counter(row["split"] for row in all_rows if row.get("changed_dimension") == "scope" and eligible(row))),
        "publisher_cap": cap_meta,
        "deduplication": dict(dedup_counts + synth_dedup),
        "extraction_counts": dict(extraction_counts),
        "unresolved_history_count": unresolved_count,
        "time_challenge_count": time_challenge_count,
        "capgate_repository_exclusions": capgate_exclusion_count,
        "controlled_fictional_count": sum(row["source_kind"] == "controlled_fictional" for row in all_rows),
        "split_checks": split_check,
        "capgate": capgate_meta,
        "research_status": "research_only_provisional_weak_labels; no independent human review labels supplied",
    }
    write_json(DATA / "split_manifest.json", split_manifest)
    source_manifest = {
        "snapshot_date": SNAPSHOT_DATE,
        "base_url": SNAPSHOT_BASE,
        "manifest_url": f"{SNAPSHOT_BASE}/manifest.json",
        "manifest_sha256": sha256_file(manifest_path),
        "license": manifest.get("license"),
        "tree_head": manifest.get("treeHead"),
        "files": {
            name: {
                "url": f"{SNAPSHOT_BASE}/{name}",
                "sha256_expected": EXPECTED[name],
                "sha256_actual": sha256_file(CACHE / name),
                "bytes_expected": manifest["files"][name].get("bytes"),
                "bytes_actual": (CACHE / name).stat().st_size,
                "rows_expected": manifest["files"][name].get("rows"),
                "download_substitution": None,
                "used": True,
            }
            for name in EXPECTED
        },
        "omitted_large_sources": {"toolsets.jsonl.gz": "not downloaded; detailed field diffs reconstructed both description sides; missing or truncated diffs were skipped."},
        "capgate": capgate_meta,
        "source_attribution": "HISTOR dataset, CC-BY-4.0; per-row repository URLs retained. CAPGATE external diagnostics retain source and record IDs.",
    }
    write_json(DATA / "source_manifest.json", source_manifest)
    # Create a frozen split index with hashes so the trainer can refuse drift.
    split_index = [
        {"example_id": row["example_id"], "split": row["split"], "content_sha256": row["content_sha256"], "definition_pair_hash": row["definition_pair_hash"], "split_group": row["split_group"], "near_duplicate_cluster": row["near_duplicate_cluster"]}
        for row in all_rows
    ]
    write_json(DATA / "split_index.json", split_index)
    split_manifest["pairs_jsonl_sha256"] = sha256_file(DATA / "pairs.jsonl")
    split_manifest["split_index_sha256"] = sha256_file(DATA / "split_index.json")
    write_json(DATA / "split_manifest.json", split_manifest)
    return {"pair_count": pair_count, **split_manifest}


def math_ceil(value: float) -> int:
    return int(-(-value // 1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="use only cached source files")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen split")
    parser.add_argument("--train-target", type=int, default=10_000)
    parser.add_argument("--validation-target", type=int, default=1_000)
    parser.add_argument("--test-target", type=int, default=1_000)
    parser.add_argument("--max-synthetic-families", type=int, default=20_000)
    args = parser.parse_args()
    result = prepare(args)
    print(json.dumps({key: value for key, value in result.items() if key not in {"split_checks", "publisher_cap", "extraction_counts", "capgate"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
