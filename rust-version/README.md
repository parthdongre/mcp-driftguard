# DriftGuard Rust port

DriftGuard Rust includes a tools-only MCP gateway, a local review database, and
managed connections for Codex, Claude Code, Cursor, Antigravity, Gemini CLI,
OpenCode, and VS Code / Copilot.

## Desktop

### Build and test on macOS

Install Node.js 22 or newer, Rust 1.89 or newer, and the Xcode Command Line
Tools (`xcode-select --install`). Run these commands from the checkout:

```sh
cd desktop
npm ci
npm run desktop:package:rust -- --bundles app
open "src-tauri/target/release/bundle/macos/MCP DriftGuard Rust.app"
```

To try hosted connectors, sign in to Codex on this Mac, then open
**MCP connections → Gateway servers → Connect Codex hosted apps**.
Choose **Launch gateway-only Codex** and complete its separate sign-in if
prompted. Available tools depend on the signed-in account and gateway policy.
Check **MCP graph → MCP activity log** for calls through the gateway.

### Other platforms and development

Build from `desktop/` after running `npm ci` and installing the Tauri platform
prerequisites. Rust 1.89 or newer is required for file locking.

```sh
npm run desktop:package:rust -- --bundles app
```

Use `--bundles nsis` on Windows or `--bundles deb` on Linux. The Rust desktop
package uses the `io.driftguard.desktop.rust` app-data directory and
`guard-rust.sqlite3`. For a debug build, set `DRIFTGUARD_RUST_ENGINE` to the
absolute path of the built Rust executable before starting Tauri.

Open **MCP connections**, select **Connect** next to your coding client, and
open a new session in that client. The desktop uses a built-in sample that
returns fixed text. Select **Review tools** to review and approve the sample
after the client attaches. To connect a different trusted server from the
desktop, set `DRIFTGUARD_RUST_PROFILE` to its absolute profile path before
launching the app, or use the CLI commands below.

In **MCP connections**, choose **Route existing Codex MCPs** to put compatible
user-configured Codex servers behind the Rust gateway under their original
server names. Start a fresh Codex session after routing. The app routes local
stdio entries and supported HTTPS entries authenticated with a bearer
environment variable. It reports skipped entries, including Codex-hosted apps
and remote OAuth connections. **Restore direct connections** undoes routing.

In **Settings → Automatic MCP approvals**, choose declared read-only tools
(the default), all compatible first-seen tools, or manual approval. This policy
applies to managed harness routes. Changes to existing definitions go through
the configured decision model or review. Explicit blocks and quarantines take
precedence. Hosted apps such as those under Codex's `codex_apps` catalog
require access controls in Codex itself.

**MCP connections → Gateway servers** registers a local stdio command or an
HTTPS MCP endpoint in the shared SQLite workspace. Saving checks its tool
catalog. The graph shows configured servers even before a harness attaches.
Select Codex, Claude Code, Cursor, Antigravity, Gemini CLI, OpenCode, or
VS Code / Copilot and click **Add to harness**. Open a new harness session
to use that server. Other stdio clients can use the generated entry under
**Harness configuration**.

Use **Connect Codex hosted apps** to register a broker backed by your
signed-in local Codex runtime. In **Gateway-only Codex**, the native hosted
catalog is disabled. Compatible hosted tools are available through the
`codex-hosted` gateway and use the same approvals, quarantine, shared
blocks, and activity log as other gateway routes. Existing catalog denials
and quarantines are copied when a hosted tool is first observed on a
managed route. Only tools with supported names and contracts are offered.
The broker can only call the hosted catalog, and Codex can still reject
a call under its own account or approval policy.

The Binance preset uses its public HTTPS MCP endpoint. The Alpaca preset
starts its standalone Trading MCP and reads credentials from named
environment variables. Configure those variables before launching the desktop
and the harness. HTTPS bearer tokens use the OS credential store. For
Codex-managed OAuth connections, **Sign in** delegates browser authorization
to Codex. That OAuth session applies to Codex's connection. Gateway HTTPS
routes support public access and bearer tokens.

The desktop discovers enabled MCP servers at startup and when a client is
connected. It queries Codex’s runtime catalog, including tools exposed through
its plugins and connectors, and scans supported entries in client settings.
GitHub, Canva, and other connectors have named entries in MCP connections,
Security review, and the MCP graph. Definitions appear in Security
review and the MCP graph before a client session starts. These catalog scans
use MCP discovery only. The connection page shows unavailable servers and
offers **Rescan MCPs** after configuration changes. Client-specific
authentication and project or hosted catalogs can require separate setup.

The Rust desktop opens on **MCP graph** by default. Managed tool calls
highlight the harness, server, and tool. **Follow live activity** focuses
the most recent route. Select a server or tool to pause following while you
inspect its evidence. The **MCP activity log** under the graph shows catalog
checks, discoveries, definition changes, policy decisions, and call outcomes
from the local database. The log records metadata about calls without saving
their arguments or results. Imported definitions and directly connected
harness catalogs appear as review sources with catalog checks.

Open **Settings → MCP monitoring and graph** to change the startup page,
live following, activity highlights, successful check visibility, and
catalog check intervals. Discovered harness catalogs refresh every five minutes
by default while the desktop is open.

### Sentinel

Open **MCP graph → Sentinel · Time Machine** to view managed calls, filter by
gateway session and status, and inspect the recorded tool definition and
preceding policy events. The last successful call helps identify changes.
Policy comparison evaluates recorded version eligibility without replaying
requests. The gateway prunes call records older than 30 days at startup.
**Clear call history** removes finished and inactive call records while
keeping tool reviews and security decisions.

Select a managed route to stop its configured server across current and future
Rust gateway routes in the same workspace. Resuming the server leaves tool
blocks, quarantines, and version approvals in force. Calls admitted before the
stop can finish. Gateway session identifiers describe a gateway connection.

The gateway checks outgoing arguments for configured credentials and private
key markers. It keeps up to 1,024 session-local fingerprints of values from
recognized credential fields in validated structured results. It blocks exact
reuse of those values in later arguments on the same connection. Text-only
and transformed values and calls outside that connection are outside this
correlation scope.

**MCP connections → Harness helpers** inventories user-level Codex and Claude
Code skills, instructions, hook definitions, plugin settings, and selected
permission settings. It also tracks Claude Code subagents and commands.
DriftGuard scans when the desktop opens and every 30 seconds while it is
open. The first scan sets the baseline. Subsequent scans record additions,
edits, and removals in the local database. The inventory stores names and
fingerprints and runs no helper commands.

## Gateway and harness CLI

From the project root, build the release executable and run the benchmark.

```sh
cargo build --locked --release --manifest-path rust-version/Cargo.toml
.venv/bin/python rust-version/benchmark.py --runs 15 --output rust-version/benchmark-results.json
```

To try the standalone bridge with a disposable database, send one JSON
request on standard input.

```sh
db_dir="$(mktemp -d)"
printf '%s\n' '{"action":"overview"}' |
  rust-version/target/release/driftguard-rust --db "$db_dir/review.sqlite3"
```

For a local MCP server, create a JSON profile with `server_id`, `argv`, and
`cwd`. Use an absolute working directory. The optional `pass_env` lists
environment variables to forward.

```json
{
  "server_id": "files",
  "argv": ["/absolute/path/to/node", "/absolute/path/to/dist/index.js", "/absolute/path/to/workspace"],
  "cwd": "/absolute/path/to/workspace",
  "protocol_version": "2025-11-25"
}
```

For a remote server, set `transport` to `http` and specify an HTTPS `url`.
Bearer authentication can use `auth_token_env` or `use_os_vault`. The gateway
uses endpoint-bound credentials and supports Streamable HTTP JSON and SSE
responses. Both transports support the legacy handshake and the 2026-07-28
protocol when selected explicitly.

```sh
engine="$PWD/rust-version/target/release/driftguard-rust"
db="$db_dir/review.sqlite3"
"$engine" --db "$db" scan /path/to/server.json
"$engine" --db "$db" harness list
"$engine" --db "$db" harness connect codex /path/to/server.json
"$engine" --db "$db" harness disconnect codex
```

Use `claude`, `cursor`, `antigravity`, `gemini`, `opencode`, or `vscode`
in place of `codex`. The generated entry runs `serve` on the fixed profile.
For another MCP client, configure the equivalent command and arguments
`--db /absolute/path/to/review.sqlite3 serve /absolute/path/to/server.json`.

Scans collect tool definitions for review. Gateway approvals bind to the exact
definition and verified server identity. Review a recorded version even when
the client is offline. Concurrent sessions for the same verified server share
the decision. A changed definition is evaluated again, and a changed server
identity invalidates approvals for that route. The gateway refreshes the
catalog before calls, on stdio change
notifications, every 15 seconds for two minutes after gateway tool use,
and every five minutes when idle by default. Running gateway sessions
read interval changes from the local database. HTTP also consumes change
notifications sent on POST response streams. Unsupported invocation contracts
are withheld. Disconnect removes the managed entry and stops subsequent
calls through that connection while preserving unrelated settings.

In Security review, **Block across harnesses** hides the tool from MCP discovery
and denies calls before they reach the upstream server. It applies to every Rust
gateway route in this workspace with the same configured server ID and tool
name, including future routes and tool versions. **Unblock all harnesses**
clears the shared block. Review the current definition to approve it again.
Existing route-only blocks can be cleared with **Clear route block**. Clients
that connect directly to an upstream server are outside this policy.

## Automatic decisions

A workspace can run a locally trained binary logistic model on updates to a
tool with an owner-approved baseline. The score can quarantine a version,
approve a plain description edit within the existing policy, or leave the
version pending. A blocked tool stays blocked. Releasing quarantine or
denying an exact version takes precedence over the model for that version.
First observations and other changes outside the approval policy can remain
pending. Model approvals preserve the owner-approved baseline for comparison.

Build the engine, then train on labeled DriftGuard pair JSONL. Use disjoint
repositories for training and validation and choose thresholds using held-out
evidence. These thresholds illustrate the CLI syntax.

```sh
.venv/bin/python rust-version/train_decision_model.py \
  --engine "$engine" --train train.jsonl --validation validation.jsonl \
  --id local-logistic-v1 --allow-max 0.1 --quarantine-min 0.95 --output model.json
"$engine" --db "$db" model set model.json
# Disable automation with:
"$engine" --db "$db" model clear
```

Restart the coding client after loading or clearing a model. The gateway
rejects calls through a session using an obsolete model. Model artifacts
contain weights and thresholds. DriftGuard records the artifact hash, score,
and action in Security activity. The project ships without trained weights
for this feature.

### XGBoost and MiniLM evaluation

Use three labeled pair JSONL files with separate repositories in each split.
The experiment checks for shared repositories and duplicate definition pairs
across splits. It compares the same XGBoost settings with structured and
lexical features alone and with MiniLM similarity features added. It selects
the quarantine threshold on validation data, then reports test-set precision
and recall evidence, including how often it would flag capability expansions.
The report includes input hashes, label and provenance counts, and the encoder
identifier. The experiment runs offline from the gateway and produces a report
for evaluating candidates for future deployment.

```sh
python -m pip install -e '.[ml]'
python experiments/run_semantic_xgboost.py \
  --train train.jsonl --validation validation.jsonl --test test.jsonl \
  --encoder-dir /path/to/minilm-snapshot > semantic-xgboost-report.json
```

Omit `--encoder-dir` to load the pinned public MiniLM snapshot, use
`--encoder-revision` to select another revision, or use `--structured-only`
to run XGBoost without loading an encoder.

## Benchmark and scope

Add `--filesystem-server /path/to/dist/index.js` to the benchmark command to
measure discovery against an installed Filesystem MCP server. That measurement
includes server startup in elapsed time. On macOS, the peak RSS returned by
`wait4` can include the child server's high-water mark.

The benchmark starts a fresh bridge process per request and uses the same
350 synthetic tool definitions for both engines. It checks the operation
results and records median and p95 elapsed time and per-process peak RSS.
Startup measures the first bridge request and database creation. These
measurements cover the bridge process on macOS or Linux. Full desktop launch,
live MCP startup, and tool-call latency require separate measurements.
The Python engine runs its existing schema and policy checks during the
benchmark. The Rust bridge implements a smaller set of review checks.

The Rust build covers explicitly configured MCP routes. Python research
scoring, hosted catalogs, and collection from a harness's existing MCP
configuration are separate from the managed Rust gateway. A coding client
continues to control its model provider, including OpenRouter or Ollama.
