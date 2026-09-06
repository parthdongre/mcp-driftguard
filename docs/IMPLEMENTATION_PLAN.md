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

Status: **foundation and baseline runners implemented; real-model benchmarking pending**

Implemented:

- embedding-provider protocol
- lazy local SentenceTransformer adapter
- five separate semantic views
- embedding cache
- field-wise cosine drift
- full-schema cosine and field-aware cosine baseline evaluation
- fusion into the model-ready pair feature vector
- validation-only threshold selection utility

Pending:

- benchmark a real local encoder over representative MCP schemas
- record encoding/inference latency
- execute full-schema-only vs field-aware ablation on the frozen corpus split
- evaluate at least one stronger encoder if the baseline is insufficient

Primary ablation: full-schema-only embedding vs field-aware embeddings.

## Phase 3 - Temporal dataset construction

Status: **active corpus-construction phase**

Implemented:

- formal C0/C1/C2/C3 labeling guide and evidence tags
- two-annotator/adjudication protocol
- dependency-free raw agreement and Cohen's kappa utilities
- explicit C2-vs-C3 disagreement reporting
- adjudication-to-reviewed-dataset conversion
- controlled benign and malicious schema-valid mutation primitives
- deterministic low-and-slow capability-creep trajectory fixture
- JSON-manifest history parser
- Git-backed history mining without executing repository code
- static Python `@mcp.tool(...)` extraction
- static TypeScript/JavaScript `registerTool(...)` extraction for common literal/Zod patterns
- static repository source discovery with extractable/unsupported/parse-error coverage reporting
- commit SHA and commit timestamp lineage preservation
- adjacent version-pair extraction
- curated public source manifest spanning Python, TypeScript, vendor and independent projects
- reproducible public-corpus builder that emits an unlabeled annotation queue and coverage summary
- corpus-construction methodology in `docs/CORPUS_CONSTRUCTION.md`

Next:

- run the public-corpus builder in a network-enabled research environment
- quantify extraction coverage per repository and registration architecture
- add static adapters only where they materially increase coverage without executing target code
- manually label the first independently reviewed real-history subset
- report raw agreement, Cohen's kappa, and C2/C3 adjudication counts
- construct broader malicious trajectories from documented attack families
- freeze repository-disjoint train/validation/test groups after the reviewed subset is large enough
- hold out attack families for robustness evaluation

No private or unpublished attack corpus should be committed to a public repository.

## Phase 4 - Baseline experiment harness

Status: **core harness implemented; corpus execution pending**

Implemented:

1. hash-only change alert
2. edit-distance / lexical threshold
3. transparent rule-risk baseline
4. full-schema cosine threshold
5. field-aware cosine threshold
6. shared binary metrics for C2+C3 and C3-only views
7. repository-disjoint frozen split manifests
8. attack-family holdout manifests
9. validation-only scalar threshold tuning
10. first C0-C3 logistic-regression baseline
11. reproducible JSON experiment output

Pending:

- single-snapshot semantic classifier
- XGBoost pair classifier
- calibrated probabilities
- C3 AUROC/AUPRC and calibration metrics
- false re-consent prompts per 100 benign updates
- attack-family-held-out execution on the frozen benchmark

All baselines must consume the same frozen split manifest where possible. Test data must not be used to choose thresholds.

## Phase 5 - Consent-aware pair classifier

Status: **logistic baseline implemented; main model pending real reviewed corpus**

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

Status: **CUSUM-style baseline and trajectory metrics implemented; comparative study pending**

Implemented trajectory metrics include:

- trajectory detection rate
- average detection delay
- benign-trajectory false alarms
- pre-onset false alarms

Compare at least:

- approved-baseline distance only
- simple drift budget
- one-sided/multivariate CUSUM
- Bayesian online change-point detection if implementation quality permits

Create trajectories where every adjacent update is intentionally below a local pairwise alert threshold but the final tool has clearly expanded or malicious capability.

Additional metric to derive during the comparative study:

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

- freeze source repository manifest and acquisition commit heads
- freeze annotation candidate set and adjudicated labels
- freeze dataset and split manifests
- freeze all thresholds and model checkpoints
- report extractor coverage and exclusions
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
- treating suspicious schema text as proof of a verified malicious incident
- dynamically importing target repositories merely to improve corpus extraction coverage
- claiming first-of-kind status without a final literature review
