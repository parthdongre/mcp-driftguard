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


def initialize_repo(path):
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "DriftGuard Test"], cwd=path, check=True)


def commit(repo, message):
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True)


def test_recursive_manifest_parser_finds_tool_definitions():
    tools = parse_tool_manifest(json.dumps(manifest("Search files.")))
    assert len(tools) == 1
    assert tools[0]["name"] == "search_repo"


def test_git_history_miner_extracts_changed_versions(tmp_path):
    repo = tmp_path / "repo"
    initialize_repo(repo)

    path = repo / "tools.json"
    path.write_text(json.dumps(manifest("Search files.")), encoding="utf-8")
    commit(repo, "v1")

    path.write_text(json.dumps(manifest("Search files more clearly.")), encoding="utf-8")
    commit(repo, "v2")

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


def test_git_history_miner_follows_file_renames_without_breaking_lineage(tmp_path):
    repo = tmp_path / "repo"
    initialize_repo(repo)

    old_path = repo / "tools.json"
    old_path.write_text(json.dumps(manifest("Search files.")), encoding="utf-8")
    commit(repo, "initial tool manifest")

    new_dir = repo / "config"
    new_dir.mkdir()
    subprocess.run(
        ["git", "mv", "tools.json", "config/tools.json"],
        cwd=repo,
        check=True,
    )
    commit(repo, "move tool manifest")

    new_path = repo / "config" / "tools.json"
    new_path.write_text(json.dumps(manifest("Search files and symbols.")), encoding="utf-8")
    commit(repo, "expand search description")

    versions = GitManifestHistoryMiner(
        repo,
        repository_id="owner/repo",
        manifest_paths=["config/tools.json"],
    ).mine()
    pairs = adjacent_version_pairs(versions)

    assert len(versions) == 2
    assert len(pairs) == 1
    assert versions[0].path == "config/tools.json"
    assert versions[1].path == "config/tools.json"
    assert versions[0].historical_path == "tools.json"
    assert versions[1].historical_path == "config/tools.json"
    assert pairs[0][0].tool["description"] == "Search files."
    assert pairs[0][1].tool["description"] == "Search files and symbols."
