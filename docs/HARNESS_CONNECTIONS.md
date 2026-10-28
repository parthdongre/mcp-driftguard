# Connect Codex and Claude Code

The native app discovers harness connections and collects current tool definitions
directly. You do not need to export `tools/list` JSON manually.

1. Update to the branch containing harness discovery and start the native app.
2. Open **MCP connections → Connect your coding harness**.
3. Enter an absolute project directory to include project settings. Leave it blank
   for user configuration. Click **Find harness connections**.
4. Choose **Fetch definitions** on a discovered source.
5. Open **Security review** or **Tool evolution** to inspect the collected tools.
   Use **Refresh definitions** to collect another complete observation.

Scanning only reads configuration; fetching can launch configured programs with
your user permissions. It does not call tools or start model turns. Harness
configuration is read-only, and fetched definitions use a separate `harness:`
review namespace. Approving them does not authorize gateway execution. Only
clients explicitly routed through the gateway are mediated.

## Collection adapters

| Adapter | What it collects | Local requirements |
| --- | --- | --- |
| Codex runtime | External MCP tool catalogs from `mcpServerStatus/list` through `codex app-server`, with Codex managing its connections/authentication | Current Codex CLI on PATH and its normal authentication/configuration |
| Claude Code runtime | Tools exposed by `claude mcp serve` | Claude Code CLI on PATH |
| Codex configuration | Selected stdio/HTTPS MCP server from user or selected-project `config.toml` | Installed server command or reachable endpoint |
| Claude Code configuration | Selected stdio/HTTPS MCP server from user, selected-project or project-local configuration | Installed server command or reachable endpoint |

Current Codex no longer exposes `codex mcp-server`. The App Server adapter uses
its separate JSONL protocol and is experimental. Its MCP catalog does not expose
Codex's built-in shell/edit tools, an existing chat's full prompt, or an arbitrary
running session. No session attachment or interception is implied.

Configuration discovery supports:

- Codex: `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`) and the selected
  project's `.codex/config.toml`; selected-project entries override user entries.
- Claude Code: `~/.claude.json`, or `.claude.json` within `CLAUDE_CONFIG_DIR`, plus
  the selected project's `.mcp.json` and `projects[absolute_project_path].mcpServers`
  in the user file. Local entries override project entries, then user entries.
- Configured environment values and local `env_vars` are used in the child only.
  Claude `${VAR}` / `${VAR:-default}` expansion is supported. Launch the app from
  the terminal containing required environment variables.
- HTTPS public endpoints, bearer environment references and static bearer headers.
  Tokens and raw arguments are not returned by scanning. Known configured
  environment/bearer values echoed in catalogs are rejected before persistence.

This is a focused configuration adapter, not a complete reimplementation of
either harness's policy/config layering. It does not enumerate enterprise managed
settings, plugin manifests, remote executor environments or Claude cloud
connectors. Use Codex runtime discovery for its effective available MCP catalog.
Direct HTTP collection does not extract harness OAuth caches or execute header
helpers. Custom headers, SSE/WebSocket and plaintext HTTP are unavailable in
direct collection. Unsupported entries explain their status without execution.

The native app must inherit the CLI's PATH. If a runtime source is absent, start
DriftGuard from the terminal where `codex` or `claude` works. Browser preview
cannot read local harness configuration or launch processes.

## Failure behavior and limits

Fetch binds a freshly rescanned selection to the configuration digest shown by
the last scan. It checks again before saving. Configuration edits require another
scan. Catalog collection finishes before ingestion; invalid schemas, repeated
cursors, timeouts and known credential echoes do not save a partial catalog.
Fetched processes are closed after collection, and no gateway heartbeat is set.

Collection has a 12-second wire-operation budget, at most 20 pages, 500 tools
and 2 MiB of catalog data. OS process/filesystem scheduling is not a hard real-time
guarantee. A slow or large harness installation may exceed these preview limits.
The native bridge retains its 20-second outer deadline. Existing documented
Windows descendant/worker cleanup limitations still apply.

## Verification

`tests/test_harnesses.py` uses disposable configuration homes, actual Python
subprocesses and a loopback HTTP fixture. It checks scope precedence, discovery
without execution, MCP and Codex JSONL framing, pagination, stale configuration,
credential handling, timeouts, child cleanup and persistent review isolation.
These are protocol contract fixtures, not tests of installed Codex/Claude binaries.

Local validation on 2026-10-28: 292 Python tests passed, one native credential-store
test skipped; nine frontend logic tests passed; TypeScript production build and
source/test lint passed. Browser execution was blocked by an invalid Chromium
download, and the separate cloud browser could not reach workspace localhost.
Rust/Cargo and installed Codex/Claude CLIs are unavailable on this validation host,
so native compilation and installed-harness compatibility remain unverified.

The browser QA script also includes a renderer → Python bridge → disposable MCP
child → SQLite → review flow. Its IPC stand-in does not verify native Rust IPC.
Run `npm run test:browser` with Playwright Chromium installed, and run the native
bridge tests on a host with Rust before relying on native packaging.

Official integration contracts checked on 2026-10-28:

- https://developers.openai.com/codex/mcp/
- https://developers.openai.com/codex/app-server/
- https://learn.chatgpt.com/docs/mcp-server
- https://code.claude.com/docs/en/mcp
