# DriftGuard submission sprint - 28 October 2026

## Time-box and scope

Target approximately 20 minutes: reproduce systems failures, run measurable Linux-local validation, preserve evidence, and prepare a research comparison. Defer new external MCP execution, native certification, model downloads, and speculative feature additions. The output is a tested prototype submission, not an error-free or publication-ready security product.

1. Establish recovered source and environment; run regression with installed ML dependencies.
2. Measure 1,000 persisted store dispatches after warmup; fixed P95 target <=50 ms.
3. Exercise eight independent SQLite connections (400 calls); verify all completions and 100 blocked calls after revocation.
4. Force-kill a transaction worker and a gateway owner; verify rollback, committed audit persistence, integrity_check, and renewed approval on restart.
5. Run a five-minute mixed workload with valid calls, invalid calls and persisted-state reads; record RSS and database size. This is a bounded soak, not a long-term reliability claim.
6. Measure actual authored STDIO subprocess traffic (200 sequential and 400 concurrent calls), 20 post-revoke attempts, dead-child handling and ten reconnect/close cycles. Fixed sequential P95 target <=100 ms.
7. Preserve failed performance attempts. Optimize only demonstrated bottlenecks; rerun affected tests and the systems workload.
8. Run frontend logic tests and production build. Do not substitute these for browser/native end-to-end verification.
9. Produce an evidence report, primary-source literature comparison, and prioritized submission/research roadmap.

## Decision gates

Required behavioral assertions must all pass. Skips or unavailable platforms remain explicit. Passing measurements on one authored fixture cannot certify 25 public MCP implementations. An independent detector benchmark is separate from systems correctness and statement coverage.

## Demonstration sequence for submission

Show a pending definition and blocked call; approve its exact hash/revision; execute once; change the definition and demonstrate invalidation; revoke or quarantine and show another blocked call. Then show the measured systems evidence and the documented limits. If using guided UI fixtures, explicitly label them; do not describe them as live protection of ChatGPT.

## After this sprint

Priority 0: finish true UI-to-gateway integration and supported native execution; keep secret-store tests blocked until the native environment is available.
Priority 1: broaden supported schema contracts safely, add bounded queue/deadline handling, and repeat systems tests on representative servers and catalogs.
Priority 2: complete 25 diverse real integrations and a multi-hour cross-platform soak.
Priority 3: independent human labels, chronological repository-disjoint evaluation, review-burden study, baselines and ablations.
