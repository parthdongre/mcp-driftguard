# DriftGuard Research Engineering Plan

This document tracks implementation in the order needed to support a defensible paper rather than a feature-heavy product demo.

## Principle

Every major component must correspond to a measurable research question, baseline, ablation, or reproducibility requirement. Experimental code should remain separate from security claims until evaluated.

## Phase 1 - Deterministic research core

Status: **implemented**

- canonical snapshots and hashes
- typed structural deltas
- field-aware schema views
- interpretable capability profile and capability delta
- stable deterministic pair features
- approved-baseline lineage tracking
- CUSUM-style sequential baseline
- pair and trajectory dataset schemas
- repository-level leakage-group metadata
- unit tests

The capability extractor and temporal scalar risk function are transparent baselines. They provide auditable features and test fixtures; they are not presented as learned ground truth.

## Phase 2 - Semantic feature pipeline

Status: **foundation implemented; real-model benchmarking pending**

Implemented:

- embedding-provider protocol
- lazy local SentenceTransformer adapter
- five separate semantic views
- embedding cache
- field-wise cosine drift
- fusion into the model-ready pair feature vector

Pending:

- benchmark a real local encoder over representative MCP schemas
- record encoding/inference latency
- compare full-schema-only vs field-aware semantic features
- evaluate at least one stronger encoder if the baseline is insufficient

Primary ablation: full-schema-only embedding vs field-aware embeddings.

## Phase 3 - Temporal dataset construction

Status: **in progress**

Implemented:

- formal C0/C1/C2/C3 labeling guide and evidence tags
- two-annotator/adjudication protocol design
- controlled benign and malicious schema-valid mutation primitives
- deterministic low-and-slow capability-creep trajectory fixture
- JSON-manifest history parser
- Git-backed version miner that reads historical manifests without executing repository code
- adjacent version-pair extraction

Next:

- identify and clone a curated set of real MCP server repositories
- add source-code extractors for Python/TypeScript tool registrations where JSON manifests are absent
- preserve repository, server, tool, commit, and timestamp lineage
- manually label a reviewed subset
- construct broader malicious trajectories from documented attack families
- keep repository-disjoint train/validation/test groups
- hold out attack families for robustness evaluation

No private or unpublished attack corpus should be committed to a public repository.

## Phase 4 - Baseline experiment harness

Status: **first harness implemented**

Implemented:

1. hash-only change alert
2. edit-distance / lexical threshold
3. transparent rule-risk baseline
4. shared binary metrics for C2+C3 and C3-only views
5. repository-disjoint split integration
6. first C0-C3 logistic-regression baseline
7. reproducible JSON experiment output

Pending:

- full-schema cosine threshold
- field-aware cosine threshold
- single-snapshot classifier
- XGBoost pair classifier
- calibrated probabilities
- attack-family-held-out evaluation

All baselines must consume the same split manifest where possible.

## Phase 5 - Consent-aware pair classifier

Status: **logistic baseline implemented; main model pending**

Target output:

- `C0`: no meaningful change
- `C1`: benign maintenance
- `C2`: legitimate capability expansion requiring re-consent
- `C3`: malicious / suspicious drift

Research requirements:

- class-wise precision/recall/F1
- macro-F1
- C3 AUROC/AUPRC
- C2 recall and precision
- confusion matrix, especially C2 vs C3
- calibrated probabilities and Brier score / ECE
- false re-consent prompts per 100 benign updates
- inference latency

## Phase 6 - Low-and-slow sequential models

Status: **CUSUM-style baseline implemented; comparative study pending**

Compare at least:

- approved-baseline distance only
- simple drift budget
- one-sided/multivariate CUSUM
- Bayesian online change-point detection if implementation quality permits

Create trajectories where every adjacent update is intentionally below a local pairwise alert threshold but the final tool has clearly expanded or malicious capability.

Primary metrics:

- trajectory detection rate
- average detection delay
- false alarms on benign trajectories
- minimum cumulative drift detected

## Phase 7 - Explainability and policy

- changed-field evidence
- capability additions/removals
- field-level drift scores
- SHAP for tree models
- counterfactual field removal/reversion experiments
- map calibrated probabilities to allow / log / re-consent / quarantine

Policy thresholds must be learned/tuned on validation data, not chosen after seeing the test set.

## Phase 8 - MCP integration

- intercept `tools/list`
- support `notifications/tools/list_changed`
- snapshot updated definitions before exposure to the model
- run detection before risky invocation
- persist lineage and approval state
- optional OPA policy adapter

## Phase 9 - Paper artifact

Before submission:

- freeze dataset and split manifests
- freeze all thresholds and model checkpoints
- run literature search again
- rerun experiments from a clean environment
- archive metrics and seeds
- produce ablation tables
- document limitations and failed hypotheses
- anonymize artifact if required by the venue

## Non-goals for the first paper

- broad malware detection inside MCP server binaries
- OAuth implementation auditing
- arbitrary malicious tool-output detection without definition change
- claiming that keyword-derived capability profiles prove actual runtime behavior
- claiming first-of-kind status without a final literature review
