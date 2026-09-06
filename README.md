# MCP DriftGuard

Version-aware semantic drift detection for MCP tool poisoning, rug pulls, capability escalation, and schema evolution.

## Why this project exists

Model Context Protocol (MCP) clients discover tools through tool definitions containing natural-language descriptions and structured schemas. Those definitions become part of the model's reasoning context. A tool may therefore be safe when first approved and later change in a security-significant way.

Traditional integrity checks can tell that a definition changed, but not whether the change is:

- semantically equivalent,
- benign maintenance,
- a legitimate capability expansion that should require re-consent, or
- malicious tool poisoning / rug-pull behavior.

MCP DriftGuard treats **the change between a previously trusted tool definition and its current definition as the primary security object**.

## Core research task

Given a trusted tool schema `T_old` and a newly observed schema `T_new`, DriftGuard computes field-aware semantic and structural deltas and predicts one of four operational classes:

| Class | Meaning | Default action |
|---|---|---|
| `C0` | No meaningful change | Allow |
| `C1` | Benign maintenance | Allow + log |
| `C2` | Legitimate capability expansion | Require re-consent |
| `C3` | Malicious / suspicious semantic drift | Quarantine / block |

## Planned detection pipeline

```text
MCP Server
   |
   v
Discovery Interceptor (tools/list)
   |
   v
Canonicalizer + Field Splitter
   |-----------------------> Trusted Snapshot Store
   v
Pairwise Delta Engine
   |-- semantic distances
   |-- typed structural deltas
   |-- sensitive capability signals
   |-- instruction / override signals
   v
Drift Classifier
   |
   v
Calibrated Risk Score (0-100)
   |
   v
Policy Layer (allow / log / re-consent / quarantine)
```

## Features we intend to model

### Semantic change

- purpose / description drift
- parameter-description drift
- input contract drift
- output contract drift
- capability / annotation drift
- full canonical schema drift

### Structural change

- parameters added, removed, or renamed
- required-set changes
- type changes
- enum expansion / restriction
- default-value changes
- output-schema changes
- safety annotation changes
- newly introduced URLs / domains
- newly introduced sensitive-capability terms
- cross-tool references
- imperative / instruction-like language

## Model progression

We will compare progressively stronger baselines:

1. hash-only change detection
2. regex / risk-dictionary detector
3. cosine-distance threshold
4. single-snapshot semantic classifier
5. **pairwise classifier** over semantic + structural deltas
6. optional Siamese / pair encoder

The initial proposed model is a lightweight pairwise classifier over field-level embedding distances and structural delta features. This keeps inference fast and model/provider agnostic.

## Additional novelty we plan to explore

- **Drift budget / trust decay:** detect slow multi-version rug pulls where every individual update appears small.
- **Counterfactual explanations:** identify the minimum changed fields responsible for a risk decision.
- **Cross-tool shadowing graph:** detect new influence or redirection between tools.
- **Uncertainty-aware abstention:** escalate out-of-distribution or low-confidence changes for review.
- **Adversarial paraphrase hardening:** test against stealthy wording changes and unseen attack families.

## Repository roadmap

```text
mcp-driftguard/
├── src/driftguard/       # core Python package
├── tests/                # unit/integration tests
├── examples/             # benign and malicious schema-pair demos
├── data/                 # dataset manifests / generated samples
├── experiments/          # training and evaluation entry points
├── policies/             # OPA/Rego policy examples
├── docs/                 # threat model, architecture, labeling guide
└── pyproject.toml
```

## Research questions

1. Does pairwise schema-change classification reduce false positives compared with hash, regex, cosine-only, and single-snapshot classifiers?
2. Which MCP tool-definition fields contribute most to malicious drift detection?
3. How well does the detector generalize to unseen / paraphrased poisoning attacks?
4. Can legitimate capability expansion be separated from malicious permission escalation?
5. What latency / accuracy trade-off is achievable before tool invocation?

## Status

Project scaffold in progress.

## License

MIT
