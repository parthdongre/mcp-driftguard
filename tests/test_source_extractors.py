import subprocess

from driftguard.history import GitSourceHistoryMiner, adjacent_version_pairs
from driftguard.source_extractors import PythonDecoratorToolExtractor


SOURCE_V1 = '''
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def search_repo(query: str, limit: int = 10) -> list[str]:
    """Search repository source files."""
    return []
'''

SOURCE_V2 = '''
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")

@mcp.tool(description="Search repository source files and return structured matches.")
def search_repo(query: str, limit: int = 20, include_hidden: bool = False) -> list[str]:
    return []
'''


def test_python_decorator_extractor_builds_static_schema():
    extractor = PythonDecoratorToolExtractor()
    tools = extractor.extract(SOURCE_V1)

    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "search_repo"
    assert tool["description"] == "Search repository source files."
    assert tool["inputSchema"]["properties"]["query"]["type"] == "string"
    assert tool["inputSchema"]["properties"]["limit"]["type"] == "integer"
    assert tool["inputSchema"]["properties"]["limit"]["default"] == 10
    assert tool["inputSchema"]["required"] == ["query"]


def test_python_extractor_skips_context_parameters():
    source = '''
@mcp.tool()
async def read_file(path: str, ctx: Context) -> str:
    """Read a file."""
    return ""
'''
    tool = PythonDecoratorToolExtractor().extract(source)[0]
    assert set(tool["inputSchema"]["properties"]) == {"path"}


def test_source_history_miner_tracks_decorator_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "DriftGuard Test"], cwd=repo, check=True)

    path = repo / "server.py"
    path.write_text(SOURCE_V1, encoding="utf-8")
    subprocess.run(["git", "add", "server.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "v1"], cwd=repo, check=True, capture_output=True)

    path.write_text(SOURCE_V2, encoding="utf-8")
    subprocess.run(["git", "add", "server.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "v2"], cwd=repo, check=True, capture_output=True)

    miner = GitSourceHistoryMiner(
        repo,
        repository_id="owner/repo",
        source_paths=["server.py"],
        extractor=PythonDecoratorToolExtractor(),
    )
    versions = miner.mine()
    pairs = adjacent_version_pairs(versions)

    assert len(versions) == 2
    assert len(pairs) == 1
    assert pairs[0][0].tool["inputSchema"]["properties"]["limit"]["default"] == 10
    assert pairs[0][1].tool["inputSchema"]["properties"]["limit"]["default"] == 20
