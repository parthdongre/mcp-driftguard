# Publication path and current evidence

Assessment date: 15 October 2026. This is a preparation guide, not a submission or
acceptance claim. Do not write a final results-bearing manuscript until the frozen
independent evaluation exists. The working scientific claim is a hypothesis about
consent cost at matched malicious recall, not the novelty of having a gateway.

## Venue fit

| Candidate family | Why it could fit, after the evidence exists | Verified requirements and current status |
|---|---|---|
| ACM AISec | AI/security evaluation, adversarial robustness, human oversight and a longitudinal consent benchmark | The [2026 official call](https://aisec.cc/) accepts research and benchmark papers. Benchmark submissions require a functional artifact link at submission; anonymity, ethics and an explicit generative-AI-use statement matter. The July 24, 2026 paper deadline is closed. A future edition must be checked independently. |
| IEEE ACSAC | An applied, demonstrably useful mediation system with independently measured protection and operational costs | The [2026 official call](https://www.acsac.org/2026/submissions/papers/) includes agentic systems and usable security, expects artifact evaluation/public availability or a justified exception, and requires anonymization, ethics and disclosure of LLM use. The paper deadline was May 26; October 22 is camera-ready, not a fresh submission opportunity. Future deadlines are not inferred. |

Fit is an inference from published scope. Neither venue is a realistic destination
for a prototype-only claim with no human labels. A smaller workshop study may be a
better first scientific milestone than a broad superiority claim. Full applied
security submission requires a stronger independent attack/outcome evaluation.
Resolve the proprietary-license/artifact-sharing policy with the owner before any
artifact publication. No public release or submission is made by this work.

## Evidence still needed

1. Expand usable production-source diversity beyond the current 11 repository groups;
   a pool of 30 candidates is not a 30-repository benchmark.
2. Obtain two independent human labels for eligible transitions and adjudicate
   disagreements. The current 494 candidates have zero human labels.
3. Audit source extraction against authentic runtime definitions/source context;
   wrappers, deleted files and reconstructed constraints limit coverage.
4. Reserve an independently authored external attack source and unseen families;
   preserve licensing, original IDs and authentic trusted pair mappings.
5. Freeze split/annotation/model/threshold hashes before final evaluation. Run the
   complete baseline/ablation matrix with repository-cluster uncertainty and seeds.
6. Compare recall, benign false alarms, C2/C3 errors, consent cost and detection
   delay together. Do not treat a pre-onset false block as attack detection.
7. Measure actual gateway and native app costs/behavior on macOS/Windows/Linux.
   Current generated-fixture Python costs and browser checks are narrower evidence.
8. Demonstrate attack outcomes in an authorized controlled testbed, with both
   routed and bypass scope explicit. Descriptor equality cannot prove handler safety.

## Manuscript structure after freeze

Use the verified literature matrix and threat model, then describe the paired and
sequential task, capability representation, policy, dataset, independent annotation,
frozen evaluation and uncertainty. Main tables must be generated from archived raw
predictions. Include failed constraints, sources of bias, label uncertainty,
extraction limits, adaptive-test contamination risks, runtime TOCTOU limits, ethics
and exact reproduction commands. Current controlled experiments belong in an
engineering appendix and cannot substitute for the independent main evaluation.

No final abstract, confidence interval, acceptance probability or headline accuracy
is filled from synthetic development scores.
