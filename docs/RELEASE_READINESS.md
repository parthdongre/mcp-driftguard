# Release readiness

**Unsigned review preview. Production signing and publication-grade research remain
separate completion gates.** Source and review documentation are on the approved
feature branch; main is preserved. Preview artifacts are produced only after their
installation/runtime/startup checks pass. No public production release or manuscript
submission is claimed.

| Area | Implemented | Remaining boundary |
|---|---|---|
| Engine correctness | Literal-safe schemas, exact identity/revision binding, bounded catalogs, persistent quarantine and evaluation safeguards | Independent audit and optional-model paths |
| Gateway | Real stdio and configured HTTPS upstreams; JSON/SSE; current routing headers; complete pre-call relisting; metadata audit and text egress checks | Tools-only subset; no OAuth, MRTR/subscriptions, broad DLP, sandbox, handler attestation or distributed exactly-once guarantee |
| Credentials | Endpoint-bound macOS Keychain / Windows Credential Manager / Linux Secret Service access; no plaintext fallback; stored values never returned to renderer | Linux needs an unlocked Secret Service session; credentials exist in process memory; no OAuth discovery or refresh |
| Desktop | Review/history/activity, guided stdio/HTTP setup, process heartbeats, blinded annotation/export, themes and keyboard support | Client configuration is explicitly merged by the user; heartbeats do not prove routing or upstream safety; manual native usability/accessibility remains |
| Packaging | Fixed bundled Python engine, release override rejection, platform installers/bundle paths, dependency notices, package/file hashes and source provenance | Unsigned/unnotarized previews; secure update trust and broad OS installation compatibility remain |
| Native verification | Fixed-module IPC tests, actual frozen-engine decisions, installed/bundled resource checks and renderer-triggered SQLite startup | These checks do not certify manual interactions, screen readers, high-DPI behavior or all lifecycle/OS combinations |
| Linux dependencies | Exact GLib source backport and current compatible macro helper; fresh dated RustSec scan has 0 vulnerability entries / 0 warnings | Registry scanning alone does not certify local patched source; retain backport tests and independent review |
| Data | 494 primary candidates from 11 groups, 227 separate reference records, 721 exact reproductions | Zero human labels; broaden to >=30 contributing primary groups, validate extraction/licensing and obtain >=500 eligible independently reviewed transitions |
| Research | Verified prior-art overlap, protocol, corrected utilities and explicitly ineligible development experiments | Independent attacks/final evaluation, complete baselines/ablations, calibration/repeated seeds/cluster intervals and final manuscript |

## Verification record

All six jobs pass on source revision `1248ebc` in
[platform run 39057785978](https://github.com/parthdongre/mcp-driftguard/actions/runs/39057785978).
The Python suites pass 256/252/255 tests on macOS/Windows/Linux respectively;
9 frontend logic tests and 23 browser checks pass, with zero automated violations
in six sampled accessibility states. Native IPC, packaged engines, installations
and actual WebView startup pass on all three CI targets.

See [CROSS_PLATFORM_TESTING.md](CROSS_PLATFORM_TESTING.md) for the exact revision,
platform jobs, counts and any open failure. The presence of a packaging or smoke
script is not itself evidence that the corresponding platform passed.

The native startup check launches the actual packaged WebView and requires its
renderer to initialize the bundled Python/SQLite engine. Linux additionally checks
a visible Xvfb window using software compositing; Windows checks a real native
window handle. This is stronger than a compile-only check and still distinct from
manual native interaction.

## Release gates

1. Review the verified unsigned preview on the intended macOS/Windows/Linux systems,
   including ordinary/failure workflows, accessibility, display scaling and lifecycle.
2. Complete independent authorization/IPC/transport/credential/recovery review.
3. Configure owner-controlled signing/notarization and secure update trust, freeze
   artifacts/provenance and verify the signed installation/update paths.
4. Complete independent human annotation and the frozen research protocol before
   finalizing paper results or releasing restricted raw data.
5. Approve the concrete production release or main merge separately.

Every changed exact definition still requires reapproval. Reduced re-consent at
comparable malicious recall remains an unproven research hypothesis. A recent
process heartbeat, a zero-count advisory scan and passing engineering tests do not
establish detector superiority or whole-product security.

[Annotation handoff](research/ANNOTATION_HANDOFF.md) ·
[Dependency findings](audit/DEPENDENCY_FINDINGS.md) ·
[Security model](SECURITY_MODEL.md)
