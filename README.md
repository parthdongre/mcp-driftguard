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

See [`docs/RESEARCH_POSITIONING.md`](docs/RESEARCH_POSITIONING.md), [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md), and [`docs/LABELING_GUIDE.md`](docs/LABELING_GUIDE.md).

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

Current prototype version: **0.4.0**

Implemented:

- deterministic canonical tool snapshots and SHA-256 identity
- typed structural old/new deltas
- five field-aware views: purpose, input contract, output contract, capability/safety metadata, and full schema
- interpretable effective-capability profiles across operation/resource/effect/scope/destination/sensitivity dimensions
- capability-delta extraction and a transparent capability-escalation feature
- stable model-ready pair features
- embedding-provider protocol, cache, cosine-distance utilities, and lazy SentenceTransformer adapter
- optional field-aware semantic drift features
- first learned C0-C3 logistic-regression pair classifier
- repository-disjoint train/validation/test splitting
- formal C0/C1/C2/C3 labeling framework and evidence tags
- controlled benign/malicious mutation primitives
- deterministic low-and-slow capability-creep trajectory generator
- Git-backed JSON tool-manifest history miner that does not execute repository code
- adjacent historical version-pair extraction
- dependency-free hash, lexical, and rule-risk baseline evaluation harness
- C2+C3 consent-significant and C3-only metrics
- reproducible experiment JSON output
- approved-baseline lineage monitor and deterministic CUSUM-style temporal baseline
- tests for structural, capability, embedding, labeling, history, leakage, evaluation, and temporal behavior

The current capability extractor, mutation fixtures, and temporal risk scalar are intentionally transparent research baselines. They are **not** presented as learned ground truth or proof of runtime behavior.

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

The paper will compare DriftGuard against progressively stronger baselines:

1. hash-only change detection
2. textual diff / edit-distance threshold
3. regex / risk dictionary
4. full-schema cosine threshold
5. field-aware cosine threshold
6. single-snapshot semantic classifier
7. LLM-as-judge on the current schema
8. LLM-as-judge on the old/new pair
9. pairwise logistic regression
10. pairwise XGBoost / stronger learned model
11. proposed capability-aware pair classifier + sequential drift detector

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

1. curate real MCP repositories and run the history miner
2. add Python and TypeScript source extractors for tool registrations that do not use JSON manifests
3. benchmark a real local sentence-transformer on the five schema views
4. build the first manually reviewed real-benign dataset subset
5. add full-schema and field-aware cosine baselines to the experiment runner
6. train/evaluate logistic regression and XGBoost on the same frozen repository-disjoint split
7. expand low-and-slow trajectories and compare drift budget, CUSUM, and Bayesian change-point detection
8. add calibrated re-consent thresholds and false re-consent metrics

## Research status

**Deterministic core, first learned pair baseline, labeling protocol, controlled mutation generator, history-ingestion foundation, and baseline experiment harness are implemented. Real-corpus construction is the next major phase.**

## License and confidentiality

Copyright (c) 2026 Parth Dongre. All rights reserved.

This repository is **proprietary research software** and is **not an open-source project**. Access, redistribution, derivative works, public disclosure, and commercial use are restricted by the repository's proprietary research license. See [`LICENSE`](LICENSE).

Earlier copies that were lawfully obtained while an earlier revision was distributed under different terms remain governed by the terms that applied to those copies.
