# Release readiness

**Reviewable internal prototype; not ready for native production release or
publication-grade research claims.** No public branch, installer, research corpus
or manuscript submission was published during this work.

| Area | Present evidence | Release blocker / limitation |
|---|---|---|
| Correctness | 217 Python tests passed, 1 optional skip; schema/integrity/research regressions covered | Independent audit and optional-model paths remain |
| Consent | Exact hash, revision, principal, server/session, protocol and policy binding; persistent quarantine; local dispatch transaction | Remote check/use race only reduced; no distributed audit/effect transaction or exactly-once guarantee |
| Gateway | Tools-only stdio subset for 2026-07-28 and separately configured 2025-11-25; subprocess tests | HTTP/OAuth, callbacks/subscriptions/cancellation and broad MCP parity absent |
| Untrusted runtime | Bounded input, fixed action surface, timeouts, session invalidation and text output checks | No sandbox, Windows Job Object guarantee, dependency attestation, broad DLP or arbitrary prompt-injection protection |
| Desktop | 6 logic tests, production build, 20 browser checks and 5 sampled accessibility states pass | Browser test IPC uses Python/SQLite; native Rust IPC unexercised |
| Platforms | Tauri source, Rust formatting and native macOS/Windows CI definition | Linux cargo check blocked by missing pkg-config/GTK-WebKit prerequisites; no native target built/launched; remote CI unrun |
| Distribution | Attribution retained; npm/Cargo locks, runtime constraints and wheel smoke check | No bundled Python, signing/notarization, installers, secure updates or OS installation verification |
| Privacy | Local state, metadata-only audit, no configured cloud/telemetry; new POSIX DB 0600 and own directories 0700 | No OS vault, retention/rotation UI, DB encryption or complete export anonymization guarantee; descriptors may be sensitive |
| Dependencies | Dated Python runtime and npm lookups report no known advisories | Local secret scan reviewed 71 candidates as identity hashes/test marker; Rust audit and full supply-chain review pending |
| Data | 494 primary candidates from 11 groups, 227 reference rows, 721 exact reproductions | 0 human labels; language/source concentration, licensing/extraction review and >=30 contributing primary groups still required |
| Research | Narrow hypothesis, verified overlap, corrected utilities, controlled experiments explicitly ineligible | No frozen independent final evaluation, complete baselines/ablations, repeated seeds or final manuscript |
| Authorization | Dedicated local branch; original main unchanged | Owner approval required before public restricted artifacts, installers or merging main |

## Visible security boundaries

Only explicitly routed supported connections are covered. Every changed exact tool
definition needs reapproval. Reduced re-consent at comparable security recall is
**not demonstrated**; it remains a research hypothesis. Quarantine may include
heuristic false positives and is latched for the exact definition. Recovery needs
separately reviewed authority rather than silently clearing evidence.

A malicious server can change a handler without changing its declaration, access
local resources under the user's privileges or race a descriptor check. Config
hashes and self-reported metadata do not prove behavior. The gateway does not
establish end-to-end formation consistency or complete cross-tool information-flow
control. Graph witnesses describe supplied evidence, not enforcement. Heuristic
risk floors are not calibrated probabilities.

## Release sequence

1. Review the patch/security model; run native CI and ordinary/failure workflows
   on actual macOS/Windows/Linux targets.
2. Resolve native integration, credentials, packaging and update trust; independently
   review authorization, IPC, transport and recovery.
3. Freeze dependencies/artifacts and build provenance; verify installation,
   accessibility, lifecycle and performance on target systems.
4. Finish independent annotation, licensing and preregistered evaluation before
   separately releasing research data or a paper.
5. Obtain explicit owner approval for the concrete public release or main merge.

Results: [CROSS_PLATFORM_TESTING.md](CROSS_PLATFORM_TESTING.md).
Progress: [IMPLEMENTATION_PROGRESS.md](IMPLEMENTATION_PROGRESS.md).
Boundaries: [SECURITY_MODEL.md](SECURITY_MODEL.md).
