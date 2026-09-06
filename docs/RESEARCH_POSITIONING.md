# MCP DriftGuard: Research Positioning

**Literature status date:** 2026-09-06

This document defines the research contribution we intend to defend in a paper. It is deliberately narrower than a general MCP security scanner.

## Working paper title

**DriftGuard: Capability-Aware Temporal Detection of Low-and-Slow Rug Pulls in Model Context Protocol Tool Definitions**

Alternative title:

**Consent-Aware Temporal Classification of MCP Tool-Definition Evolution**

## One-sentence thesis

MCP security should treat a tool definition as a versioned security object: by comparing approved and current schemas, extracting capability-aware semantic deltas, and accumulating risk across a sequence of small updates, a client can distinguish harmless maintenance from legitimate capability expansion and malicious low-and-slow rug pulls before tool execution.

## Why the original idea needs stronger positioning

The initial FF180 proposal correctly identified a gap between hash-based change detection and semantic assessment of tool-definition changes. However, the MCP security literature has moved quickly. Several claims that would have been plausible in early 2026 are no longer defensible.

### Claims we must NOT make

- We are **not** the first learned semantic detector for MCP security. MCP-Guard uses a fine-tuned E5 detector and LLM arbitration.
- We are **not** the first work to study rug pulls or post-approval mutation. Multiple works and the Cursor MCPoison disclosure already establish this threat.
- We are **not** the first temporal MCP security system. MCPShield reasons over historical traces, FlowGuard uses history-guided refinement, and TrustShiftProbe (Aug. 2026) explicitly studies staged temporal attacks.
- We are **not** the first to identify gradual capability escalation as a threat. Formal MCP threat models already describe it.
- We are **not** the first MCP tool-poisoning benchmark. MCPTox, MCP-AttackBench, MCP-SafetyBench, MCPSecBench and others already exist.
- We should not claim that hashes/signatures are obsolete. They solve integrity and provenance; DriftGuard solves the meaning and security significance of an authorized or otherwise observed change.

## Current related-work map

| Work | Primary object | Temporal/history aware? | Learned semantic detection? | Main gap relative to DriftGuard |
|---|---|---:|---:|---|
| MCP-Guard (2025/ACL 2026) | Current tool/adversarial content snapshot | No | Yes | Does not make approved-vs-current tool-definition change the ML object |
| Securing MCP / signed manifests (2025) | Descriptor integrity + current semantic vetting | Limited | LLM judge | Signing tells that content changed; not whether the change is benign, capability-expanding, or malicious |
| MCPShield (2026) | Runtime tool behavior and historical traces | Yes | Reasoning/probing | Focuses on runtime cognition/probing rather than version-sequence classification of tool definitions |
| FlowGuard (2026) | Runtime execution evidence + semantic risks | Some history | Semantic triage | Execution/evidence-grounded scanner, not approved-schema evolution classification |
| DCIChecker (2026) | Description-vs-code consistency | No version sequence | LLM semantic checking | Compares description with implementation, not previous/current tool-definition versions |
| TrustShiftProbe (Aug. 2026) | Temporally staged server **results/behavior** | Yes | Multi-tier runtime defense | Explicitly trusts tool schemas and studies output/result corruption; low-and-slow drift is left as a future direction |
| MCPoison / Cursor fix | MCP configuration changes after approval | Yes at integrity level | No | Re-approval on every modification is safe but treats harmless and dangerous changes equally |
| mcp-tester rug-pull pinning | Description/schema hash + textual diff | Yes | No | Detects change but explicitly cannot classify legitimate vs malicious change |
| Official MCP 2026-07-28 | Dynamic tool discovery/list changes | Protocol support | No | Defines change notifications and cacheability, but no semantic trust or re-consent policy |

## Defensible research gap

The strongest gap is **security-significance classification over tool-definition version sequences**.

Existing systems mostly answer one of these questions:

1. Is the current artifact suspicious?
2. Did the artifact change?
3. Does the current implementation match its description?
4. Did the server's runtime behavior deviate from a historical baseline?

DriftGuard asks a different question:

> **How did the security-relevant meaning and effective capability of an already-approved MCP tool change across versions, and does that change require silent acceptance, re-consent, or blocking?**

That distinction remains useful even when every version is cryptographically signed by the legitimate publisher. A signed update can still expand capabilities or become malicious.

## Core research contributions

The paper should be built around four contributions, not a generic scanner.

### C1. Capability-Aware Version-Pair Representation

Instead of embedding a raw JSON blob, represent the change between `T_old` and `T_new` through multiple security views:

- tool purpose: name/title/description;
- input contract: parameters, parameter descriptions, required set, defaults, enums and types;
- output contract;
- MCP safety annotations;
- external interaction indicators such as URLs/domains;
- cross-tool references and selection-manipulation language;
- full canonical schema.

In addition to embedding distances, infer a structured **effective capability vector** such as:

`<operation, resource, effect, scope, destination, sensitivity>`

Examples:

- `<read, repository, observe, selected repo, local, normal>`
- `<write, filesystem, mutate, arbitrary path, local, sensitive>`
- `<send, credential, exfiltrate, external host, network, critical>`

The key feature is the **capability delta** between versions, not only lexical drift.

### C2. Consent-Aware Four-Class Change Semantics

Use operational labels:

- **C0**: no meaningful change;
- **C1**: benign maintenance;
- **C2**: legitimate but security-significant capability expansion requiring re-consent;
- **C3**: malicious or suspicious semantic drift.

C2 is important because exact-change systems over-prompt while benign/malicious binary systems may silently allow legitimate but high-impact permission expansion.

The research question is whether a model can learn the **consent boundary** rather than only a maliciousness boundary.

### C3. Sequential Drift Budget for Low-and-Slow Rug Pulls

Pairwise detection alone is insufficient against an adversary who makes many small updates, each below a review threshold.

For a version sequence

`T0 -> T1 -> T2 -> ... -> Tn`

compute a per-update security drift vector `d_t` and maintain a stateful sequential detector.

We should evaluate at least two formulations:

1. **Weighted cumulative trust budget**
   `B_t = lambda * B_(t-1) + w^T d_t`

2. **Sequential change detection**, such as multivariate CUSUM or Bayesian online change-point detection, over semantic/capability delta streams.

The contribution is not merely saying that gradual escalation exists. The contribution is an evaluated defense against **low-and-slow tool-definition drift**.

This is especially defensible after TrustShiftProbe: that work studies temporally staged runtime-result corruption, explicitly trusts tool schemas, and identifies patient low-and-slow drift as an important future experiment. DriftGuard targets the complementary definition/approval channel.

### C4. Temporal MCP Tool-Evolution Benchmark

Create a paired and sequential dataset rather than another static poisoning corpus.

#### Real benign evolution

Mine open-source MCP repositories and reconstruct actual tool-definition histories from commits/releases. Extract versions where names, descriptions, schemas, defaults, annotations or outputs change.

Human-label a high-quality subset with a written annotation guide.

#### Security-significant and malicious evolution

Starting from real benign versions, generate schema-valid transformations for:

- direct descriptor poisoning;
- implicit/cross-tool instructions;
- capability escalation;
- new sensitive required parameters;
- misleading defaults;
- external-domain introduction;
- annotation contradictions;
- semantic shadowing/preference manipulation;
- Unicode/approval-view concealment cases;
- low-and-slow multi-version poisoning trajectories.

#### Leakage control

Use repository-level/server-level splits. Do not allow near-duplicate versions from the same server to appear across train and test.

Also report **attack-family-held-out** generalization, not only random splits.

## Strongest novelty claim to pursue

A defensible paper claim, if the final literature review and experiments continue to support it, is:

> To the best of our knowledge, DriftGuard is the first system to formulate MCP tool-definition security as consent-aware classification over version sequences and to evaluate capability-aware sequential detection of low-and-slow schema rug pulls.

Do not use the word **first** in a submission until the literature review is rerun immediately before paper submission.

## Method architecture

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
 drift budget / CUSUM / BOCPD
              |
              v
      policy + re-consent gate
```

## Models and baselines

### Baselines

1. Hash-only: any change => alert/re-consent.
2. Textual diff / edit-distance threshold.
3. Risk-regex/YARA-style rules.
4. Full-schema cosine distance.
5. Field-aware cosine distances without structural features.
6. Single-snapshot learned classifier.
7. LLM-as-judge on `T_new`.
8. LLM-as-judge on `(T_old, T_new)`.

### Proposed models

**Model A: Capability-aware gradient boosting**

- field-level embedding distances;
- PCA-projected before/after/difference features;
- structural delta features;
- capability delta vector;
- annotation consistency features.

XGBoost/LightGBM is attractive because it is fast, explainable and strong on mixed structured features.

**Model B: Pair encoder / Siamese head**

Use representations such as:

`z = [e_old ; e_new ; |e_old-e_new| ; e_old * e_new ; f_struct ; f_capability]`

Compare against Model A rather than assuming neural is better.

**Sequential layer**

Evaluate cumulative score, CUSUM and one online change-point method. The sequential method sits above the pair classifier and consumes calibrated delta/risk outputs.

## Evaluation questions

### RQ1: Pairwise value

Does approved-vs-current classification outperform hash-only, cosine-only, single-snapshot classifiers and LLM judges on benign-update false positives and malicious-drift recall?

### RQ2: Capability representation

Does capability-aware fusion outperform embeddings-only and structure-only features?

### RQ3: Consent boundary

Can C2 legitimate capability expansion be separated from both C1 benign maintenance and C3 malicious escalation?

### RQ4: Low-and-slow attacks

Can sequential drift detection identify gradual tool-definition rug pulls that remain below every pairwise threshold?

### RQ5: Generalization

How well does the detector generalize to held-out repositories and held-out poisoning families, including optimized adversarial paraphrases?

### RQ6: Operations

What latency, storage and false re-consent rate does the system add to realistic `tools/list` workloads?

## Metrics

Classification:

- macro-F1;
- class-wise precision/recall;
- C3 AUROC/AUPRC;
- C2 recall and confusion with C3;
- calibration error / Brier score;
- false-positive rate on real benign evolution.

Sequential detection:

- trajectory detection rate;
- average detection delay in versions;
- false alarms per 100 benign updates;
- minimum detectable cumulative drift;
- detection rate when every local step remains below the pairwise threshold.

Operational:

- milliseconds per changed tool;
- memory and snapshot storage overhead;
- unnecessary re-consent prompts per 100 benign updates.

Security impact:

- attack success rate before and after policy enforcement in a controlled MCP agent testbed.

## Ablation plan

- embeddings only vs structural only vs capability only vs hybrid;
- one full-schema embedding vs field-aware embeddings;
- current snapshot only vs version pair;
- pairwise only vs pairwise + sequential detector;
- without MCP annotations vs with annotations;
- synthetic-only benign data vs real benign histories;
- random split vs repository-level split;
- known attack families vs held-out attack families.

## Failure cases we should explicitly study

- semantically large but harmless documentation rewrites;
- tiny wording changes with a major implied authority change;
- attacker modifies only defaults or enum values;
- description unchanged while required sensitive parameter is added;
- annotations stay benign while description/schema implies destructive behavior;
- Unicode TAG/zero-width concealment;
- legitimate new external-domain capability;
- many tiny changes whose cumulative effect is dangerous;
- tool rename/replacement that breaks simple lineage matching;
- localization/i18n changes;
- version rollback to an older approved-but-riskier schema.

## Relationship to MCP 2026-07-28

The 2026-07-28 specification explicitly allows tool lists to change over time and provides `notifications/tools/list_changed` for servers that support it. That gives DriftGuard a protocol-native interception point.

The detector should therefore support:

- initial approved snapshot;
- re-fetch on list-change notification;
- cache-aware comparison;
- deterministic canonicalization;
- server/tool lineage identifiers;
- fallback periodic revalidation for servers that do not emit change notifications.

## Paper structure

1. Introduction and motivating rug-pull scenario
2. MCP tool-definition lifecycle and threat model
3. Related work and why current detectors do not classify version sequences
4. Temporal MCP Tool-Evolution Benchmark
5. Capability-aware pair representation
6. Consent-aware classifier
7. Sequential low-and-slow drift detector
8. Experimental setup
9. Results and ablations
10. Limitations and responsible use
11. Conclusion

## Seed abstract

Model Context Protocol (MCP) clients increasingly rely on dynamically discovered tool definitions to decide what external capabilities an agent may invoke. Existing defenses can detect suspicious tool metadata, verify artifact integrity, or monitor runtime behavior, but they do not adequately distinguish harmless evolution of an approved tool definition from security-significant capability expansion and malicious post-approval drift. We present DriftGuard, a version-aware MCP defense that treats tool-definition evolution as a temporal security problem. DriftGuard fuses field-aware semantic change with typed structural and effective-capability deltas, classifies each update into no-op, benign maintenance, capability expansion requiring re-consent, or malicious drift, and applies a sequential drift detector to identify low-and-slow rug pulls spread across multiple individually small updates. We evaluate DriftGuard on a temporal benchmark constructed from real MCP tool-definition histories and schema-valid adversarial transformations, using repository-disjoint and attack-family-held-out splits. We compare against hash, regex, cosine, single-snapshot, and LLM-judge baselines and measure classification quality, calibration, re-consent false positives, low-and-slow detection delay, and pre-execution latency.

## Publication strategy

Do not release implementation details simply to gain GitHub visibility. Keep the development repository private while experiments are immature.

For peer review, we can choose one of three artifact strategies depending on venue requirements:

1. keep code private and provide a detailed methods appendix;
2. provide an anonymized reviewer-only artifact;
3. after acceptance, release only a restricted research artifact or benchmark under separate non-commercial/research terms while keeping production code proprietary.

The paper and the software do not need to use the same license.

## Literature that materially affects positioning

- Xing et al., **MCP-Guard**, arXiv:2508.10991 / ACL Findings 2026.
- Wang et al., **MCPTox**, arXiv:2508.14925 / AAAI 2026.
- Li et al., **MCP-ITP**, arXiv:2601.07395.
- Zhou et al., **MCPShield**, arXiv:2602.14281.
- Huang et al., **Model Context Protocol Threat Modeling...**, arXiv:2603.22489.
- Acharya and Gupta, **A Formal Security Framework for MCP-Based AI Agents**, arXiv:2604.05969.
- **Description-Code Inconsistency in Real-world MCP Servers**, arXiv:2606.04769.
- An et al., **FlowGuard**, arXiv:2607.14754.
- Rashidi, **Unicode TAG-Block Concealment...**, arXiv:2607.05744.
- Rostamzadeh et al., **TrustShiftProbe**, arXiv:2608.23763.
- Check Point Research, **MCPoison / CVE-2025-54136**.
- Model Context Protocol specification **2026-07-28**, Tools and list-change notification semantics.

## Decision

The implementation should now prioritize, in order:

1. robust version lineage + schema history;
2. field-aware embedding and structural delta pipeline;
3. capability-delta representation;
4. C0/C1/C2/C3 pair classifier with calibration;
5. real benign history mining + attack trajectory generator;
6. low-and-slow sequential drift detector;
7. evaluation harness and ablation suite;
8. only then optional cross-tool graph and counterfactual explanation work.

Cross-tool graph analysis and counterfactual explanations are useful extensions, but they should not dilute the main paper thesis.
