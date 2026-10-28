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

Connection names, definition fields, activity entries and settings use compact
disclosure rows. Click a name or focus its disclosure and press Enter/Space to
show its description, controls and diagnostic details. The interface uses native
system typography, including the macOS interface font, without remote font files.

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
| Codex configuration | A selected server through Codex App Server when its CLI is installed; direct stdio/HTTPS otherwise | Codex CLI, or an installed server command/reachable endpoint |
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

When the Codex CLI is available, selecting an individual Codex server sends
`serverName` to App Server. Codex applies its own configuration, supported
transports, credential handling and workspace trust. Environment variables
explicitly referenced by its server configuration are forwarded; unrelated
environment secrets are not. Disabled entries stay disabled. No authentication,
TLS, workspace-trust or harness permission checks are bypassed.

The native app must inherit the CLI's PATH. If a runtime source is absent, start
DriftGuard from the terminal where `codex` or `claude` works. Browser preview
cannot read local harness configuration or launch processes.

If scanning fails, the interface now preserves native bridge error messages
(including Rust string rejections). Run `npm run desktop:check` from `desktop/`
to verify that the source development engine is installed and imports correctly.
The development launcher selects the repository `.venv` automatically. A stale
`DRIFTGUARD_PYTHON` override must be corrected or unset before restarting.

## Failure behavior and limits

Fetch binds a freshly rescanned selection to the configuration digest shown by
the last scan. It checks again before saving. Configuration edits require another
scan. Catalog collection finishes before ingestion; invalid schemas, repeated
cursors and known credential echoes do not save an incomplete server catalog.
Fetched processes are closed after collection, and no gateway heartbeat is set.

Codex startup/authentication failures are reported per server. Complete healthy
catalogs can still be collected, and unavailable servers retain previous
observations. If the overall deadline expires after complete catalogs have been
received, those can be saved with an explicit warning to fetch remaining servers
individually. No incomplete tool catalog is substituted for a failed server.

Collection has a 12-second wire-operation budget. Direct collection allows 20
pages, 500 tools and 2 MiB. Codex uses one server per page, at most 200 servers,
5,000 tools and 8 MiB total; each stored server catalog retains the store's
500-tool/2-MiB limits. OS process/filesystem scheduling is not a hard real-time
guarantee. A slow or large harness installation may exceed these preview limits.
The native bridge retains its 20-second outer deadline. Existing documented
Windows descendant/worker cleanup limitations still apply.

## Verification

`tests/test_harnesses.py` uses disposable configuration homes, actual Python
subprocesses and a loopback HTTP fixture. It checks scope precedence, discovery
without execution, MCP and Codex JSONL framing, pagination, stale configuration,
credential handling, timeouts, child cleanup and persistent review isolation.
Most are protocol contract fixtures. An opt-in test also exercises an installed
Codex CLI using a disposable configuration and MCP server, with no model turns
or tool calls. Run it by setting `DRIFTGUARD_TEST_CODEX` to an installed CLI path.

Local validation on 2026-10-28: 299 Python tests passed, one native credential-store
test skipped, including real Codex CLI 0.165.0 discovery against an isolated MCP
fixture. Sixteen frontend logic/rendering tests passed; TypeScript production
build and source/test lint passed. Browser execution was blocked by an invalid Chromium
download, and the separate cloud browser could not reach workspace localhost.
Rust/Cargo and an installed Claude CLI are unavailable on this validation host.
Native compilation, macOS GUI behavior and the user's authenticated MCP endpoints
remain unverified. The Codex vendor test does not validate real provider OAuth.

The browser QA script also includes a renderer → Python bridge → disposable MCP
child → SQLite → review flow. Its IPC stand-in does not verify native Rust IPC.
Run `npm run test:browser` with Playwright Chromium installed, and run the native
bridge tests on a host with Rust before relying on native packaging.

Official integration contracts checked on 2026-10-28:

- https://developers.openai.com/codex/mcp/
- https://developers.openai.com/codex/app-server/
- https://learn.chatgpt.com/docs/mcp-server
- https://code.claude.com/docs/en/mcp
