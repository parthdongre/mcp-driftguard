# First live connection

Importing a harness catalog does not connect that harness through DriftGuard.
Imports use temporary discovery sessions and separate review identities. Start
with one local server, route the client through the gateway, and approve that
running connection in the shared desktop workspace.

## Prepare a real server

Requires the installed DriftGuard source environment and Node.js 24 or newer.
From the repository root:

```bash
npm install --prefix live-validation --ignore-scripts --save-exact @modelcontextprotocol/server-filesystem@2.0.1
.venv/bin/python -m driftguard.live_setup
```

On Windows, use `.venv\Scripts\python.exe` for the second command.
This prepares `live-demo/files/check.txt`, a source profile, a Codex TOML entry,
and a Claude Code JSON entry. It does not modify harness configuration, start a
server, approve tools, or access provider accounts. The server is restricted to
the generated `live-demo/files` directory. Generated files are excluded from Git.
Existing files with different contents are preserved; choose `--output` for a
fresh directory. The helper also accepts `--server` and `--state` overrides.

## Connect Codex

1. Merge the contents of `live-demo/codex-gateway.toml` into
   `~/.codex/config.toml`. Preserve existing settings and avoid duplicate tables.
   If you use `CODEX_HOME`, use its `config.toml` instead.
2. Start Codex in a trusted project and keep that session running.
3. Open the native DriftGuard app and refresh. Review `read_text_file` under
   **live-filesystem**. A `harness:` or `import:` source is not the live gateway.
4. Approve that exact version. The legacy MCP gateway advertises and emits
   `notifications/tools/list_changed` after local catalog/review changes, allowing
   clients that support it to refresh without a reconnect. Tool listing still
   performs full verification and never grants approval itself.
5. Ask Codex to use **live-filesystem → read_text_file** to read the absolute
   `check.txt` path printed by the helper. Specifying the MCP tool avoids an
   unrelated built-in shell/file read, which would not exercise the gateway.
6. Deny the tool in DriftGuard and repeat the MCP request. It must be withheld
   or denied; no second upstream call may be recorded.

For Claude Code, merge `live-demo/claude-gateway.json` into the trusted project's
`.mcp.json`, then follow the same live review steps. The desktop connection setup
now offers separate Codex TOML and Claude Code JSON exports.

Keep the gateway session alive while reviewing. Restarting it deliberately
invalidates old session approvals. An MCP client that does not consume tool-list
notifications may not update its tool UI until it explicitly lists tools again.
The setup helper uses the documented desktop state path; if your native app uses
a different path, pass its actual path with `--state`.

Known DriftGuard gateway entries are excluded from harness fetching, so discovery
does not start a replacement session and invalidate live approvals. Temporary
Codex discovery uses command-line disable overrides for those entries without
editing configuration. Claude runtime discovery is withheld when a gateway is
configured; original configured servers remain individually selectable. Custom
wrapper commands that conceal the gateway are not automatically recognized.
Codex gateway names containing dots or other non-bare key characters cause
temporary Codex discovery to be withheld because its override parser cannot
safely exclude those names. The generated `live-filesystem` name avoids this.

## Diagnose the failing stage

| Symptom | Check |
|---|---|
| No live source in DriftGuard | Client configuration must launch the gateway and use the same `--state` path as the app. Check the client's MCP startup status. |
| Only `harness:` or `import:` sources appear | These are catalog observations. Route the client through the generated live gateway entry. |
| Python MCP cannot import its packages | Launch the environment's Python path. DriftGuard preserves venv symlinks when starting configured executables. |
| Tools remain absent after approval | Confirm approval belongs to the running live source, and the client consumes tool-list change notifications. |
| A tool is still withheld | Its output contract may use unsupported keywords, or its definition changed and requires review. |
| Hosted GitHub/Figma/etc. login is unavailable | A hosted app session cannot be borrowed by this local gateway. Configure a supported original server/endpoint with its own authentication. OAuth refresh is not implemented here. |

## What has been verified

The opt-in integration test runs the official Filesystem server 2.0.1, an actual
gateway subprocess, a JSON-RPC client, a shared SQLite file, and desktop bridge
approvals. It verifies pending tools are hidden, approval emits a list-change
notification, an approved read returns schema-validated structured output,
revocation emits another notification, and a later call is blocked. It reads
only an authored temporary file. It does not run a model turn or use user data.

```bash
DRIFTGUARD_TEST_FILESYSTEM="$PWD/live-validation/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js" .venv/bin/python -m pytest -q tests/test_real_filesystem.py
```

A separate opt-in test uses installed Codex CLI 0.165.0 to launch the gateway and
discover its pending catalog. A complete authenticated Codex/Claude chat on the
user's Mac remains a separate verification step; these tests do not establish
support for every hosted app or OAuth provider.
