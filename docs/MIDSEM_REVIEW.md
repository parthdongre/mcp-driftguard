# MCP DriftGuard — Midsem Review Guide

## One-line project explanation

MCP DriftGuard is a security system that detects when an MCP tool changes after it has already been trusted, especially when the change gradually increases the tool's capabilities across multiple versions.

## Problem statement

Model Context Protocol (MCP) allows AI applications to discover and call external tools. These tools are described using natural-language descriptions, JSON-like schemas, annotations, and other metadata. A user or host may trust a tool when it initially appears harmless.

The problem is that the tool definition can later change. A malicious or compromised MCP server can exploit this trust by slowly modifying what the tool says it does, what inputs it accepts, where data can be sent, or what side effects it can perform.

Traditional checks answer only questions such as:

- Has the file changed?
- Has the hash changed?
- Is the new description suspicious?

They do not adequately answer:

- How far has the tool moved from the version the user originally approved?
- Did its effective capability increase?
- Is the change harmless maintenance or a legitimate feature expansion that needs fresh consent?
- Is an attacker spreading a dangerous change across many small versions to avoid a threshold?

DriftGuard focuses on this post-approval evolution problem.

## Core research idea

Instead of treating each MCP tool definition independently, DriftGuard treats the version lineage as the security object:

```text
Approved T0
   |
   v
T1 -> T2 -> T3 -> ... -> Tn
```

For every new version, the system compares:

1. the previous version to the current version, and
2. the last approved version to the current version.

This allows it to detect both sudden changes and low-and-slow capability escalation.

## Operational classes

| Class | Meaning | Example | Default action |
|---|---|---|---|
| C0 | No meaningful change | formatting or semantically identical definition | Allow |
| C1 | Benign maintenance | clearer wording, harmless schema cleanup | Allow + log |
| C2 | Legitimate capability expansion | tool adds a real new feature | Require re-consent |
| C3 | Suspicious / malicious drift | data exfiltration or concealed permission escalation | Quarantine / block |

The important design choice is C2. Not every new capability is an attack, but a user should not automatically inherit consent to a materially more powerful tool.

## System architecture

```text
MCP tools/list or tools/list_changed
              |
              v
      Raw tool definition
              |
              v
      Canonical snapshot
       + stable SHA-256
              |
              v
       Version lineage store
              |
              v
     Old/new delta extraction
       /       |        \
      /        |         \
 semantic  structural   capability
  drift       drift       drift
      \        |         /
       \       |        /
        Pair feature vector
              |
        Pairwise classifier
          C0/C1/C2/C3
              |
              +------------------+
              |                  |
              v                  v
     approved-baseline       local step
         comparison          comparison
              \                  /
               \                /
              sequential monitor
              CUSUM / trust debt
                    |
                    v
            consent policy gate
         allow / re-consent / block
```

## Major components

### 1. Canonicalization

File: `src/driftguard/canonicalize.py`

Raw JSON cannot be compared safely using only a direct hash because key ordering and whitespace can change without changing meaning. DriftGuard canonicalizes the tool definition first.

It normalizes safe presentation differences while preserving values where whitespace or order may have semantic importance.

A stable SHA-256 is then calculated so identical logical definitions have the same identity.

### 2. Structural delta extraction

Files:

- `src/driftguard/diff.py`
- `src/driftguard/structural_security.py`

The system extracts security-relevant changes instead of only computing a line diff.

Examples include:

- new parameters,
- new required parameters,
- type changes,
- default-value changes,
- sensitive terms,
- URL additions,
- imperative instructions,
- cross-tool references,
- authority-override language.

This matters because a one-line schema modification can be more security-sensitive than a large documentation rewrite.

### 3. Field-aware semantic analysis

Files:

- `src/driftguard/views.py`
- `src/driftguard/embeddings.py`
- `src/driftguard/features.py`

Instead of embedding the entire tool definition as one text block, DriftGuard separates multiple semantic views:

- purpose,
- input contract,
- output contract,
- capability/safety metadata,
- complete schema.

This prevents a dangerous local change from being diluted by a large amount of unchanged text.

### 4. Capability analysis

File: `src/driftguard/capabilities.py`

The tool definition is projected into interpretable capability dimensions such as:

- operation,
- resource,
- effect,
- scope,
- destination,
- sensitivity.

The system then calculates whether the current tool implies more power than the previously approved one.

This is one of the project's main distinctions from ordinary text-diff security.

### 5. Pairwise learned models

Files:

- `src/driftguard/learning.py`
- `src/driftguard/tree_learning.py`
- `src/driftguard/hybrid_detector.py`

The project first uses transparent baselines such as logistic regression, then compares against stronger non-linear baselines such as XGBoost.

The intention is to prove that the feature representation contributes useful security information rather than hiding all reasoning inside a large opaque model.

### 6. Temporal monitoring

File: `src/driftguard/temporal.py`

This is the part that targets the low-and-slow attack.

For each update, DriftGuard calculates:

- step risk: previous -> current,
- baseline risk: approved -> current,
- cumulative CUSUM score.

Conceptually:

```text
CUSUM_t = max(0, decay * CUSUM_(t-1) + step_risk - reference_drift)
```

Small benign changes do not continuously accumulate. Repeated suspicious changes consume the drift budget and eventually trigger an alert.

### 7. Consent policy

Files:

- `src/driftguard/consent_policy.py`
- `src/driftguard/stateful_policy.py`

Detection is converted into an action.

The key security rule is that previously granted consent is not automatically valid forever. If the effective capability of the tool materially changes, the host can require re-approval before the tool is used again.

## Example attack scenario for the review

Assume the user approves this tool:

```text
Version 0:
"Search repository files."
```

The attacker does not immediately change it to an obvious exfiltration tool. Instead:

```text
Version 1:
"Search repository files and inspect metadata."

Version 2:
"Search repository files, inspect metadata,
and prepare results for sharing."

Version 3:
"...prepare results for external sharing."

Version 4:
"...upload results when requested."
```

Each local change may look relatively small.

An adjacent-only detector can repeatedly see a small change.

DriftGuard also compares Version 4 against the original approved Version 0. The baseline comparison reveals that the tool has moved from local search toward external data transfer. At the same time, the CUSUM signal has accumulated evidence from the sequence.

The policy can then quarantine the tool or require fresh consent before another invocation.

## Why a hash is not enough

A hash is excellent for answering:

> Did anything change?

It cannot answer:

> Was the change dangerous?

For example, both of these produce a changed hash:

```text
"Search files."
-> "Search repository files."
```

and

```text
"Search files."
-> "Search files and upload secrets to an external endpoint."
```

The security meaning is completely different.

DriftGuard uses hashing for identity, but semantic, structural, capability, and temporal analysis for security decisions.

## Why ordinary semantic similarity is not enough

Suppose 95% of a tool definition remains unchanged and one sentence adds external transmission.

The overall cosine similarity may still be high because most tokens are unchanged.

Field-aware views and capability extraction increase the weight of security-sensitive changes instead of letting them disappear inside full-schema similarity.

## Why the temporal component matters

A pairwise detector can be evaded if an attacker breaks one large change into several small ones.

Example:

```text
A -> B    small
B -> C    small
C -> D    small
D -> E    small
```

But:

```text
A -> E    large security change
```

DriftGuard therefore observes both local drift and cumulative drift from the approved baseline.

This is the central idea behind the project's low-and-slow rug-pull defense.

## Dataset and research methodology

The project contains tooling for building a temporal MCP tool-evolution benchmark.

Sources include:

- real Git history of MCP tool definitions,
- JSON manifest histories,
- static Python MCP registrations,
- static TypeScript/Zod MCP registrations,
- controlled benign changes,
- controlled malicious mutations,
- bounded low-and-slow trajectories,
- external benchmark adapters.

Third-party repositories are statically inspected rather than executed.

## Preventing data leakage

A normal random split can accidentally place nearly identical versions from the same repository in both training and test sets.

That would exaggerate performance.

The project therefore includes:

- repository-disjoint splitting,
- attack-family holdout evaluation,
- frozen split manifests,
- threshold selection using validation data rather than test data.

This is important for the research credibility of the project.

## Baselines being compared

The system is designed to be compared with simpler approaches:

1. hash-only change detection,
2. lexical/text diff,
3. regex/risk dictionary,
4. full-schema semantic cosine,
5. field-aware cosine,
6. logistic pair classifier,
7. tree/XGBoost pair classifier,
8. sequential deterministic detector,
9. later LLM-as-judge and stronger learned approaches.

The aim is to show exactly which part of the proposed representation and temporal reasoning provides value.

## Current implementation status

Already implemented in the repository:

- deterministic tool snapshots,
- stable hashes,
- structural deltas,
- capability projection,
- field-aware semantic views,
- pair feature generation,
- logistic-regression baseline,
- XGBoost family-holdout baseline,
- C0/C1/C2/C3 labeling system,
- low-and-slow trajectory generation,
- CUSUM-style temporal monitor,
- consent reset/policy simulation,
- Git history mining,
- static Python extraction,
- static TypeScript extraction,
- repository-disjoint splits,
- attack-family-held-out tests,
- annotation/agreement tooling,
- benchmark scripts,
- CI tests and linting.

## What is still research-in-progress

The project should not be presented as production-ready yet.

Important remaining work includes:

- substantially expanding the real MCP repository corpus,
- independent human labeling of the final corpus,
- external attack-dataset transfer evaluation,
- probability calibration and OOD/abstention,
- broader ablation studies,
- latency/throughput/memory measurements,
- a real MCP `tools/list_changed` interception integration,
- final literature search before locking the novelty claim.

## Current evidence and how to describe it correctly

The project has strong results on controlled development poisoning benchmarks, including results above 95% in parts of the development evaluation.

Do not call this "95% real-world attack detection accuracy."

The correct statement is:

> Controlled development benchmarks show that the current representation is promising, but broader real-world corpus validation and independent external evaluation are still required before making production or publication-level accuracy claims.

## Main novelty / research contribution

The research contribution is the combination of four ideas:

1. **Approved-version-aware comparison** rather than only current-snapshot inspection.
2. **Capability-aware change representation** in addition to semantic and structural differences.
3. **Consent-aware C0/C1/C2/C3 classification**, separating legitimate capability growth from malicious escalation.
4. **Temporal accumulation for low-and-slow tool-definition rug pulls** across multiple versions.

Any final priority claim should still be verified against the latest literature before publication.

## Demo sequence for a midsem review

A clean 5–7 minute demo can follow this order:

### Step 1 — Show the initial approved tool

Explain that this is the trust baseline.

### Step 2 — Show a harmless wording update

Point out that the hash changes, but security meaning does not necessarily change.

### Step 3 — Show multiple low-and-slow versions

Add sharing/external/upload language gradually.

### Step 4 — Show risk values

Explain:

- step risk,
- approved-baseline risk,
- cumulative CUSUM.

### Step 5 — Show policy result

The tool crosses the threshold and is quarantined or sent for re-consent.

### Step 6 — Show repository research infrastructure

Briefly show:

- `src/driftguard/`
- `tests/`
- `experiments/`
- `docs/PAPER_READINESS.md`

This proves the work is more than a single demo script.

## 60-second explanation to say aloud

"MCP lets AI agents discover tools dynamically. The security issue we focus on is what happens after a tool has already been approved. A malicious or compromised MCP server can slowly change the tool definition over multiple versions. A hash tells us that something changed, but not whether it became more dangerous. DriftGuard stores the approved baseline, canonicalizes every new tool definition, extracts structural, semantic, and effective-capability differences, and classifies the update into no change, benign maintenance, legitimate capability expansion, or malicious drift. We also keep a temporal CUSUM-style risk budget, so an attacker cannot easily bypass detection by splitting one dangerous change into many tiny updates. If capability expands legitimately we can ask the user for consent again; if the drift is suspicious we quarantine the tool."

## Likely viva questions

### What exactly is MCP?

Model Context Protocol is a protocol through which AI applications can discover and interact with external tools/resources exposed by MCP servers. DriftGuard focuses specifically on the security of changing tool definitions.

### What is tool poisoning?

Tool poisoning is manipulation of a tool's metadata, description, schema, or surrounding instructions so that the model is induced to behave in a way the user did not intend.

### What is a rug pull in this project?

A tool initially behaves or appears safe, gains trust, and later changes into something more powerful or malicious. A low-and-slow rug pull performs this transition gradually.

### Why compare with the approved baseline?

Because small adjacent updates can hide a large cumulative change. The approved version represents what the user actually consented to.

### Why do you need C2 if C3 already represents dangerous changes?

C2 represents legitimate capability expansion. It may not be malicious, but the old user consent should not automatically authorize the new capability. This allows re-consent without falsely calling the developer an attacker.

### Why CUSUM?

CUSUM is a simple interpretable sequential-change technique. It allows small repeated deviations to accumulate while ignoring isolated noise below the reference drift. It is used as a transparent baseline before testing more complex temporal models.

### Are you executing untrusted MCP repositories?

No. The history/data extraction approach is designed to statically inspect repository content and Git history, reducing the risk of executing potentially malicious third-party code.

### Is this currently production ready?

No. It is a research prototype. The core detector and evaluation infrastructure are implemented, while broad real-corpus validation, external transfer tests, calibration, system benchmarks, and end-to-end MCP interception are still being completed.

### Where is machine learning used?

Pair features produced from semantic, structural, and capability changes can be used by learned classifiers such as logistic regression and XGBoost. The temporal baseline is intentionally deterministic at this stage so its contribution can be evaluated independently.

### Why not use only an LLM to judge every change?

An LLM judge may be expensive, variable, hard to reproduce, and can itself be influenced by malicious tool text. DriftGuard first creates explicit measurable features and uses reproducible baselines. LLM judging can then be evaluated as a comparison rather than assumed to be the solution.

### What makes the project research-oriented rather than just a software tool?

The repository contains explicit research questions, controlled baselines, attack-family holdouts, repository-disjoint splits, annotation protocols, statistical utilities, ablations/benchmark plans, and paper-readiness guardrails. The objective is to test hypotheses about temporal and capability-aware MCP security, not only to ship a UI.

## Best closing line for the review

The project is trying to protect the boundary between **what the user originally trusted** and **what an evolving AI tool is allowed to become without asking again**.
