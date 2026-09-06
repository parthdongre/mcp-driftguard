# MCP DriftGuard

**Proprietary research project. Not open source.**

Capability-aware temporal semantic drift detection for MCP tool poisoning, capability escalation, and low-and-slow rug pulls.

## Research thesis

Model Context Protocol (MCP) clients discover tools through tool definitions containing natural-language descriptions and structured schemas. Those definitions become part of the model's reasoning context and can evolve after a user or host has already approved the tool.

Traditional integrity checks can tell that a definition changed, but they do not tell whether the update is:

- semantically equivalent,
- benign maintenance,
- a legitimate capability expansion that should require re-consent, or
- malicious tool poisoning / rug-pull behavior.

MCP DriftGuard treats **the evolution of an approved tool definition across versions as the primary security object**.

The current paper direction is:

> **DriftGuard: Capability-Aware Temporal Detection of Low-and-Slow Rug Pulls in Model Context Protocol Tool Definitions**

See [`docs/RESEARCH_POSITIONING.md`](docs/RESEARCH_POSITIONING.md) for the literature-backed novelty analysis and [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) for the research engineering roadmap.

## Core task

Given a trusted schema `T_old` and a newly observed schema `T_new`, DriftGuard computes field-aware semantic, structural, and effective-capability deltas and predicts one of four operational classes:

| Class | Meaning | Default action |
|---|---|---|
| `C0` | No meaningful change | Allow |
| `C1` | Benign maintenance | Allow + log |
| `C2` | Legitimate capability expansion | Require re-consent |
| `C3` | Malicious / suspicious semantic drift | Quarantine / block |

A sequential detector then reasons over `T0 -> T1 -> ... -> Tn` so an attacker cannot evade review simply by spreading a dangerous change across many individually small updates.

## Research contributions under evaluation

1. **Capability-aware version-pair representation** combining field-level semantic drift with typed schema deltas and inferred effective-capability changes.
2. **Consent-aware change classification** that explicitly separates benign maintenance from legitimate but security-significant capability expansion.
3. **Sequential drift budget / change-point detection** for low-and-slow multi-version rug pulls.
4. **Temporal MCP Tool-Evolution Benchmark** built from real benign version histories plus schema-valid malicious evolution trajectories with repository-disjoint and attack-family-held-out evaluation.

These remain hypotheses until validated experimentally and re-checked against the literature before publication.

## Implemented research core

The first research-engineering milestone is implemented and Phase 2 has started:

- deterministic canonical tool snapshots and SHA-256 identity
- typed structural old/new deltas
- five field-aware views: purpose, input contract, output contract, capability/safety metadata, and full schema
- interpretable effective-capability profiles across operation/resource/effect/scope/destination/sensitivity dimensions
- capability-delta extraction and a transparent capability-escalation feature
- stable pairwise numeric feature extraction for later sklearn/XGBoost models
- embedding-provider protocol, embedding cache, cosine-distance utilities, and a lazy SentenceTransformer adapter
- optional field-aware semantic drift features fused into the pair feature vector
- a stateful approved-baseline lineage monitor
- a deterministic CUSUM-style low-and-slow baseline plus approved-to-current cumulative risk
- dataset schemas for pairwise and trajectory experiments with repository-level leakage grouping
- unit tests covering structural, capability, embedding, temporal, and dataset behavior
- a runnable low-and-slow trajectory demo under `examples/`

The current capability extractor and temporal risk function are intentionally transparent baselines. They are **not** the final learned detector.

## Planned pipeline

```text
MCP tools/list or tools/list_changed
              |
              v
     Raw + canonical snapshot
              |
       version lineage store
              |
              v
   Field-aware delta extraction
      /                  \
semantic views      structural deltas
      \                  /
       capability-delta encoder
              |
              v
     Pairwise change classifier
      C0 / C1 / C2 / C3
              |
      calibrated probabilities
              |
      +--------------------+
      | sequential history |
      v                    |
 drift budget / CUSUM / change point
              |
              v
      policy + re-consent gate
```

## Baselines

The paper will compare DriftGuard against progressively stronger baselines rather than only showing raw model accuracy:

1. hash-only change detection
2. textual diff / edit-distance rules
3. regex / risk dictionary
4. full-schema cosine threshold
5. field-aware cosine threshold
6. single-snapshot semantic classifier
7. LLM-as-judge on the current schema
8. LLM-as-judge on the old/new pair
9. proposed capability-aware pair classifier
10. proposed pair classifier + sequential drift detector

## Features under study

### Semantic views

- tool purpose / description drift
- parameter-description drift
- input contract drift
- output contract drift
- capability / annotation drift
- full canonical schema drift

### Structural and capability deltas

- parameters added, removed, or renamed
- required-set changes
- type changes
- enum expansion / restriction
- default-value changes
- output-schema changes
- safety annotation changes
- newly introduced URLs / domains
- sensitive-resource and action changes
- cross-tool references / tool-selection manipulation
- imperative / override language
- inferred effective capability changes such as read/write/delete/send/execute across local or external scopes

## Main research questions

1. Does approved-vs-current classification reduce benign-update false positives compared with exact-change, cosine-only, single-snapshot, and LLM-judge baselines?
2. Does a capability-aware representation improve detection beyond embeddings-only and structure-only features?
3. Can legitimate capability expansion be separated reliably from malicious permission escalation?
4. Can sequential detection catch low-and-slow tool-definition rug pulls where every local update remains below a pairwise alert threshold?
5. How well does the detector generalize to unseen repositories and unseen poisoning families?
6. What latency and false re-consent rate are achievable before tool invocation?

## Repository structure

```text
mcp-driftguard/
├── src/driftguard/       # research core package
├── tests/                # unit/integration tests
├── examples/             # benign and malicious schema evolution demos
├── data/                 # private dataset manifests / generated samples
├── experiments/          # training and evaluation entry points
├── policies/             # policy / re-consent prototypes
├── docs/                 # threat model, research positioning, labeling guide
└── pyproject.toml
```

## Immediate next milestones

1. run and benchmark an actual local sentence-transformer on the five schema views
2. private data ingestion and labeling pipeline for real MCP repository histories
3. hash / lexical / cosine / regex baseline experiment harness
4. first C0-C3 logistic-regression and XGBoost pair classifiers
5. probability calibration and consent-policy thresholds
6. controlled low-and-slow trajectory generator
7. comparison of drift budget, multivariate CUSUM, and Bayesian change-point detection

## Research status

**Phase 1 complete; Phase 2 semantic feature pipeline in progress.** Dataset acquisition and learned pair-classifier work are next.

## License and confidentiality

Copyright (c) 2026 Parth Dongre. All rights reserved.

This repository is **proprietary research software** and is **not an open-source project**. Access, redistribution, derivative works, public disclosure, and commercial use are restricted by the repository's proprietary research license. See [`LICENSE`](LICENSE).

Earlier copies that were lawfully obtained while an earlier revision was distributed under different terms remain governed by the terms that applied to those copies.
