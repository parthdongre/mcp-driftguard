# Algorithm program and deployment decisions

Date: 2026-10-15. Mathematical forms below describe the candidate under discussion, not a claim that every cited paper has been reproduced. Literature and publication status are verified in [SYSTEMATIC_LITERATURE_REVIEW.md](SYSTEMATIC_LITERATURE_REVIEW.md). Final split, threshold and label rules remain in [PAPER_PROTOCOL.md](../PAPER_PROTOCOL.md).

## Decision boundary

Use deterministic identity, approval and policy enforcement as the execution authority. Learned or sequential detectors can add evidence and trigger review; a missing model must not create an allow decision. Tool-definition features describe inferred/claimed capabilities, not proven effects of an arbitrary backend. Advanced models remain research options until independent evaluation justifies their latency and complexity.

Let `x_t` be a field-aware drift vector, `r_t` a bounded scalar security score, `T_0` the approved definition and `T_t` the current definition. Compare adjacent changes `T_(t-1) -> T_t` separately from cumulative change `T_0 -> T_t`; adjacent-only small changes can hide a large endpoint shift. Do not overwrite the consent baseline on every benign observation.

## Semantic and structured models

| Candidate | Mathematical object and assumptions | Cost/training requirements | Recommendation and failure mode |
|---|---|---|---|
| Canonical hash / typed structural delta | Exact content identity and schema facts; no semantic inference. | Linear in descriptor bytes; no training. | Always retain as baseline and integrity evidence. It detects change, not intent; arbitrary JSON Schema keyword coverage must be tested explicitly. |
| Field-wise lexical or cosine drift | `1 - cos(e_old,f, e_new,f)` per field `f`; aggregate by max/weighted head. | Embedding cost dominates; cached dot products O(Fd), storage O(Fd) per snapshot. | Strong transparent baseline. Long-field truncation, model revision, Unicode and field omission can hide changes. Lexical risk scores are not probabilities. |
| E5/BGE/SentenceTransformers | Frozen bi-encoder representations or contrastive domain tuning; correct model-specific prefixes and revision pins. | Offline weights; batched encoding and cache; contrastive tuning needs independent positives/hard negatives. | Prefer small local encoder before larger models. Security-specific tuning may learn generator templates. Test external transfer and repository/family holdouts. |
| Siamese / cross-encoder pair model | Shared encoders plus deltas, or joint attention on old/new token sequence; predicts change class. | Siamese permits snapshot caching; cross-encoder performs joint inference per pair and usually costs more. Needs many independently labeled pairs. | Candidate when real pair data exists. Token truncation and training/test lineage leakage must be reported. No neural improvement is established in this branch. |
| Logistic regression | Softmax/binary `p(y|x)` from regularized linear features. | O(dK) inference; sparse text/numeric features; scale numeric inputs inside the train-only pipeline. | Practical interpretable baseline already represented in the engine. Calibration and threshold selection require separate data discipline. |
| XGBoost / LightGBM | Additive decision-tree score with interactions, followed by multiclass probability/calibration layer. | Rough inference O(number of trees × depth), optional native dependencies and training search. | Compare with linear model on identical records. Do not add both frameworks without evidence. Existing XGBoost experiment requires its optional dependency; absence is a skipped comparison, not a benchmark success. |
| Four-class vs multitask | Flat C0–C3 softmax versus two heads: maliciousness and consent necessity. | Class-balanced reviewed examples, cost matrix, calibrated outputs. | Explicitly measure C2 mistaken for C3 and C3 missed as C2. Consent necessity and maliciousness are related but distinct decisions. Model uncertainty should trigger review. |
| Frozen LLM judge | Version-pinned prompt/model reads untrusted old/new descriptors as data and emits fixed schema. | High and variable latency; external service cost/privacy unless local; repeat nondeterministic runs. | Optional comparative baseline; explicit cloud opt-in. Prompt injection against the judge must be evaluated. It cannot authorize bypassing deterministic restrictions. |

## Sequential candidates

| Candidate | Formulation and assumptions | Per-update cost/state | Implementation/evidence and decision |
|---|---|---|---|
| Approved baseline only | `b_t = risk(T_0,T_t)`; no learned temporal model. | Feature extraction plus O(1) scalar state, excluding snapshots. | Existing baseline; catches endpoint shifts even when local increments are small. False alarms may grow as benign maintenance accumulates. |
| Existing scalar CUSUM-style | `S_t = max(0, lambda*S_(t-1)+r_t-k)`; empirical allowance `k` and decay `lambda`. | O(1) after extracting features. | Keep as default research baseline. This is a decayed heuristic when `lambda<1`, not a likelihood-ratio CUSUM with a proved ARL. |
| EWMA | `z_t = alpha*r_t+(1-alpha)*z_(t-1)`, `z_0=mu_0`; alert on `max(0,z_t-mu_0)>=h`. | O(1) work/storage. | Implemented in `sequential_experiments.EWMAChart`. Transparent smoothed risk; sustained drift increases state, benign recovery decreases it. `alpha` controls delay/smoothing; thresholds empirically calibrated. |
| Multivariate max CUSUM | `S_j,t=max(0,lambda*S_j,t-1+(x_j,t-mu_j)/sigma_j-k)`; alert on `max_j S_j,t>=h`. | O(d) work/storage. | Implemented in `sequential_experiments.MultivariateCUSUM`; diagonal scaling, no covariance model. Multiple coordinates increase false-alarm opportunities; tune jointly on benign validation. Not kernel CUSUM. |
| Covariance-aware MCUSUM | Whiten drift using a train-only covariance estimate, then accumulate a vector chart. | Dense O(d²) updates plus O(d²) covariance; estimation needs sufficient null data. | Defer until heterogeneous reference data exists. Correlated sparse signals and singular covariance demand shrinkage and stratification. |
| BOCPD | Recursively maintain `P(run_length_t | x_1:t)` with hazard and predictive distribution. | Exact run-state count grows with t; bounded/pruned variants trade precision for cost. | Experimental candidate for abrupt regime shifts. Hazard/model misspecification and adversarial dependence undermine posterior interpretation; report pruning and missing-data rules. |
| Kernel / MMD CUSUM | Compare reference and rolling observations in an RKHS across candidate change locations. | Naive rolling MMD can cost O(W²) kernel work; recursive bounded-window methods reduce update costs for fixed configuration. | Candidate for nonlinear joint drift. Reproduce Wei/Xie faithfully before using its name or ARL approximations. Include bandwidth/window selection and low-memory baselines. |
| Conditional CTM / e-process | Accumulate a valid nonnegative test process against a fixed null reference; threshold roughly `1/alpha` only when the e-process assumptions hold. | Depends on nonconformity, reference size and betting construction. | Research candidate. Tool versions may be serially dependent, repository-specific and adaptively selected; naive conformal ranks/products do not yield an automatic guarantee. Freeze reference and diagnose dependence before discussing guarantees. |
| HMM / sequence encoder | Latent security-state transition model / learned sequence representation. | HMM O(K²) update for K states; sequence encoder dependent on history/tokens. | Defer: current short templated trajectories cannot identify transition dynamics or justify deep sequence training. |

The approved baseline remains available even in the sequential research comparison. An experiment that disables C2 capability information for one baseline must identify that change as an ablation, not a fair comparison of maliciousness memory.

## Typed graphs and uncertainty

Reachability solves the concrete question whether a new capability edge creates a path from a sensitive resource to an external destination. `capability_graph.py` implements explicit edge addition/removal and breadth-first witness search, returning one path per sensitive source/external destination. The traversal is O(S(V+E)) for S sensitive sources; deterministic adjacency sorting and materializing all witness paths add their own costs, so total runtime is not simply the traversal bound. In particular, many long witnesses can require quadratic output space. Incremental graph mutation is implemented; cached incremental reachability is not claimed.

Every edge distinguishes `descriptor_inferred`, `runtime_observed`, and `human_reviewed` evidence and retains provenance. These are evidence categories rather than levels that automatically certify actual permissions: descriptor text is an untrusted claim, an observation is bounded to its recorded context, and human review is a decision supported by its stated evidence. A path is a connection in this supplied model, not proof that a server has or will exercise a capability. The module is isolated from gateway authorization.

Weighted shortest paths are meaningful only after defining defensible edge costs. Dijkstra requires nonnegative costs; its inclusion alone adds no security value. Graph embeddings/GNNs require labeled graph examples and must outperform typed reachability with inspectable evidence. Neither Dijkstra nor a GNN is justified by the current corpus.

Calibration compares Brier/ECE and reliability curves on held-out data. Temperature scaling uses a small parametric transform; isotonic regression is flexible but needs more calibration data. Keep calibration fitting separate from the frozen test and record whether validation is reused for policy selection. Selective prediction reports risk versus coverage; uncertainty or OOD should require review. Counterfactual explanations must distinguish a demonstrated decision change from a guarantee of safety.

## Actual controlled experiment

Run from the repository root:

```bash
PYTHONPATH=src python experiments/run_sequential_comparison.py --output artifacts/sequential_comparison.json
```

The runner compares adjacent scalar risk, EWMA, and standardized multivariate CUSUM on the existing deterministic synthetic trajectory split: two validation repository templates and two test templates. Null means/scales and thresholds use benign validation observations only. It archives per-step raw scores, first/pre/post-onset alerts, repository assignments, Python version, source hashes, commit and dirty state. The threshold rule is fixed as strictly above the maximum benign validation score. No test labels tune it.

This is a plumbing comparison with very little data. It establishes that methods run and serialize interpretable output, including failures; it does not establish superiority, real-world attack prevention, probability calibration, or a distribution-free guarantee. Do not promote it to paper evidence. The output must be rerun after feature-engine changes because its scores depend on them.
