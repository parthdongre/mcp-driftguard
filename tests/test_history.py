import json
import subprocess

from driftguard.history import GitManifestHistoryMiner, adjacent_version_pairs, parse_tool_manifest


def manifest(description):
    return {
        "tools": [
            {
                "name": "search_repo",
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ]
    }


def test_recursive_manifest_parser_finds_tool_definitions():
    tools = parse_tool_manifest(json.dumps(manifest("Search files.")))
    assert len(tools) == 1
    assert tools[0]["name"] == "search_repo"


def test_git_history_miner_extracts_changed_versions(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "DriftGuard Test"], cwd=repo, check=True)

    path = repo / "tools.json"
    path.write_text(json.dumps(manifest("Search files.")), encoding="utf-8")
    subprocess.run(["git", "add", "tools.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "v1"], cwd=repo, check=True, capture_output=True)

    path.write_text(json.dumps(manifest("Search files more clearly.")), encoding="utf-8")
    subprocess.run(["git", "add", "tools.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "v2"], cwd=repo, check=True, capture_output=True)

    miner = GitManifestHistoryMiner(
        repo,
        repository_id="owner/repo",
        manifest_paths=["tools.json"],
    )
    versions = miner.mine()
    pairs = adjacent_version_pairs(versions)

    assert len(versions) == 2
    assert len(pairs) == 1
    assert pairs[0][0].tool["description"] == "Search files."
    assert pairs[0][1].tool["description"] == "Search files more clearly."
    assert all(version.committed_at is not None for version in versions)
    assert all("T" in version.committed_at for version in versions if version.committed_at)
