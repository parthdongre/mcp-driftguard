# DriftGuard Paper Experiment Protocol

This document freezes the methodological rules for publication-grade experiments. Development benchmarks may change while engineering; paper results must follow this protocol and must not be retrospectively tuned on the final test set.

## 1. Primary paper claim

The primary claim is not raw accuracy. The target claim is:

> DriftGuard detects malicious post-approval MCP tool-definition drift, including adversarially budgeted low-and-slow rug pulls and unseen attack families, while keeping benign false positives and unnecessary user re-consent low.

A paper result is considered successful only if the final independent evaluation meets all declared constraints simultaneously.

### Primary security targets

- C3 malicious recall: **>= 95%**
- benign C0/C1 false-positive rate: **<= 3%**
- C3 precision: report with 95% confidence interval
- unseen attack-family recall: **>= 90%**, aspirational target >= 95%
- bounded low-and-slow trajectory detection rate: **>= 90%**, aspirational target >= 95%

### Primary usability targets

- report C2 recall separately from C3 recall;
- report C2->C3 false-malicious rate;
- report unnecessary re-consent per 100 benign updates;
- compare against reapprove-on-any-change;
- report mean/median detection delay for malicious trajectories.

These thresholds are research targets, not guarantees. Any paper reports the measured result even if the target is missed.

---

## 2. Dataset layers

### Layer A: Real benign/evolving MCP history

Source authentic public MCP repositories and mine historical versions statically without executing third-party code.

Required before final paper evaluation:

- >= 30 repositories for a minimum viable paper;
- target >= 50 repositories;
- target >= 500 independently labeled transitions, preferably > 1,000;
- retain repository, file lineage, commit SHA, commit timestamp, tool name, old/new definitions, and extraction method;
- exclude documentation/test fixtures from the primary corpus unless explicitly studied as a separate stratum.

Every real-history transition must be labeled by two independent annotators before adjudication.

### Layer B: Independent external attacks

Use independently authored MCP attack datasets or released artifacts where licensing permits. Candidate sources include MCPTox, MCP-AttackBench/MCP-Guard, MCP-ITP-derived cases, and other public benchmarks discovered before freeze.

Rules:

- external cases must be converted through a documented dataset-specific converter into `ExternalVersionPair`;
- original dataset identity and source record ID must be preserved;
- no external test examples may be manually rewritten after seeing DriftGuard errors;
- if an external benchmark provides only poisoned snapshots, pair each poisoned tool with the authentic/trusted source tool using a documented deterministic mapping;
- external datasets reserved for transfer tests must not contribute lexical templates to training.

### Layer C: Controlled attacks

Controlled attack transformations are used for training and mechanistic ablations, not as the sole basis of final performance claims.

Families should include:

- authority/instruction override;
- credential and secret escalation;
- hidden/default external sink introduction;
- scope broadening;
- cross-tool steering/shadowing;
- deceptive safety annotations;
- malicious defaults;
- Unicode/format-control concealment;
- implicit poisoning patterns;
- destructive capability concealed as read-only.

### Layer D: Bounded low-and-slow trajectories

A trajectory is eligible for the low-and-slow benchmark only when `analyze_bounded_trajectory` verifies:

1. every adjacent transition remains inside the declared local drift budget; and
2. approved-to-final risk/capability movement exceeds the local budget or approved capability envelope.

This prevents trivial multi-step attacks containing an obvious single-step jump.

---

## 3. Labeling protocol

Use C0/C1/C2/C3 exactly as defined in `docs/LABELING_GUIDE.md` and `docs/RESEARCH_PROBLEM_V2.md`.

Two annotators label independently. They may inspect the old definition, new definition, source diff/commit context, and repository documentation, but not model predictions.

Report:

- raw agreement;
- Cohen's kappa;
- confusion matrix between annotators;
- C2/C3 disagreement rate;
- number and reason categories for adjudicated examples.

Adjudicated labels are frozen before the final model is evaluated.

---

## 4. Evaluation regimes

Final paper tables must include multiple regimes rather than one random split.

### Regime R1: Repository-disjoint

No repository appears across train, validation, and test. This is the primary i.i.d.-like generalization regime for real MCP history.

### Regime R2: Attack-family-disjoint

One or more complete attack families are absent from training and validation, then evaluated only at test time.

### Regime R3: Cross-dataset transfer

Train without one independently authored benchmark and test on that external source.

### Regime R4: Future-version holdout

Use timestamps to evaluate later tool-definition evolution after training/tuning on earlier data. The exact cutoff is chosen before model comparison.

### Regime R5: Bounded trajectory holdout

Generate or curate attack trajectories whose adjacent transitions satisfy the frozen local drift budget. Families used for final trajectory evaluation must be distinct from the sequences used during temporal-threshold tuning.

---

## 5. Baselines

Every method receives identical frozen splits.

Required baselines:

1. hash/change-only;
2. edit/lexical distance;
3. risk keyword/regex rules;
4. full-schema cosine similarity;
5. field-aware cosine similarity;
6. single-snapshot maliciousness classifier;
7. pairwise text-only classifier;
8. pairwise structural-only classifier;
9. pairwise hybrid classifier;
10. reapprove-on-any-change policy;
11. adjacent-only anomaly threshold;
12. approved-baseline-only threshold;
13. CUSUM/sequential accumulation baseline;
14. DriftGuard full system.

Where feasible, include a strong LLM-as-judge baseline with a frozen prompt and model version.

---

## 6. Ablations

The full DriftGuard system must be rerun after removing one component at a time:

- no field separation;
- no semantic features;
- no typed structural features;
- no capability projection;
- no hard structural invariants;
- no approved baseline;
- no sequential accumulation;
- no real benign history during training;
- no hard benign negatives;
- binary C3-vs-rest instead of C0/C1/C2/C3.

Primary ablation question: which components improve unseen-family and low-and-slow detection without increasing benign FPR/re-consent burden?

---

## 7. Threshold and policy selection

The final test labels are never used to choose thresholds.

Allowed:

- train model on training partition;
- tune model hyperparameters on validation partition;
- choose decision thresholds on validation partition;
- choose sequential/CUSUM parameters on validation trajectories;
- freeze the resulting configuration;
- evaluate once on the final test partition.

Not allowed:

- inspect test-family failures, modify features, and continue calling the same set a final test;
- choose the best seed based on test performance;
- adjust the local drift budget to make a particular attack family count as low-and-slow after seeing the result.

Development challenge sets used during engineering must be explicitly labeled as development-only and excluded from the final frozen test.

---

## 8. Metrics

### Pair/classification metrics

Report:

- macro-F1 for C0/C1/C2/C3;
- per-class precision, recall, F1;
- C3 AUROC and AUPRC;
- balanced accuracy;
- benign C0/C1 FPR;
- C2->C3 false-malicious rate;
- Brier score / calibration error;
- confusion matrix.

### Temporal metrics

Report:

- trajectory detection rate;
- detection rate before final malicious step;
- mean and median detection delay after attack onset;
- benign false alarms per 100 updates;
- unnecessary re-consent per 100 benign updates;
- average versions observed before intervention;
- detection rate stratified by local drift budget and attack family.

### Systems metrics

Report:

- median/P95 inference latency;
- memory footprint;
- embedding/cache cost where applicable;
- throughput for batch schema refresh;
- storage overhead per historical snapshot.

---

## 9. Statistical reporting

Point estimates alone are insufficient.

- use bootstrap 95% confidence intervals;
- when records are clustered by repository/server, bootstrap at the repository/server level rather than assuming every transition is independent;
- use paired bootstrap differences when comparing methods on the same repositories/trajectories;
- report at least 5 random seeds for learned models unless deterministic training is demonstrated;
- report mean and standard deviation across seeds;
- publish all failed as well as successful primary-regime results.

The repository provides `bootstrap_confidence_interval` and `paired_bootstrap_difference` as the first statistical utilities.

---

## 10. Reproducibility freeze

Every final paper experiment must archive:

- Git commit SHA;
- data manifest and upstream source commit SHAs;
- annotation file hash;
- split manifest;
- attack-family holdout manifest;
- local drift budget;
- random seeds;
- model and embedding identifiers/revisions;
- selected thresholds;
- dependency lock/environment export;
- command line used to run the experiment;
- raw predictions and metrics artifact.

A result lacking this information is a development result, not a paper result.

---

## 11. Paper claim eligibility

A result may be used in the abstract/conclusion only if all are true:

- final data labels were frozen before evaluation;
- test repositories were not used for model/feature tuning;
- held-out attack families were not used for feature engineering after freeze;
- at least one independent external attack source is included;
- real benign history is represented in the test set;
- confidence intervals are reported;
- the experiment is reproducible from an archived configuration;
- the artifact marks itself `paper_claim_eligible: true` only after these checks are programmatically satisfied.

Until then, the repository must describe numerical results as controlled/development benchmarks.
