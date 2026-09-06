import subprocess

from driftguard.history import GitSourceHistoryMiner, adjacent_version_pairs
from driftguard.source_extractors import TypeScriptRegisterToolExtractor

SOURCE_V1 = '''
const server = new McpServer({ name: 'demo', version: '1.0.0' });

server.registerTool(
  'search',
  {
    title: 'Search Tool',
    description: 'Search repository files',
    inputSchema: z.object({
      query: z.string().describe('Search query'),
      limit: z.number().default(10),
      format: z.enum(['text', 'json']).optional()
    }),
    annotations: { readOnlyHint: true }
  },
  async ({ query }) => ({ content: [{ type: 'text', text: query }] })
);
'''

SOURCE_V2 = '''
const server = new McpServer({ name: 'demo', version: '1.0.0' });
server.registerTool(
  'search',
  {
    title: 'Search Tool',
    description: 'Search repository files and include hidden files',
    inputSchema: z.object({
      query: z.string().describe('Search query'),
      limit: z.number().default(20),
      includeHidden: z.boolean().default(false)
    }),
    annotations: { readOnlyHint: true }
  },
  async ({ query }) => ({ content: [{ type: 'text', text: query }] })
);
'''


def test_typescript_register_tool_extractor_reads_literal_zod_schema():
    tools = TypeScriptRegisterToolExtractor().extract(SOURCE_V1)

    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "search"
    assert tool["title"] == "Search Tool"
    assert tool["description"] == "Search repository files"
    assert tool["inputSchema"]["properties"]["query"]["type"] == "string"
    assert tool["inputSchema"]["properties"]["query"]["description"] == "Search query"
    assert tool["inputSchema"]["properties"]["limit"]["type"] == "number"
    assert tool["inputSchema"]["properties"]["limit"]["default"] == 10
    assert tool["inputSchema"]["properties"]["format"]["enum"] == ["text", "json"]
    assert tool["inputSchema"]["required"] == ["query"]
    assert tool["annotations"]["readOnlyHint"] is True


def test_typescript_extractor_skips_dynamic_tool_names():
    source = '''
const name = getToolName();
server.registerTool(name, { description: 'Dynamic' }, async () => ({}));
'''
    assert TypeScriptRegisterToolExtractor().extract(source) == []


def test_typescript_source_history_mining(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "DriftGuard Test"], cwd=repo, check=True)

    path = repo / "server.ts"
    path.write_text(SOURCE_V1, encoding="utf-8")
    subprocess.run(["git", "add", "server.ts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "v1"], cwd=repo, check=True, capture_output=True)

    path.write_text(SOURCE_V2, encoding="utf-8")
    subprocess.run(["git", "add", "server.ts"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "v2"], cwd=repo, check=True, capture_output=True)

    miner = GitSourceHistoryMiner(
        repo,
        repository_id="owner/repo",
        source_paths=["server.ts"],
        extractor=TypeScriptRegisterToolExtractor(),
    )
    pairs = adjacent_version_pairs(miner.mine())

    assert len(pairs) == 1
    assert pairs[0][0].tool["inputSchema"]["properties"]["limit"]["default"] == 10
    assert pairs[0][1].tool["inputSchema"]["properties"]["limit"]["default"] == 20
    assert "includeHidden" in pairs[0][1].tool["inputSchema"]["properties"]
