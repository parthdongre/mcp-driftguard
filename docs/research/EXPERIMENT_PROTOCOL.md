# Implementation evidence and experiment handoff

Date: 2026-10-15. **[PAPER_PROTOCOL.md](../PAPER_PROTOCOL.md) remains the authoritative preregistration-style protocol.** This handoff explains implemented safeguards and remaining executable work; it does not silently redefine targets or duplicate the frozen rules.

## Correctness changes made in this iteration

| Confirmed defect/gap | Repair | Evidence |
|---|---|---|
| An intervention in a benign prefix was counted as a detected C3 trajectory and its negative delay clamped to zero. | First-intervention consent simulation now records `pre_onset_intervention_rate` and does not credit that action as post-onset attack detection. | Regression trace has score 0.9 at step 0, attack onset 2, no later signal: detection is 0 and delay undefined. |
| Policy outcomes were keyed by duplicate trace IDs, silently overwriting results. | Duplicate IDs, nonfinite/out-of-range scores, invalid onset indices and empty optimization grids are rejected. | Focused malformed-input and duplicate-outcome tests. |
| Temporal evaluator always chose the first version, ignoring the declared approved version. | Resolves exactly one matching approval, rejects duplicate version IDs/missing future observations, and measures indices relative to approval. | Mid-sequence approval changes onset from step 3 to step 1 in a controlled lineage. |
| Naive and aware timestamps could raise an unhandled TypeError or produce ambiguous cutoffs. | Require explicit timezones and normalize to UTC for comparison. | Boundary tests cover UTC/+05:30 equivalence and fail clearly on missing zones. |
| Duplicate annotator/annotation references could masquerade as independent review. | Distinct IDs and consistent independent annotators required; optional original-annotation verification checks adjudication identity/candidate references. Duplicate candidates are rejected. | Self-agreement and forged-reference regression tests. IDs alone do not prove human authorship or independence. |
| Only scalar/record bootstrap existed. | Whole-repository/server cluster and paired-cluster bootstrap preserve all records in resampled groups and recompute nonlinear statistics. | Tests exclude impossible within-group mixtures and verify paired nonlinear metric behavior. |

`trajectory_evaluation` runs the monitor through all versions and reports whether any **post-onset** alert occurs; pre-onset false alarms are separately counted. `consent_policy` models a **first intervention that halts the trace**. These are intentionally distinct estimands. A pre-onset intervention is not attack detection in either headline interpretation. Do not compare their recall columns without stating the intervention semantics.

## Cluster uncertainty API

```python
from driftguard.statistics import (
    cluster_bootstrap_confidence_interval,
    paired_cluster_bootstrap_difference,
)

ci = cluster_bootstrap_confidence_interval(
    record_outcomes, repository_ids, statistic=metric,
    bootstrap_samples=5000, seed=20260906,
)
delta = paired_cluster_bootstrap_difference(
    baseline_outcomes, driftguard_outcomes, repository_ids,
    statistic=metric, bootstrap_samples=5000, seed=20260906,
)
```

`metric` receives the complete pooled resampled records. A sampled repository is retained with every record, and repeated sampled repositories repeat those records. This targets a record-weighted pooled metric. For equal-repository performance, first compute one metric per repository and bootstrap that vector using the existing scalar utility. The paired API requires identical record alignment and uses the same cluster draws for both models. At least two groups are required; very few groups or all-success/all-failure data may produce uninformative or degenerate percentile intervals. This is a limitation to report, not proof of certainty.

## Annotation workflow boundary

The data model stores independent annotator decisions and adjudications. `adjudications_to_pair_records(..., annotations=original_annotations)` additionally verifies referenced records. Omitting `annotations` retains the legacy assertion-based import path and is not sufficient evidence of independently reviewed labels. Neither path creates human annotations. Record acquisition/extractor coverage and target counts from the canonical protocol remain unmet until authentic inputs and human work exist.

Agreement output includes the C0–C3 rater confusion matrix and unmatched-left/right counts so incomplete overlap cannot disappear in a perfect agreement number. Cohen's kappa is `null` when there are no paired annotations or both raters use only the same single class: its denominator is zero, even if raw agreement is one. Human agreement remains unmeasured until actual independent records are supplied.

## Reproduction commands

```bash
python -m pytest -q tests/test_annotation_workflow.py tests/test_consent_policy.py tests/test_trajectory_evaluation.py tests/test_temporal_split.py tests/test_cluster_statistics.py tests/test_sequential_experiments.py
PYTHONPATH=src python experiments/run_sequential_comparison.py --output artifacts/sequential_comparison.json
PYTHONPATH=src python experiments/run_temporal_strategy_benchmark.py
```

All generated sequential results are marked `paper_claim_eligible: false`. Their repository names are template identifiers, not independently acquired real MCP repositories. The isolated EWMA/multivariate implementations do not change the deterministic gateway's authorization behavior.

## Remaining publication gates

Use the existing protocol's five regimes and frozen manifests. Prioritize authentic corpus acquisition with extraction-gap accounting, two independent human reviews, external transfer with authentic baselines, then matched-threshold comparisons and ablations. Existing helper functions do not prove those evaluations occurred. Reserve untouched final sources before further feature engineering, archive label/split/model/environment hashes and raw predictions, and rerun from a clean release.

The following remain open: automatic evidence-backed paper readiness rather than self-asserted booleans; a complete frozen cross-dataset runner; actual human annotation and agreement measurements; multiclass calibration comparison; controlled execution-side attack success with canary-only local backends; and independently repeated system/resource measurements. Competitor methods are literature/feature comparisons unless a compatible, licensed implementation was run under the same declared inputs. No publication-readiness or superiority claim is made.
