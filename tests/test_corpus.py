from driftguard.canonicalize import schema_hash
from driftguard.corpus import historical_versions_to_candidates
from driftguard.history import HistoricalToolVersion


def tool(description, properties=None, required=None):
    return {
        "name": "search_repo",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {"query": {"type": "string"}},
            "required": required or ["query"],
        },
    }


def version(commit, value):
    return HistoricalToolVersion(
        repository_id="owner/repo",
        commit_sha=commit,
        path="server.py",
        tool_name="search_repo",
        tool=value,
        schema_hash=schema_hash(value),
    )


def test_history_candidates_remain_unlabeled_and_include_diff_facts():
    old_tool = tool("Search repository files.")
    new_tool = tool(
        "Search repository files using an API token.",
        properties={
            "query": {"type": "string"},
            "api_token": {"type": "string"},
        },
        required=["query", "api_token"],
    )
    candidates = historical_versions_to_candidates(
        [version("a" * 40, old_tool), version("b" * 40, new_tool)]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.provenance == "real_history"
    assert candidate.old_version_id == "a" * 40
    assert candidate.new_version_id == "b" * 40
    assert any(item.startswith("required_added:api_token") for item in candidate.suggested_evidence)
    assert any(item.startswith("sensitive_terms_added:") for item in candidate.suggested_evidence)
    assert not hasattr(candidate, "label")


def test_candidate_id_is_deterministic():
    first = historical_versions_to_candidates(
        [version("a" * 40, tool("Search files.")), version("b" * 40, tool("Search source files."))]
    )[0]
    second = historical_versions_to_candidates(
        [version("a" * 40, tool("Search files.")), version("b" * 40, tool("Search source files."))]
    )[0]

    assert first.candidate_id == second.candidate_id
