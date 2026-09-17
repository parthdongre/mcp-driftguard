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

For the research framing and review material, see [`docs/RESEARCH_POSITIONING.md`](docs/RESEARCH_POSITIONING.md), [`docs/PAPER_PROTOCOL.md`](docs/PAPER_PROTOCOL.md), [`docs/PAPER_READINESS.md`](docs/PAPER_READINESS.md), and [`docs/MIDSEM_REVIEW.md`](docs/MIDSEM_REVIEW.md).

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
- capability-delta extraction and transparent capability-escalation features
- stable model-ready pair features
- embedding-provider protocol, cache, cosine-distance utilities, and lazy SentenceTransformer adapter
- optional field-aware semantic drift features
- learned C0-C3 logistic-regression pair classifier
- XGBoost attack-family holdout baseline
- repository-disjoint train/validation/test splitting
- formal C0/C1/C2/C3 labeling framework and evidence tags
- controlled benign/malicious mutation primitives
- deterministic low-and-slow capability-creep trajectory generator
- approved-baseline lineage monitor and deterministic CUSUM-style temporal baseline
- consent-reset and stateful policy simulation
- Git-backed JSON tool-manifest history mining without executing repository code
- static Python MCP tool extraction
- static TypeScript/Zod MCP tool extraction
- adjacent historical version-pair extraction
- dependency-free hash, lexical, and rule-risk baseline evaluation harness
- semantic baselines, attack-family holdouts, repeated-seed and temporal benchmark infrastructure
- annotation agreement and adjudication tooling
- reviewer-facing deterministic integration demo with text and JSON output
- CI linting, full tests, and installed-CLI smoke testing

The current capability extractor, mutation fixtures, and temporal risk scalar are intentionally transparent research baselines. They are **not** presented as learned ground truth or proof of runtime behavior.

## Reviewer / midsem demo

Install the project in editable mode:

```bash
pip install -e ".[dev]"
```

Run the human-readable low-and-slow demonstration:

```bash
driftguard-review-demo
```

Export exactly the same evidence as JSON:

```bash
driftguard-review-demo --json
```

The scenario begins with an approved local repository-search tool and gradually adds metadata inspection, sharing, external sharing, and upload language. The output shows `step_risk`, `baseline_risk`, cumulative `CUSUM`, explanatory reasons, and the final policy action. CI invokes the installed console command directly so the demo path is continuously checked, not just the underlying Python function.

For the presentation explanation, architecture, limitations, and viva questions, read [`docs/MIDSEM_REVIEW.md`](docs/MIDSEM_REVIEW.md). For engineering decisions and file-level orientation, read [`STEPS.md`](STEPS.md).

## Pipeline

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

The paper compares or plans to compare DriftGuard against progressively stronger baselines:

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

The repository already contains several of these baselines; the remaining ones are tracked explicitly in `docs/PAPER_READINESS.md`.

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
├── src/driftguard/       # research core package and review demo
├── tests/                # unit/integration tests
├── examples/             # benign and malicious schema-evolution demos
├── data/                 # corpus manifests / generated samples
├── experiments/          # training and evaluation entry points
├── docs/                 # threat model, research protocol, review material
├── STEPS.md              # engineering decision and codebase overview
└── pyproject.toml
```

## Immediate next milestones

1. expand the real MCP history corpus to at least 30 repositories, then target 50+
2. independently label a substantial real-history transition set and report agreement / Cohen's kappa
3. reserve at least one independent external poisoning source for frozen transfer evaluation
4. add future-version temporal holdout and cross-dataset transfer experiments
5. complete the required ablation matrix on identical frozen splits
6. add calibration, Brier/ECE, OOD/abstention, and repeated-seed aggregate reports
7. compare adjacent-only, approved-baseline-only, CUSUM, and stronger temporal strategies on frozen bounded trajectories
8. measure median/P95 latency, throughput, memory, embedding/cache cost, and snapshot storage overhead
9. build an end-to-end MCP `tools/list_changed` interception integration around the existing detector
10. re-run the literature search immediately before freezing any publication novelty claim

## Research status

**The deterministic detector core, learned pair baselines, labeling protocol, controlled attack generator, static history/source ingestion, temporal monitor, benchmark infrastructure, and reproducible reviewer demo are implemented. The highest-value remaining work is broader real-corpus evidence, independent evaluation, systems measurements, and live MCP interception.**

Controlled development benchmarks have shown promising results, including >95% in some synthetic/development settings. These results are **development evidence only** and must not be described as real-world MCP attack-detection accuracy.

## License and confidentiality

Copyright (c) 2026 Parth Dongre. All rights reserved.

This repository is **proprietary research software** and is **not an open-source project**. Access, redistribution, derivative works, public disclosure, and commercial use are restricted by the repository's proprietary research license. See [`LICENSE`](LICENSE).

Earlier copies that were lawfully obtained while an earlier revision was distributed under different terms remain governed by the terms that applied to those copies.
