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

Status: next

- define an embedding-provider protocol
- use one local baseline encoder initially
- embed purpose, input contract, output contract, capability/safety view, and full schema separately
- cache embeddings by snapshot hash
- compute old/new cosine drift per view
- export a deterministic feature matrix with explicit feature names
- add latency measurements

Primary ablation: full-schema-only embedding vs field-aware embeddings.

## Phase 3 - Temporal dataset construction

- mine real MCP server version histories
- preserve repository, server, tool, commit, and timestamp lineage
- extract only actual tool-definition changes
- manually label a reviewed subset
- define C0/C1/C2/C3 annotation rules
- generate controlled benign transformations
- generate schema-valid malicious transformations from documented attack families
- construct multi-step low-and-slow trajectories
- keep repository-disjoint train/validation/test groups
- hold out attack families for robustness evaluation

No private or unpublished attack corpus should be committed to a public repository.

## Phase 4 - Baseline experiment harness

Implement comparable evaluators for:

1. hash-only
2. edit-distance / lexical drift
3. regex / risk dictionary
4. full-schema cosine threshold
5. field-aware cosine threshold
6. single-snapshot classifier
7. pairwise logistic regression
8. pairwise XGBoost

All baselines must consume the same split manifest where possible.

## Phase 5 - Consent-aware pair classifier

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
