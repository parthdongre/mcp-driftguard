# macOS preview: harness and enforcement regression checks

**Scope:** The bundled administrator service and Codex system policy must be validated
on a real Mac by a local administrator. CI and Linux source tests **cannot** prove
Keychain authorization, launchd activation, or system-wide enforcement.

The desktop workspace and administrator-managed gateway use different databases.
Connecting a desktop harness does **not** activate the administrator service.

## 1. Source tests (cross-platform)

From the repository root:

```sh
cargo test --locked --manifest-path rust-version/Cargo.toml --test harness_config
(cd desktop && npm ci && node --test tests/harness-state.test.mjs && npm run build)
```

Validate Codex, Claude Code, Cursor, Antigravity, Gemini, OpenCode, and VS Code
using an isolated home. Verify repeated connects, byte-perfect rollback,
preservation of unrelated edits, and stale-profile recovery.

Expected UI transition:

| Situation | Status | Action |
| --- | --- | --- |
| Detected, not managed | Detected | Connect |
| Managed, config healthy | Configured (or session attached) | Disconnect |
| Managed, configuration/profile drifted | Needs repair | Disconnect first |
| Unmanaged, previous session still running | Existing session attached | Restart client |

A disconnected managed gateway must deny any subsequent call made via an existing
gateway process. An already-running coding client can retain cached tools in its UI;
restart it to clear them. Direct, un-routed MCP connections remain outside this gate.

## 2. macOS administration, authentication, and rollback

Run on a personally controlled test Mac. Never paste Keychain items, tokens,
administrator passwords, private certificates, or raw credential output into logs.

1. Inspect the ZIP source/signature and ensure it came from a trusted build.
   Note that the preview is **ad-hoc signed and unnotarized**.
2. Quit existing Codex sessions. Run the supplied `Install DriftGuard.command`
   interactively, with a local administrator account; complete the **macOS**
   Keychain and certificate prompts. Do not attempt to bypass these prompts.
3. Run `Check Setup.command`. Confirm the service is active, the pilot call
   succeeds, and the Codex managed policy is installed.
4. Open **fresh** Codex CLI and desktop sessions and invoke
   `pilot-sample · read_sample`. Expected tool output is
   `DriftGuard live integration check`.
5. Attempt the pilot call before and after **block_tool_all** on the sample tool.
   Expect the gateway to refuse the call while blocked. Check gateway audit events
   and restore access only after confirming the denial.
6. Quarantine the reviewed sample version, verify denial, then release and
   explicitly approve the exact version. Check audit history and reconnect.
7. Restart Codex after `Turn Off Enforcement.command`. Confirm the previous
   policy/configuration has been restored. Re-install only if desired.

For a real blocking test, distinguish an MCP tool invocation from an assistant
reply that merely remembers the sample text. Inspect the actual tool activity.

## 3. Prove the enforcement boundary

**Codex policy enforcement is not an operating-system-wide firewall.**
The system policy applies to the supported Codex runtimes it governs.
A standalone Claude Code process, another IDE or a custom MCP client may still
use a direct MCP connection. Test those clients independently.

If any tested client can invoke a direct MCP tool that did not pass through the
managed DriftGuard gateway, record the result as an **enforcement bypass**, not a
successful system-wide installation. A Mac administrator prompt alone does not
establish machine-wide interception.

Codex OAuth and host-specific credentials may prevent some existing routes from
being reconfigured. Their names must be exposed in the UI as unprotected routes,
never counted as successful managed connections.

## 4. Release gates

- Rust source and desktop tests passing on macOS Apple Silicon (also Intel if supported).
- Interactive administrator authentication and Keychain tests passing on a real Mac.
- Fresh Codex CLI and Codex desktop both use the managed gateway.
- Denied and quarantined tools cannot be invoked, including by already-running
  gateway sessions; audit logs reflect denials.
- Disconnect or policy rollback preserves unrelated user configuration and rejects
  stale/edited managed entries without data loss.
- The UI distinguishes installed/configured/attached and reports skipped OAuth routes.
- No 'system-wide macOS protection' marketing claim unless separate coverage is
  demonstrated for *each* target client/process, including direct-route bypass tests.
- Signed/notarized production packages are a separate release requirement.

The November 2026 prebuilt ZIP must be **rebuilt** after source fixes. Editing a
shell launcher or test checklist does not patch its bundled native executables or
PyInstaller administrator service.
