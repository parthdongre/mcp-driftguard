DriftGuard

Submission validation, research positioning and next steps

Parth Dongre | VIT Pune | SY IT-D | Roll 5428 October 2026 | Linux / Python 3.12 | Recovered development checkout

1. What is actually verified

This report separates engineering validation from detection accuracy. The measurements use a persisted SQLite trust store and an authored local MCP subprocess. No new external server, user account, browser workflow or native installer is certified by these runs.

Check | Measured result | Outcome

Full Python regression | 269 passed, 1 skipped (JUnit XML verified) | One native credential-store gate remains unavailable

Store dispatch P95 (1,000 samples) | 9.083 ms | PASS

Local STDIO gateway P95 (200 samples) | 84.538 ms | PASS

Eight database connections | 400 successful calls; 100 post-revoke blocks | PASS

Forced crashes | Transaction rollback + new gateway session requires review | PASS

Bounded sustained run | 300.0 s; 13360 calls; 1336 invalid inputs blocked | PASSED

Frontend | 9 logic tests and production build | PASS; no browser/native claim

Statement coverage is 84.53% overall (gateway store 92.72%, HTTP transport 87.04%, STDIO transport 81.25%, input contracts 100%). The earlier >90% per-component advancement gate is not satisfied across the recovered tree; passing behavioral tests is not full release approval.

Scope limit: a five-minute workload is useful submission evidence, but it cannot establish multi-hour reliability, crash safety at every possible instruction boundary, zero-day resistance, or behavior of unchanged remote handlers.

2. Reproducible systems evidence

Performance targets were recorded before measurement: store-dispatch P95 <=50 ms, local STDIO sequential P95 <=100 ms, zero concurrency errors and zero post-revocation execution; five-minute soak with <=64 MiB RSS growth. Network and LLM inference latency are excluded.

Measurement | Before optimization | Latest measurement

STDIO sequential P95 | 103.473 ms | 84.538 ms

STDIO concurrency throughput | 9.91 calls/s | 18.25 calls/s

STDIO queued P95, eight callers | 3636.61 ms | 2403.74 ms

Sustained RSS growth | Not applicable | 1.43 MiB

Sustained database size | Not applicable | 3.13 MiB

Reconnect/close cycles | Not applicable | 10

The first STDIO profile failed its latency target. A bounded successful-metaschema cache alone did not solve it. Duplicate explicit identity hashing was then removed from gateway wrapper paths, while each actual peer request still verifies identity immediately before wire dispatch. The original failed profiles are retained.

Concurrency test: eight independent SQLite connections perform 400 operations. A barrier-controlled call races a revocation on another connection; after revocation commits, 100 additional calls must be rejected. STDIO traffic separately sends 400 calls from eight threads; requests remain serialized by the peer. Tail queue latency is reported, not hidden.

Crash test: kill a subprocess while an audit transaction is uncommitted; reopen the database and check rollback, committed-event persistence and SQLite integrity. Kill a gateway owner after approval; launch a fresh owner and ensure prior consent cannot execute. This is not an exactly-once guarantee for remote side effects.

Reproduce from repository root:.venv/bin/python -m pytest -q -rs.venv/bin/python -m experiments.validate_submission_systems --seconds 300.venv/bin/python -m experiments.profile_gateway_submission

3. Comparable research and products

These are research comparators, benchmarks and a competing product, not equivalent systems tested on a shared dataset. Paper metrics cannot be ranked against DriftGuard engineering scores. Abstracts and primary documentation were checked; no complete systematic literature review is claimed.

Work / source | What it contributes | Implication for DriftGuard

MCP-Guard (2025; revised 2026) [1] | Layered static/neural detection and LLM arbitration; MCP-AttackBench. | Direct detector baseline; compare on the same held-out data and cost budget.

ETDI (2025) [2] | Identity, immutable versioned tool definitions and policy-based permissions. | Exact version-bound consent is prior art, not sufficient novelty.

MCPShield (2026) [3] | Pre-invocation probing, runtime boundaries and history-informed trust. | Temporal trust alone is not a unique contribution; narrow the claim.

MCPTox (2025; AAAI 2026) [4] | Tool-poisoning benchmark based on real MCP tools. | Use as external evaluation material after license and label checks; not a competing defense.

MCPSecBench (2025; revised 2026) [5] | Multi-surface protocol, host and server attack evaluation. | Use its taxonomy to expose gaps beyond descriptor monitoring.

MCP-ITP (2026) [6] | Adaptive implicit poisoning that can influence a different privileged tool. | Test cross-tool steering; scanning invoked tools alone is insufficient.

SchemaGuard (2026) [7] | Structure-aware manifest/skill admission screening with localization. | Typed schema representations already have prior art; avoid a first-of-kind claim.

MCP-Scan / Invariant [8] | Product with tool pinning, runtime proxying and custom guardrails. | Hashing, rug-pull alerts and proxy monitoring are existing product capabilities.

4. Defensible contribution and useful ideas

Recommended positioning: a local-first consent and review workspace for evolving MCP tool definitions, with structured capability differences, temporal review evidence, exact authorization bindings, and reproducible failure/recovery tests. Treat improved review utility as a hypothesis to evaluate.

Critical distinction: exact-hash blocking already catches every observed descriptor change, including benign changes. A temporal score does not automatically improve prevention over that baseline. Its measurable value could be better prioritization and explanations, reduced reviewer mistakes, and lower review burden. Unchanged-handler attacks remain outside descriptor-only detection.

Candidate direction | User value / experiment | Status

Capability-delta review receipts | Show which parameter, permission or destination changed and why review is required. Measure reviewer accuracy and completion time against raw diffs. | Candidate extension; not proven unique

Review-budget-aware temporal triage | Rank evolving tools under a fixed human review budget. Compare hash-only, snapshot-only and temporal rankings at matched false-positive/review budgets. | Research hypothesis; do not autoapprove

Replayable consent evidence packs | Export redacted definition hashes, policy/session bindings, reasons and a deterministic replay case. Measure reproducibility and recovery-debugging time. | Useful engineering contribution; no authenticity guarantee without signing

Cross-tool capability-path warnings | Explain combinations such as read-sensitive-file then network-send. Use controlled workflows; measure bypasses and false positives. | Future research; related prior art exists

Uncertain-outcome recovery receipts | When a server crashes mid-call, mark the result indeterminate and require reconciliation instead of blindly retrying a mutation. | High product value; exactly-once is not claimed

Needs further improvement? Yes. Before real deployment: complete UI-to-live-gateway behavior, supported schema contracts, native installation/credential checks, bounded queues and deadlines, multi-hour load, and representative integrations. Before publication: independent annotations, chronological repository-disjoint splits, matched baselines, ablations, confidence intervals and a review-utility study.

5. Submission plan and references

For tomorrow: present the implemented consent gate, structured differences, temporal evidence and the bounded systems results. Demonstrate pending -> approved -> changed/revoked -> blocked on a controlled example. Clearly label guided UI fixtures. Use the evidence files for measured claims.

Do not claim: 25 fresh successful external integrations, native platform certification, independent detection accuracy, outperforming the listed systems, first-ever rug-pull protection, multi-hour stability or guaranteed error-free operation. The repository is a recovered development revision; old 390-test results do not describe this checkout.

Remaining work in order: (1) finish real UI-to-gateway integration and native checks; (2) address output-schema compatibility and queue tails; (3) complete diverse integrations and longer soak; (4) evaluate detector and reviewer utility independently. Freeze submission scope rather than adding untested algorithms tonight.

[1] MCP-Guard. https://arxiv.org/abs/2508.10991

[2] ETDI. https://arxiv.org/abs/2506.01333

[3] MCPShield. https://arxiv.org/abs/2602.14281

[4] MCPTox. https://arxiv.org/abs/2508.14925

[5] MCPSecBench. https://arxiv.org/abs/2508.13220

[6] MCP-ITP. https://arxiv.org/abs/2601.07395

[7] SchemaGuard. https://doi.org/10.32604/cmc.2026.089268

[8] Invariant MCP-Scan documentation. https://github.com/invariantlabs-ai/docs/blob/main/docs/mcp-scan/index.md

Evidence: artifacts/submission-systems/*.json and artifacts/debug-recovery/submission-regression-final.xml. Sources checked 28 October 2026. Candidate ideas are interpretations of the comparison, not established novelty or implemented capabilities.
