# ADR: native shell around the existing Python engine

Status: accepted for an internal prototype; distribution decision remains provisional.

The codebase already contains a tested Python research engine. Rewriting it would
create a second scientific implementation and new correctness risks before data
supports model selection. Use Tauri 2, React, TypeScript and Vite for a native shell,
with one allowlisted JSON bridge to the retained engine.

| Option | Advantage | Cost / decision |
|---|---|---|
| Tauri + Python | OS WebView, restrained native shell, preserves scientific code | Selected; OS build prerequisites and Python deployment remain platform-specific |
| Electron + Python | Consistent Chromium and mature desktop integration | Additional embedded runtime and distribution size; no demonstrated need yet |
| Python-only desktop toolkit | Fewer language boundaries | More design/platform integration tradeoffs; not selected for this UI iteration |
| Rewrite security/research in Rust | Potential small native default runtime | Duplicates research semantics; unsupported by current evidence |

## Prototype bridge

The native host resolves its application-data directory. It accepts only review
operations and invokes a fixed module with `DRIFTGUARD_PYTHON`, an absolute trusted
virtual-environment executable, using Python `-I`. The renderer cannot choose the
executable, database or module. No shell, HTTP service, browser auth integration,
filesystem plugin or remote analysis provider is enabled. The response is bounded
and one async deadline covers queueing, stdin, stdout/stderr and process exit.
Tokio is already part of Tauri's dependency graph; explicitly enabling its small
process/I/O feature set avoids unbounded synchronous writes and reader joins.
This change follows reproduced pipe/deadline failure scenarios, not a performance
claim. Cancellation requests direct-child cleanup; Windows internal pipe workers
and descendants may outlive a request, and OS calls are not hard real-time. Permission/capability files restrict this command to
the local main window. Native code remains privileged and must be independently
reviewed; CSP is defense in depth, not a substitute for boundary validation.

## Packaging strategies

| Strategy | Current state | Release criterion |
|---|---|---|
| User-installed virtual environment | Implemented development path | Exact installation and shared-DB workflow verified per OS |
| Frozen minimal Python sidecar | Candidate for normal installation | Reproducible per-platform builds, dependency inventory, signing and update validation |
| Dedicated minimal native security core + optional Python research worker | Possible later separation | Cross-implementation invariants and measured benefit justify extra maintenance |

Keep large ML packages and models out of the default installer. A future sidecar
should expose the same bounded protocol and deterministic gate. No unsigned
prototype is represented as a production-certified defense. Installer publication,
signing/notarization, notifications, credential vaults and updates are not complete.

Primary Tauri references: [security](https://v2.tauri.app/security/),
[capabilities](https://v2.tauri.app/security/capabilities/),
[CSP](https://v2.tauri.app/security/csp/), and
[prerequisites](https://v2.tauri.app/start/prerequisites/).
