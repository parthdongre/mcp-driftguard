# Implementation progress — private review prototype

Authoritative baseline: `parthdongre/mcp-driftguard`, main at
`9fcab36176279d77c4dd7f1950d47e4991697cf7` (v0.4.0). Work is on local branch
`dev/research-gateway-desktop`; main, ownership and proprietary licensing are
preserved. No remote branch, merge, installer or research release was published.
The research/source cutoff is **2026-10-15T18:06:27Z**, the initial request time.

## Milestone record

| Milestone | Implemented and verified | Remaining boundary / next priority |
|---|---|---|
| A — audit | Baseline suite, coverage, environment, file map, architecture, defects and literature overlap recorded. Targeted review verifies supplied references and additional prior art. | Search coverage is not exhaustive; repeat searches and preserve index exports before submission. |
| B — research infrastructure | Literal-safe snapshots, integrity, schema unions, annotation/agreement, UTC splits, approved-version trajectories, post-onset detection and repository bootstrap corrected. Acquired 494 primary candidates from 11 groups plus 227 reference rows; exactly reproduced all 721 records. | Zero human labels; fewer than 30 contributing primary groups. Broaden sources, independently annotate, adjudicate and freeze final splits. |
| C — isolated algorithms | EWMA, standardized multivariate CUSUM, typed provenance-bearing capability graph and controlled comparison added outside authorization. Raw scores, configurations and source hashes retained. | Tiny templated comparison cannot select a production classifier or establish superiority. Kernel/Bayesian/conformal methods remain assessed alternatives. |
| D — gateway | Opt-in tools-only stdio mediator, exact approval, policy/principal/session binding, persistent quarantine, stale revision/replay rejection, bounded catalogs, pre-call relisting, audit and text egress checks. Real subprocess tests exercise the subset. | HTTP, remote OAuth, general subscriptions/callbacks and cancellation unsupported. No OS sandbox, handler attestation, complete DLP or exactly-once guarantee. |
| E — desktop | Interactive review, parallel definitions, recorded history, activity/export, isolated guided scenario, blinded annotation/export, appearance and honest empty states. Tauri source supplies fixed allowlisted Python IPC and app-data state. | Browser workflows pass; native integration unverified. Connections require explicit CLI setup; no vault, bundled Python, live health monitor or full research-results explorer. |
| F — hardening | Python/security tests, UI logic/build, browser workflows, sampled accessibility, screenshot review, fixture profiling and dependency lookups completed. Native macOS/Windows CI prepared. | Linux native build blocked by system prerequisites; other native targets, screen readers, signing, updates, Rust advisory review and independent audit pending. Remote CI unrun. |
| G — publication | Literature comparison, narrower hypothesis, threat model, methodology comparison, protocol and venue/readiness notes maintained. | Final labeled benchmark, independent attacks, baselines/ablations/statistics and manuscript incomplete. No submission or publication claim. |

## Material corrections

Canonical normalization respects literal JSON and keeps a separate exact identity
for authorization. Mutated/stale snapshots are rejected. Missing differs from null,
booleans differ from numbers, union type arrays work, and temporal state retains
detached evidence. Annotation agreement rejects self-comparisons and reports
undefined kappa as undefined. Evaluation separates early false alarms from
post-onset detection, respects approved versions and resamples whole repository
clusters. Graph edges retain evidence provenance; inference is not runtime proof.

Consent persists separately from observations. Every changed exact definition needs
review regardless of classifier score. Quarantine cannot be cleared by denying,
revoking, removing or reintroducing that definition. Replacements cannot inherit
old live-session approval. Imports cannot authorize live gateway connections.
Unsupported output-schema contracts are withheld before execution.

## Executed evidence

Full Python: **217 passed, 1 skipped**, **84.80%** statement coverage (4339/5117).
Baseline coverage was 85.12% (3134/3682); the percentage is not an improvement
claim. The optional XGBoost path was skipped. Frontend logic: **6 passing tests**.
TypeScript/Vite production build passes. Browser verification: **20 passing
checks**; five sampled accessibility states have zero automated WCAG A/AA
violations. These results do not certify native WebViews or all-screen accessibility.

The controlled sequential fixture has two malicious, two C2 and two C1 evaluation
trajectories. All three methods detected both malicious trajectories and intervened
on both C2 trajectories. Adjacent risk and EWMA each alerted on one of two benign
trajectories and had one pre-onset false alarm; the multivariate candidate had
neither in this tiny fixture. Mean post-onset delay was zero. These are development
plumbing results with `paper_claim_eligible=false`, not general performance estimates.

Generated-catalog profiling records median/P95 time and traced Python allocations
for 10/100/1000 tools, not app RSS, gateway throughput or native desktop performance.
No efficiency multiplier is claimed. Raw evidence and commands are in
[audit/](audit/) and [CROSS_PLATFORM_TESTING.md](CROSS_PLATFORM_TESTING.md).

## Next evidence

1. Inspect actual macOS/Windows native builds and interactions; resolve failures,
   then package and verify a pinned Python sidecar.
2. Add HTTP and remote authorization as a separately reviewed boundary with
   credential-store integration and conformance tests.
3. Obtain two independent human annotations, review extraction/licensing, broaden
   sources and freeze labels/splits before classifier selection.
4. Run independent attacks, baselines, ablations, repeated seeds, calibration and
   cluster intervals before finalizing novelty and paper tables.

See [RELEASE_READINESS.md](RELEASE_READINESS.md) and the existing
[PAPER_READINESS.md](PAPER_READINESS.md) checklist.
