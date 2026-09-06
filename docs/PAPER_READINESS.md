# Paper Readiness Tracker

This file distinguishes **implemented engineering**, **development evidence**, and **publication-grade evidence**. A high development-benchmark score does not make the paper complete.

## Current status

### Research framing

- [x] Version-aware tool-definition security object
- [x] C0/C1/C2/C3 consent-aware labels
- [x] Field-aware semantic + structural + capability fusion
- [x] Approved-baseline comparison
- [x] Sequential/CUSUM-style temporal monitoring
- [x] Bounded Tool-Surface Drift threat model
- [x] Consent-security optimization objective
- [x] Explicit overlap analysis against recent MCP literature
- [ ] Re-run systematic literature search immediately before submission
- [ ] Freeze exact novelty statement only after final search

### Detector implementation

- [x] Canonical snapshots and diffs
- [x] Structural security features
- [x] Capability projection/deltas
- [x] Hybrid ML poisoning detector
- [x] High-confidence structural invariants
- [x] Unicode/concealment signals
- [x] Cross-tool/authority-override signals
- [x] C0-C3 learned baseline
- [x] Temporal sequential monitor
- [x] Consent-policy validation optimizer
- [x] Bounded-drift trajectory auditor
- [ ] Stronger calibrated multiclass model (e.g. tree/boosted and neural pair baselines)
- [ ] Final probability calibration comparison
- [ ] OOD/abstention experiment

### Real data

- [x] Static JSON history mining
- [x] Static Python MCP tool extraction
- [x] Static TypeScript/Zod MCP tool extraction
- [x] Rename-aware Git lineage tracking
- [x] Initial real public-history corpus pilot
- [ ] Expand to >= 30 repositories minimum
- [ ] Target >= 50 repositories
- [ ] Target >= 500 independently labeled real transitions
- [ ] Prefer >= 1,000 real transitions if feasible
- [ ] Ensure meaningful domain diversity
- [ ] Freeze upstream source SHAs and corpus manifest

### Annotation quality

- [x] Formal labeling guide
- [x] Independent annotation record format
- [x] Agreement/Cohen's kappa tooling
- [x] Adjudication workflow
- [ ] Two humans independently label final real-history corpus
- [ ] Report raw agreement
- [ ] Report Cohen's kappa
- [ ] Report C2/C3 disagreement rate
- [ ] Freeze adjudicated label hash before final test

### Independent attack evaluation

- [x] Neutral external version-pair interchange format
- [x] Generic external benchmark importer
- [ ] Build dataset-specific converter for MCPTox or its current released artifact
- [ ] Build dataset-specific converter for MCP-AttackBench if licensing/data access permits
- [ ] Add MCP-ITP-derived/evasion cases where available
- [ ] Reserve at least one independent source for cross-dataset transfer only
- [ ] Never rewrite frozen external test examples after seeing errors

### Low-and-slow / bounded trajectories

- [x] Initial controlled low-and-slow generator
- [x] Local drift-budget formalization
- [x] Programmatic bounded-trajectory audit
- [ ] Audit and redesign generators so final attack trajectories provably satisfy frozen budgets
- [ ] Multiple attack objectives, not one scripted sequence
- [ ] Family-level held-out trajectory generation
- [ ] Compare adjacent-only, baseline-only, CUSUM, and full DriftGuard
- [ ] Report detection delay and false alarms
- [ ] Test multiple local budget levels

### Evaluation methodology

- [x] Repository-disjoint split manifest
- [x] Attack-family holdouts
- [x] Validation-only threshold selection
- [x] Pairwise baseline runner
- [x] Semantic baseline runner
- [x] Temporal baseline runner
- [x] Bootstrap confidence interval utilities
- [x] Paired bootstrap comparison utility
- [x] Paper-claim eligibility guardrails
- [ ] Add future-version temporal holdout
- [ ] Add cross-dataset transfer runner
- [ ] Add repeated-seed aggregate runner
- [ ] Add calibration/Brier/ECE report
- [ ] Add repository-cluster bootstrap runner
- [ ] Freeze final test manifests before last feature iteration

### Required baselines

- [x] Hash/change-only
- [x] Rule-risk baseline
- [x] Lexical/edit drift
- [x] Full/field-aware semantic baselines
- [x] Logistic pair classifier
- [x] Sequential deterministic baseline
- [ ] Single-snapshot maliciousness baseline
- [ ] Text-only pair classifier report
- [ ] Structural-only pair classifier report
- [ ] Gradient-boosted pair classifier
- [ ] LLM-as-judge baseline with frozen prompt/model version
- [ ] Reapprove-on-any-change consent baseline

### Required ablations

- [ ] no field separation
- [ ] no semantic features
- [ ] no structural features
- [ ] no capability projection
- [ ] no hard structural invariants
- [ ] no approved baseline
- [ ] no sequential accumulation
- [ ] no real benign history
- [ ] no hard benign negatives
- [ ] binary vs C0/C1/C2/C3

### Systems evaluation

- [ ] Median and P95 latency
- [ ] Throughput
- [ ] Peak memory
- [ ] Embedding/cache cost
- [ ] Snapshot storage overhead
- [ ] End-to-end MCP `tools/list_changed` interception demo

### Statistics and reproducibility

- [x] Confidence-interval implementation
- [x] Explicit final-test contamination guardrail
- [ ] >= 5 learned-model seeds
- [ ] repository/server-cluster bootstrap confidence intervals
- [ ] raw prediction archive
- [ ] dependency/environment lock artifact
- [ ] model/embedding revision pins
- [ ] experiment command archive
- [ ] one frozen release/commit used for all paper tables

### Paper writing

- [x] Detailed research positioning
- [x] Research Problem V2
- [x] Formal paper experiment protocol
- [ ] Final abstract
- [ ] Introduction
- [ ] Related work table
- [ ] Threat model figure
- [ ] Method figure
- [ ] Dataset table
- [ ] Main results table
- [ ] Unseen-family table
- [ ] Low-and-slow plot
- [ ] Consent-security Pareto plot
- [ ] Ablation table
- [ ] Limitations/ethics
- [ ] Reproducibility statement
- [ ] Final citation verification

## Current numerical evidence

The repository has achieved >95% on controlled development poisoning benchmarks, including a fresh structural-family challenge. These results are **development evidence only** because feature engineering occurred during iterative challenge testing and the benchmark is predominantly controlled/synthetic.

Do not call these numbers real-world MCP poisoning accuracy or final paper results.

## Definition of paper-ready

The project becomes paper-ready when:

1. the novelty statement survives a final literature search;
2. real benign history is broad and independently labeled;
3. at least one independent external attack source is reserved for final transfer evaluation;
4. bounded low-and-slow test trajectories are frozen before final model tuning;
5. all required baselines and ablations are run on identical frozen splits;
6. primary metrics meet or honestly report against the preregistered targets;
7. confidence intervals, repeated seeds, and system costs are reported;
8. the final experiment passes `assess_paper_readiness` with no missing evidence or disqualifiers;
9. paper text makes no unsupported priority or real-world-accuracy claims.
