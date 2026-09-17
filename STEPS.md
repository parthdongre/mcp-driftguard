# MCP DriftGuard — Development Decisions Overview

This file records the major engineering and research decisions in the project at a level suitable for contributors and project reviews. It is intentionally an overview, not line-by-line documentation.

## 1. Security object: tool evolution, not only the current tool

### Decision
Treat the sequence of MCP tool definitions across versions as the primary security object:

`T0 -> T1 -> ... -> Tn`

### Why
A malicious server does not need to ship an obviously dangerous tool on day one. It can begin with a harmless tool, receive approval, and gradually change descriptions, schemas, or capability signals later. A single-snapshot detector misses the trust history.

### Where
- `src/driftguard/canonicalize.py`
- `src/driftguard/history.py`
- `src/driftguard/temporal.py`
- `src/driftguard/stateful_policy.py`

## 2. Canonical snapshots + SHA-256 identity

### Decision
Canonicalize observed tool definitions before hashing and comparison.

### Why this instead of raw JSON hashing
Raw JSON can change because of key order or presentation-only whitespace. Those changes are not meaningful security changes. Canonicalization keeps security-relevant literal values while normalizing irrelevant representation differences.

### Where
- `canonicalize_tool()` normalizes the representation.
- `schema_hash()` creates the stable identity.
- `make_snapshot()` turns an observed tool into a logical immutable snapshot.

## 3. Typed structural deltas

### Decision
Do not rely on a plain text diff. Extract changes such as parameters added, required fields added, type/default changes, URLs, imperative language, sensitive terms, and cross-tool references.

### Why
Two strings can be textually similar while having very different security meaning. Adding a required destination URL or turning an optional field into a mandatory field is more important than ordinary wording changes.

### Where
- `src/driftguard/diff.py`
- `src/driftguard/structural_security.py`

## 4. Field-aware semantic views

### Decision
Represent a tool through separate semantic views rather than one large text blob.

Current views include purpose, input contract, output contract, capability/safety metadata, and full schema.

### Why
A small change in the input contract can be security-critical even when the overall tool description remains almost identical. One full-schema embedding can hide this local change.

### Where
- `src/driftguard/views.py`
- `src/driftguard/embeddings.py`
- `src/driftguard/features.py`

## 5. Effective-capability projection

### Decision
Infer an interpretable capability profile from the tool definition and compare old vs new capability signals.

### Why
The project is not only asking "Did the text change?" It is asking "Did the tool become able to do something materially more powerful?"

Capabilities are represented across dimensions such as operation, resource, side effect, scope, destination, and sensitivity.

### Where
- `src/driftguard/capabilities.py`
- consumed by `src/driftguard/features.py`

## 6. Four operational classes: C0–C3

### Decision
Use four classes instead of only benign/malicious.

- `C0`: no meaningful change
- `C1`: benign maintenance
- `C2`: legitimate capability expansion
- `C3`: suspicious/malicious drift

### Why
A security system should not classify every capability increase as an attack. Some updates are legitimate but still require renewed user consent. Separating C2 from C3 makes the system useful as a consent gate, not merely an anomaly detector.

### Where
- `src/driftguard/models.py`
- `src/driftguard/labeling.py`
- `docs/LABELING_GUIDE.md`

## 7. Approved baseline + local step comparison

### Decision
For every new version, compare both:

1. previous version -> current version
2. approved baseline -> current version

### Why
An attacker can make each individual update small. Adjacent-only comparison may see four harmless-looking changes, while approved-to-current comparison reveals that the tool has moved far from what the user originally trusted.

### Where
- `src/driftguard/temporal.py`
- `src/driftguard/stateful_policy.py`

## 8. Sequential CUSUM-style drift monitor

### Decision
Accumulate repeated small suspicious changes over time using a deterministic CUSUM-style baseline.

### Why
This specifically targets low-and-slow rug pulls. Even when each update remains below a one-step alert threshold, repeated drift consumes a trust budget until the system escalates.

### Why deterministic first
The first temporal detector is intentionally transparent so that experiments can isolate whether temporal accumulation itself adds value before replacing it with a learned temporal model.

### Where
- `research_risk_signal()`
- `SequentialDriftMonitor`
- `TemporalConfig`
- all in `src/driftguard/temporal.py`

## 9. Consent-aware policy layer

### Decision
Security output is converted into an operational action such as allow, allow+log, require re-consent, or quarantine.

### Why
A detector alone is not a deployable security control. The practical question is what happens before the MCP tool is allowed to run again.

### Where
- `src/driftguard/consent_policy.py`
- `src/driftguard/stateful_policy.py`

## 10. Repository-disjoint and attack-family-held-out evaluation

### Decision
Avoid random pair-level train/test splitting when samples from the same repository or attack family could leak into both sides.

### Why
Otherwise the model can appear highly accurate by memorizing project-specific style or mutation templates instead of learning transferable security behavior.

### Where
- `src/driftguard/splits.py`
- `src/driftguard/attack_family_benchmark.py`
- `src/driftguard/learned_family_benchmark.py`
- experiment runners under `experiments/`

## 11. Baselines before novelty claims

### Decision
Compare against progressively stronger alternatives: hashing, lexical change, rules, semantic cosine, pairwise logistic regression, XGBoost, and temporal baselines.

### Why
The project is intended to be researchable. A new method is not useful simply because it works; it must show why the additional components outperform simpler alternatives under the same split.

### Where
- `src/driftguard/baselines.py`
- `src/driftguard/research_baselines.py`
- `src/driftguard/learning.py`
- `src/driftguard/tree_learning.py`
- multiple experiment runners under `experiments/`

## 12. Static source extraction instead of executing repositories

### Decision
Mine MCP tool definitions from source/history without executing third-party repository code.

### Why
The project itself studies potentially malicious MCP tooling. Executing an untrusted project merely to build a dataset would create an avoidable security risk.

### Where
- `src/driftguard/history.py`
- `src/driftguard/source_extractors.py`
- `src/driftguard/corpus_discovery.py`

## 13. Why Python + Pydantic

### Python
Chosen because the research loop requires rapid experimentation, ML tooling, Git/history processing, statistics, and reproducible scripts. Python has the strongest ecosystem for this combination.

### Pydantic
Used for typed research/data models and validation. It gives explicit schemas and catches malformed experiment data earlier than ad-hoc dictionaries.

### Why not a heavy web framework in the core
The primary artifact is currently a research/security engine. UI/API concerns are kept optional so experiments do not depend on a server stack.

## 14. Why scikit-learn first, with XGBoost as a stronger baseline

### Logistic regression
A strong interpretable baseline. It shows whether the engineered representation is useful before credit is given to model complexity.

### XGBoost
Added as a stronger non-linear baseline to test whether interactions among semantic, structural, and capability features materially improve classification.

### Why not start with a large neural model
Doing so would make it harder to determine whether gains come from the security representation or simply from model capacity, while also increasing compute and reproducibility cost.

## 15. Research evidence discipline

### Decision
Separate:

- implemented engineering,
- controlled development evidence,
- publication-grade evidence.

### Why
Synthetic or development benchmarks can guide engineering, but they must not be presented as real-world accuracy.

### Where
- `docs/PAPER_READINESS.md`
- `docs/PAPER_PROTOCOL.md`
- `src/driftguard/paper_readiness.py`

## 16. Current reviewer-facing integration work

The next layer is an end-to-end deterministic demonstration that starts from one approved MCP tool and shows a sequence of individually small post-approval changes until the temporal policy quarantines the tool. The goal is not a second detector; it is a clear integration path that lets a reviewer observe canonicalization, temporal accumulation, approved-baseline reasoning, and policy output in one run.

## 17. What not to claim yet

Do not say:

- DriftGuard already achieves a proven real-world detection accuracy.
- The research novelty is permanently established.
- Synthetic attack-family performance directly represents production MCP servers.
- The current capability extractor is ground truth.

The defensible statement is that the repository implements a research prototype and evaluation framework for capability-aware temporal MCP tool-definition drift, while broad real-corpus validation and external attack transfer remain ongoing work.
