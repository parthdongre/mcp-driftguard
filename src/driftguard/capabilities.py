from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .models import CapabilityDelta, CapabilityProfile, ToolSnapshot

# These mappings are intentionally explicit and auditable. They are feature extractors,
# not a claim that a keyword proves a capability is actually implemented.
_OPERATION_TERMS: dict[str, tuple[str, ...]] = {
    "read": ("read", "view", "inspect", "search", "list", "query"),
    "write": ("write", "create", "update", "modify", "edit", "save"),
    "delete": ("delete", "remove", "erase", "destroy"),
    "execute": ("execute", "run", "shell", "command", "script"),
    "transmit": ("send", "upload", "post", "forward", "transmit", "publish"),
    "fetch": ("fetch", "download", "retrieve", "request"),
    "authenticate": ("authenticate", "login", "authorize", "oauth"),
}

_RESOURCE_TERMS: dict[str, tuple[str, ...]] = {
    "filesystem": ("file", "files", "filesystem", "directory", "path"),
    "repository": ("repository", "repo", "github", "gitlab", "source code"),
    "database": ("database", "sql", "table", "query"),
    "credentials": (
        "credential",
        "credentials",
        "token",
        "api key",
        "api_key",
        "password",
        "secret",
        "ssh key",
    ),
    "network": ("network", "url", "http", "https", "endpoint", "domain", "webhook"),
    "email": ("email", "mail", "recipient", "inbox"),
    "payment": ("payment", "card", "bank", "transaction", "invoice"),
    "process": ("process", "shell", "command", "terminal", "script"),
}

_EFFECT_TERMS: dict[str, tuple[str, ...]] = {
    "observe": ("read", "view", "inspect", "search", "list", "query", "retrieve"),
    "mutate": ("write", "create", "update", "modify", "edit", "save"),
    "destroy": ("delete", "remove", "erase", "destroy"),
    "execute": ("execute", "run", "shell", "command", "script"),
    "disclose": ("send", "upload", "post", "forward", "transmit", "share", "publish"),
}

_SCOPE_TERMS: dict[str, tuple[str, ...]] = {
    "broad": (
        "all files",
        "all repositories",
        "entire",
        "recursive",
        "wildcard",
        "any file",
        "any repository",
        "global",
    ),
    "path_scoped": ("path", "directory", "folder"),
    "repository_scoped": ("repository", "repo", "owner", "branch"),
    "recipient_scoped": ("recipient", "email", "destination"),
}

_DESTINATION_TERMS: dict[str, tuple[str, ...]] = {
    "external_network": ("http://", "https://", "external", "remote", "webhook", "endpoint", "upload"),
    "local": ("local", "localhost", "filesystem", "workspace"),
    "third_party": ("third party", "third-party", "github", "gitlab", "slack", "discord", "email"),
}

_SENSITIVITY_TERMS: dict[str, tuple[str, ...]] = {
    "secrets": (
        "credential",
        "credentials",
        "token",
        "api key",
        "api_key",
        "password",
        "secret",
        "ssh key",
    ),
    "personal_data": ("personal", "pii", "phone", "address", "user data", "private"),
    "financial": ("payment", "card", "bank", "transaction", "financial"),
    "source_code": ("source code", "private repository", "private repo", "repository", "repo"),
}


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value) if value is not None else ""


def _contains(text: str, term: str) -> bool:
    # Phrases and punctuation-heavy terms are searched literally; simple tokens use boundaries.
    if any(char in term for char in " /_.:-"):
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _match_categories(
    text: str, mapping: dict[str, tuple[str, ...]]
) -> tuple[list[str], dict[str, list[str]]]:
    matched: list[str] = []
    evidence: dict[str, list[str]] = {}
    for category, terms in mapping.items():
        hits = sorted({term for term in terms if _contains(text, term)})
        if hits:
            matched.append(category)
            evidence[category] = hits
    return sorted(matched), evidence


def extract_capability_profile(snapshot: ToolSnapshot) -> CapabilityProfile:
    """Extract an interpretable capability profile from one canonical tool definition."""

    text = _flatten(snapshot.canonical_tool).lower()
    operations, op_evidence = _match_categories(text, _OPERATION_TERMS)
    resources, resource_evidence = _match_categories(text, _RESOURCE_TERMS)
    effects, effect_evidence = _match_categories(text, _EFFECT_TERMS)
    scopes, scope_evidence = _match_categories(text, _SCOPE_TERMS)
    destinations, destination_evidence = _match_categories(text, _DESTINATION_TERMS)
    sensitivity, sensitivity_evidence = _match_categories(text, _SENSITIVITY_TERMS)

    evidence: dict[str, list[str]] = {}
    for prefix, bucket in (
        ("operation", op_evidence),
        ("resource", resource_evidence),
        ("effect", effect_evidence),
        ("scope", scope_evidence),
        ("destination", destination_evidence),
        ("sensitivity", sensitivity_evidence),
    ):
        for key, hits in bucket.items():
            evidence[f"{prefix}:{key}"] = hits

    return CapabilityProfile(
        operations=operations,
        resources=resources,
        effects=effects,
        scopes=scopes,
        destinations=destinations,
        sensitivity=sensitivity,
        evidence=evidence,
    )


def _added_removed(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    old_set, new_set = set(old), set(new)
    return sorted(new_set - old_set), sorted(old_set - new_set)


def capability_delta(old: CapabilityProfile, new: CapabilityProfile) -> CapabilityDelta:
    operations_added, operations_removed = _added_removed(old.operations, new.operations)
    resources_added, resources_removed = _added_removed(old.resources, new.resources)
    effects_added, effects_removed = _added_removed(old.effects, new.effects)
    scopes_added, scopes_removed = _added_removed(old.scopes, new.scopes)
    destinations_added, destinations_removed = _added_removed(old.destinations, new.destinations)
    sensitivity_added, sensitivity_removed = _added_removed(old.sensitivity, new.sensitivity)
    return CapabilityDelta(
        operations_added=operations_added,
        operations_removed=operations_removed,
        resources_added=resources_added,
        resources_removed=resources_removed,
        effects_added=effects_added,
        effects_removed=effects_removed,
        scopes_added=scopes_added,
        scopes_removed=scopes_removed,
        destinations_added=destinations_added,
        destinations_removed=destinations_removed,
        sensitivity_added=sensitivity_added,
        sensitivity_removed=sensitivity_removed,
    )


def capability_escalation_score(delta: CapabilityDelta) -> float:
    """Return a bounded, transparent severity feature for newly implied capabilities.

    This is a feature for research baselines, not the final security verdict.
    """

    weights = {
        "write": 0.14,
        "delete": 0.24,
        "execute": 0.28,
        "transmit": 0.24,
        "authenticate": 0.12,
    }
    score = sum(weights.get(item, 0.04) for item in delta.operations_added)
    score += 0.12 * len(delta.effects_added)
    if "disclose" in delta.effects_added:
        score += 0.20
    if "external_network" in delta.destinations_added:
        score += 0.20
    if "broad" in delta.scopes_added:
        score += 0.16
    score += 0.16 * len(delta.sensitivity_added)
    if "credentials" in delta.resources_added or "secrets" in delta.sensitivity_added:
        score += 0.22
    return round(min(1.0, score), 6)
