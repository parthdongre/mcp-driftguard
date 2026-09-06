# Research Problem V2: Consent-Optimal Detection of Adversarially Budgeted MCP Tool Evolution

## Working paper title

**DriftGuard: Consent-Optimal Sequential Detection of Bounded Rug Pulls in Evolving Model Context Protocol Tool Surfaces**

## Why the research problem changed

A paper about detecting suspicious text in MCP tool descriptions is no longer sufficiently distinct. Existing work already covers learned semantic poisoning detectors, large poisoning benchmarks, implicit poisoning optimized to evade detectors, runtime evidence, staged server behavior, tool-surface integrity controls, and general MCP evolution.

DriftGuard therefore focuses on a narrower and harder security problem: **an MCP tool is already trusted, then evolves through multiple individually small, schema-valid changes that cumulatively cross the capability boundary the user originally approved.**

The research objective is not simply to maximize malicious/benign classification accuracy. The defender must simultaneously:

1. detect malicious cumulative capability drift;
2. distinguish benign maintenance from legitimate capability expansion;
3. request re-consent only when the user's approved capability envelope is materially crossed;
4. catch low-and-slow rug pulls whose individual updates stay below local alarms;
5. minimize consent fatigue and false security interventions.

This turns MCP drift defense into a **sequential security decision problem under an adversarial local-change budget**.

---

## Formal problem

Let an MCP tool definition at version `t` be a structured security object:

`T_t = {name, description, input schema, output schema, annotations, metadata, capability projection}`

The user approves `T_0`. That snapshot establishes an approved capability envelope `Gamma(T_0)`.

For every later version, define a field-aware transition representation:

`Delta_t = Phi(T_{t-1}, T_t)`

where `Phi` includes semantic, lexical, schema-structural, sensitive-data, destination, annotation, and effective-capability changes.

A normal one-step detector evaluates only `Delta_t`. A bounded attacker instead chooses a sequence:

`T_0 -> T_1 -> ... -> T_n`

subject to a local stealth constraint:

`d(T_{t-1}, T_t) <= epsilon` for every `t`.

The attacker succeeds if the final tool crosses the original authorization boundary:

`C(T_n) not_subset_of Gamma(T_0)`

while individual transitions remain locally unremarkable.

DriftGuard observes the entire approved lineage:

`H_t = (T_0, T_1, ..., T_t)`

and chooses an action:

`pi(H_t) in {ALLOW, MONITOR, RECONSENT, BLOCK}`.

The research goal is to learn or design `pi` so that it minimizes user-intervention cost while satisfying strong security constraints.

A publication-oriented constrained objective is:

`minimize Expected[unnecessary re-consent + detection delay]`

subject to:

- malicious recall >= 95%;
- benign false-positive rate <= 3%;
- high recall on attack families never seen during training;
- high detection rate on bounded low-and-slow trajectories;
- thresholds selected without access to the final test labels.

This explicitly models the **security-usability trade-off** rather than treating every change as either harmless or malicious.

---

## Change/consent labels

DriftGuard preserves the four-class formulation:

- **C0 — No meaningful change:** canonical or security-equivalent change.
- **C1 — Benign maintenance:** documentation, clarification, bug-compatible schema cleanup, or other change that does not materially expand authority.
- **C2 — Legitimate capability expansion:** a real new capability or permission that may be legitimate but exceeds the existing consent envelope and therefore requires re-consent.
- **C3 — Malicious/suspicious drift:** poisoning, deceptive privilege expansion, hidden sinks, authority override, credential harvesting, shadowing, concealment, or a staged rug pull.

The distinction between C2 and C3 is central. A secure system should not label every product improvement as an attack, but it should also not silently inherit consent for a materially stronger tool.

---

## Core threat model: Bounded Tool-Surface Drift

We introduce the working threat model **Bounded Tool-Surface Drift (BTSD)**.

An adversary controls or compromises an MCP server after a tool has been approved. Instead of inserting an obviously malicious definition in one update, the adversary distributes the target capability change across versions. Every adjacent update must satisfy a configurable local drift budget over:

- semantic change;
- lexical change;
- capability escalation;
- number of structural changes;
- new sensitive concepts;
- new external destinations;
- annotation changes;
- cross-tool references.

A trajectory counts as genuinely low-and-slow only when all adjacent updates remain inside that budget while the approved-to-final endpoint crosses the same security boundary.

This prevents weak experiments where a sequence is called low-and-slow even though one intermediate update is already obviously malicious.

The implementation begins in `src/driftguard/bounded_drift.py`.

---

## Research questions

### RQ1 — Version-pair security classification

Can a field-aware old/new classifier distinguish C0, C1, C2, and C3 more accurately and with fewer false positives than hash, edit-distance, rule, cosine, single-snapshot, and flat-text baselines?

### RQ2 — Consent-boundary inference

Can DriftGuard distinguish legitimate capability expansion requiring re-consent (C2) from malicious capability escalation (C3), instead of collapsing both into a generic anomaly label?

### RQ3 — Bounded low-and-slow rug pulls

Can a sequential detector identify trajectories in which every adjacent version remains below a predefined local drift budget but the final capability surface violates the originally approved envelope?

### RQ4 — Security versus consent fatigue

At a fixed malicious-recall constraint, how much can DriftGuard reduce unnecessary re-consent compared with block-on-change, reapprove-on-any-schema-change, and ordinary anomaly-threshold policies?

### RQ5 — Unseen attack-family generalization

How well does the detector transfer to poisoning families withheld completely from training, including attacks imported from independently authored datasets?

### RQ6 — Future-version generalization

How well does a model trained on earlier MCP evolution generalize to later repository versions and newly introduced mutation patterns?

### RQ7 — Component contribution

How much do field-aware semantics, typed structural deltas, capability projection, hard structural invariants, approved-baseline comparison, and sequential accumulation each contribute?

---

## Main hypotheses

- **H1:** pairwise semantic + structural + capability features outperform single-snapshot and semantic-only baselines on C2/C3 separation.
- **H2:** repository-disjoint hybrid models retain high malicious recall while materially reducing false positives on real benign history.
- **H3:** approved-baseline + sequential accumulation detects bounded low-and-slow attacks missed by adjacent-only detectors.
- **H4:** consent-aware policy achieves a better malicious-recall/re-consent Pareto frontier than reapprove-on-any-change.
- **H5:** explicit security invariants improve unseen structural-family recall without materially increasing benign false positives.

---

## Proposed research contributions

### Contribution 1: A formal bounded-drift threat model

Formulate post-approval MCP rug pulls as adversarial sequences constrained by a per-update local-change budget.

### Contribution 2: Consent-aware temporal classification

Model MCP changes as C0/C1/C2/C3 rather than binary safe/malicious decisions.

### Contribution 3: Capability-envelope-aware sequential detection

Compare both adjacent versions and the currently observed version against the last explicitly approved baseline, while accumulating weak local evidence across the lineage.

### Contribution 4: A security-labeled temporal MCP evolution benchmark

Combine independently annotated real repository histories, controlled benign evolution, independent external poisoning datasets, attack-family holdouts, and bounded multi-version rug-pull trajectories.

### Contribution 5: Security-consent Pareto evaluation

Evaluate not only attack detection but also unnecessary re-consent, false blocks, intervention frequency, and detection delay.

### Contribution 6: Independent generalization evaluation

Normalize independently authored attack datasets into version-pair form and reserve them for transfer/holdout evaluation instead of allowing DriftGuard's own generator to define the full test distribution.

---

## Distinction from closely related work

The exact priority claim must be rechecked immediately before submission because MCP security work is moving quickly.

- **MCP-Guard / MCP-AttackBench:** strong learned semantic poisoning detection and a large attack benchmark; not centered on consent-aware evolution across an approved version lineage.
- **MCPTox:** large realistic poisoning evaluation built from authentic tools; primarily static attack cases, not approved-to-current sequences.
- **MCP-ITP:** optimizes implicit poisoning to evade detectors; valuable as an external adversarial source for DriftGuard evaluation.
- **FlowGuard:** uses runtime evidence and history-guided refinement; focuses on verifying execution-related/security findings, not bounded tool-definition evolution and consent fatigue.
- **TrustShiftProbe:** explicitly studies staged temporal trust attacks, but at the runtime/server-payload behavior layer. DriftGuard targets the definition/capability lineage exposed before execution.
- **MCPEvol-Bench:** studies agent adaptability under evolving MCP tool interfaces. DriftGuard studies the security/authorization meaning of evolution.
- **ShieldMCP and other runtime gateways:** validate calls/responses and tool-layer threats during execution; DriftGuard's primary decision point is the changed tool surface before tool use.
- **Provenance-bound capability-envelope pinning / block-and-reapprove controls:** establish important integrity and reapproval mechanisms for changed tool surfaces. DriftGuard asks a different empirical question: can a learned and sequential policy distinguish safe maintenance, re-consent-worthy expansion, and adversarially budgeted rug pulls while reducing unnecessary reapproval?

The defensible novelty is therefore not "first semantic MCP detector", "first temporal MCP defense", or "first MCP evolution benchmark". The strongest working claim is the combination of **bounded adversarial tool-definition evolution + consent-boundary classification + sequential capability drift + consent-cost evaluation**.

---

## What would make the problem publication-grade

The paper should be considered ready only after all of the following are completed:

1. hundreds to thousands of independently reviewed real historical transitions from a broad MCP repository sample;
2. independent C0/C1/C2/C3 annotation and inter-annotator agreement;
3. external attack datasets converted without contaminating training decisions;
4. repository-disjoint, attack-family-disjoint, and future-version evaluation;
5. bounded low-and-slow trajectories satisfying explicit local drift constraints;
6. validation-only threshold/policy selection;
7. confidence intervals and repeated-seed reporting;
8. complete baseline and ablation tables;
9. latency/resource measurements;
10. a frozen experiment artifact containing code version, data manifest, split manifest, seeds, thresholds, and environment.

---

## Key references to track before submission

- MCP-Guard / MCP-AttackBench, arXiv:2508.10991
- MCPTox, arXiv:2508.14925
- MCP-ITP, arXiv:2601.07395
- MCP threat modeling and client tool-poisoning analysis, arXiv:2603.22489
- ShieldMCP, ACL Industry 2026
- MCPEvol-Bench, arXiv:2607.14642
- FlowGuard, arXiv:2607.14754
- TrustShiftProbe, arXiv:2608.23763
- IEEE TSE 2026, Beyond the Protocol: MCP ecosystem attack vectors
- Provenance-Bound Capability-Envelope Pinning of an MCP Tool Surface, Technical Disclosure Commons, June 2026
- MCP specification 2026-07-28 tool `listChanged` behavior and human-in-the-loop guidance
