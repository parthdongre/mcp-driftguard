# DriftGuard desktop research preview

React/TypeScript/Vite interface with a Tauri 2 shell. This is a development
prototype requiring a local Python environment; no signed installer is delivered.

## Browser interface

From the repository root:

```bash
# macOS/Linux:
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]' -c requirements/core-constraints.txt
# Windows PowerShell:
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements/core-constraints.txt
```

Then, in `desktop/`:

```bash
npm ci
npm run dev
```

Open the shown loopback URL. Browser mode cannot protect MCP clients or write the
native review store. Its guided detector fixture is explicit and isolated. The
annotation workspace runs locally and exports human-entered JSONL; no model labels
are fabricated. Labels remain in memory across page navigation; export before
closing the browser. Never treat automated QA fixture labels as research evidence.

## Native development

Install [Tauri platform prerequisites](https://v2.tauri.app/start/prerequisites/)
and Rust. Set a trusted absolute Python executable from the virtual environment.
Do not use a system/user-site installation: native invocation uses Python `-I`.

macOS/Linux, from `desktop/`:

```bash
export DRIFTGUARD_PYTHON="$(cd .. && pwd)/.venv/bin/python"
npm run desktop:dev
```

Windows PowerShell, from `desktop/`:

```powershell
$env:DRIFTGUARD_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
npm run desktop:dev
```

The default store is the OS app-data directory for `io.driftguard.desktop`, with
filename `guard.sqlite3`. Pass the same absolute path to the gateway `--state`:

| OS | Expected default path |
|---|---|
| macOS | `~/Library/Application Support/io.driftguard.desktop/guard.sqlite3` |
| Windows | `%APPDATA%\io.driftguard.desktop\guard.sqlite3` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/io.driftguard.desktop/guard.sqlite3` |

Actual paths depend on OS environment settings. Only a client explicitly routed
through the stdio gateway is mediated. See [GATEWAY.md](../docs/GATEWAY.md) for
configuration and [SECURITY_MODEL.md](../docs/SECURITY_MODEL.md) for limits. A stdio
server runs with user permissions; launching it is not sandboxing.

Manual imports use a distinct namespace and cannot authorize a live server. Live
sessions must be reviewed through the shared store after connecting. Desktop
status does not establish that a gateway process is currently running.

## Checks

```bash
npm test
npm run build
npx playwright install chromium
npm run test:browser
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
npm run desktop:build -- --no-bundle
```

Browser tests serve the built `dist/` in the same process. They use an isolated
fixture and a temporary SQLite database through a test-only IPC stand-in. They do
not verify native Rust IPC. `DRIFTGUARD_PREVIEW_URL` selects an existing local
preview; `DRIFTGUARD_BROWSER_EXECUTABLE` can select an installed test Chromium.
`DRIFTGUARD_TEST_PYTHON` selects the Python test environment. QA screenshots are
temporary ignored files under `verification/`.

Regenerate guided evidence with `python desktop/scripts/generate-demo.py` from the
repository root after core changes. Evidence and release limits are recorded in
[RELEASE_READINESS.md](../docs/RELEASE_READINESS.md).

## Native bridge regression checks

From the repository root with Rust/Cargo on PATH:

```bash
python desktop/scripts/check-native.py
# Linux process-helper verification without GTK/Tauri GUI prerequisites:
python desktop/scripts/check-native.py --headless
```

The runner creates an ignored desktop/.venv-native, installs the constrained core,
and requires that absolute venv executable for Rust tests. Tests cover actual
Unicode import/review/approval, stale revisions, quarantine, blocked input/output,
size limits, malformed envelopes and exit status. Headless mode copies process
helpers/tests unchanged, strips only Tauri GUI wiring and rejects any dependency
identity differing from the production Cargo.lock. It is not a GUI launch test.

A timed-out mutation may already have committed. Refresh before another decision;
the native bridge does not automatically repeat requests. See the security model
for Windows worker and descendant-lifetime limitations.
