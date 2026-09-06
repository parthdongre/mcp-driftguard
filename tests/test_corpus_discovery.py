from driftguard.corpus_discovery import discover_mcp_sources, extractable_paths_by_kind


def test_discovery_finds_extractable_python_typescript_and_json(tmp_path):
    (tmp_path / "server.py").write_text(
        '''
@mcp.tool()
def search_repo(query: str) -> str:
    """Search repository files."""
    return query
''',
        encoding="utf-8",
    )
    (tmp_path / "server.ts").write_text(
        '''
server.registerTool(
  "echo",
  { description: "Echo text", inputSchema: z.object({ text: z.string() }) },
  async ({ text }) => ({ content: [{ type: "text", text }] }),
);
''',
        encoding="utf-8",
    )
    (tmp_path / "tools.json").write_text(
        '''
{
  "tools": [
    {
      "name": "status",
      "description": "Return status",
      "inputSchema": {"type": "object", "properties": {}}
    }
  ]
}
''',
        encoding="utf-8",
    )

    discoveries = discover_mcp_sources(tmp_path)
    paths = extractable_paths_by_kind(discoveries)

    assert paths["python"] == ["server.py"]
    assert paths["typescript"] == ["server.ts"]
    assert paths["json"] == ["tools.json"]


def test_discovery_finds_bare_nested_python_tool_decorator(tmp_path):
    (tmp_path / "server.py").write_text(
        '''
class DemoServer:
    def register(self):
        @self.mcp.tool
        async def list_databases() -> list[str]:
            """List databases."""
            return []
''',
        encoding="utf-8",
    )

    discoveries = discover_mcp_sources(tmp_path)

    assert len(discoveries) == 1
    discovery = discoveries[0]
    assert discovery.kind == "python"
    assert discovery.status == "extractable"
    assert discovery.extracted_tools == 1
    assert discovery.hint_count == 1


def test_discovery_reports_unsupported_python_registration_pattern(tmp_path):
    (tmp_path / "wrapped.py").write_text(
        '''
def search_repo(query: str) -> str:
    return query

mcp.tool(search_repo)
''',
        encoding="utf-8",
    )

    discoveries = discover_mcp_sources(tmp_path)

    assert len(discoveries) == 1
    discovery = discoveries[0]
    assert discovery.kind == "python"
    assert discovery.status == "unsupported_pattern"
    assert discovery.extracted_tools == 0
    assert discovery.hint_count == 1


def test_discovery_ignores_vendor_directories(tmp_path):
    vendor = tmp_path / "node_modules" / "dependency"
    vendor.mkdir(parents=True)
    (vendor / "server.ts").write_text(
        'server.registerTool("x", { inputSchema: z.object({}) }, async () => ({}));',
        encoding="utf-8",
    )

    assert discover_mcp_sources(tmp_path) == []
