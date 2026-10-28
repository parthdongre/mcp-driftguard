# Source map at baseline 9fcab36176279d77c4dd7f1950d47e4991697cf7

Generated from the baseline Git tree and AST, with measured baseline statement coverage. New files are described in ARCHITECTURE.md.

| File | Public definitions | Internal dependencies | Statement coverage |
|---|---|---|---|
| `examples/low_and_slow_demo.py` | `tool`, `snapshot`, `main` |  | not instrumented |
| `experiments/build_public_corpus.py` | `main` |  | not instrumented |
| `experiments/import_external_benchmark.py` | `main` |  | not instrumented |
| `experiments/mine_history.py` | `main` |  | not instrumented |
| `experiments/run_attack_family_holdout.py` | `main` |  | not instrumented |
| `experiments/run_bounded_drift_audit.py` | `main` |  | not instrumented |
| `experiments/run_learned_family_holdout.py` | `main` |  | not instrumented |
| `experiments/run_pair_baselines.py` | `main` |  | not instrumented |
| `experiments/run_poisoning_ablation_suite.py` | `main` |  | not instrumented |
| `experiments/run_poisoning_benchmark.py` | `main` |  | not instrumented |
| `experiments/run_repeated_seed_poisoning.py` | `main` |  | not instrumented |
| `experiments/run_semantic_baselines.py` | `main` |  | not instrumented |
| `experiments/run_temporal_baseline.py` | `main` |  | not instrumented |
| `experiments/run_temporal_strategy_benchmark.py` | `main` |  | not instrumented |
| `experiments/run_xgboost_family_holdout.py` | `main` |  | not instrumented |
| `experiments/score_annotations.py` | `main` |  | not instrumented |
| `src/driftguard/__init__.py` |  | `annotation_workflow`, `canonicalize`, `corpus`, `corpus_discovery`, `diff`, `evaluation`, `features`, `history`, `labeling`, `learning`, `models`, `mutations`, `source_extractors`, `splits`, `temporal`, `thresholds`, `trajectory_evaluation` | 100.0% |
| `src/driftguard/annotation_workflow.py` | `HumanAnnotation`, `AdjudicationRecord`, `AnnotationAgreement`, `read_human_annotations_jsonl`, `read_adjudications_jsonl`, `annotation_agreement`, `disagreement_candidate_ids`, `adjudications_to_pair_records` | `dataset`, `labeling`, `models` | 80.4% |
| `src/driftguard/attack_family_benchmark.py` | `AttackFamilyFold`, `StrictFamilyMetrics`, `FamilyStrategyEvaluation`, `controlled_attack_family_folds`, `validate_attack_family_fold`, `evaluate_attack_family_holdout`, `bounded_audits` | `bounded_drift`, `consent_policy`, `dataset`, `models`, `mutations`, `temporal`, `trajectory_benchmark` | 94.5% |
| `src/driftguard/attack_family_stateful.py` | `StatefulFamilyStrategyEvaluation`, `evaluate_stateful_attack_family_holdout` | `attack_family_benchmark`, `stateful_policy`, `temporal`, `trajectory_benchmark` | 100.0% |
| `src/driftguard/baselines.py` | `hash_only_changed`, `rule_baseline` | `models` | 74.4% |
| `src/driftguard/bounded_drift.py` | `LocalDriftBudget`, `DriftStepReport`, `BoundedTrajectoryReport`, `analyze_step`, `analyze_bounded_trajectory`, `is_budgeted_rug_pull` | `canonicalize`, `dataset`, `diff`, `features`, `temporal` | 93.5% |
| `src/driftguard/calibration.py` | `CalibrationMetrics`, `binary_brier_score`, `binary_calibration_metrics` |  | 92.1% |
| `src/driftguard/canonicalize.py` | `canonicalize_tool`, `canonical_json`, `schema_hash`, `make_snapshot` | `models` | 97.2% |
| `src/driftguard/capabilities.py` | `extract_capability_profile`, `capability_delta`, `capability_escalation_score` | `models` | 100.0% |
| `src/driftguard/consent_policy.py` | `PolicyAction`, `SequenceRiskTrace`, `ConsentPolicyThresholds`, `ConsentPolicyMetrics`, `PolicySelection`, `evaluate_consent_policy`, `select_consent_policy`, `consent_security_pareto_frontier` | `models` | 92.7% |
| `src/driftguard/corpus.py` | `historical_versions_to_candidates` | `canonicalize`, `dataset`, `diff`, `history` | 82.6% |
| `src/driftguard/corpus_discovery.py` | `SourceDiscovery`, `discover_mcp_sources`, `extractable_paths_by_kind` | `history`, `source_extractors` | 80.6% |
| `src/driftguard/dataset.py` | `AnnotationCandidate`, `PairDatasetRecord`, `TrajectoryStep`, `TrajectoryDatasetRecord`, `write_jsonl`, `read_pair_jsonl`, `read_candidate_jsonl`, `read_trajectory_jsonl` | `models` | 80.2% |
| `src/driftguard/diff.py` | `structural_delta`, `build_delta` | `models` | 95.5% |
| `src/driftguard/embeddings.py` | `EmbeddingProvider`, `EmbeddingCache`, `SentenceTransformerProvider`, `cosine_distance`, `view_embedding_drift` | `models` | 75.3% |
| `src/driftguard/evaluation.py` | `BinaryMetrics`, `BaselineResult`, `binary_metrics`, `hash_alert`, `rule_alert`, `lexical_alert`, `semantic_drift_scores`, `full_schema_semantic_alert`, `field_semantic_alert`, `evaluate_binary_baseline`, `evaluate_standard_baselines`, `evaluate_semantic_baselines`, `multiclass_metrics` | `baselines`, `canonicalize`, `dataset`, `diff`, `embeddings`, `features`, `models` | 88.4% |
| `src/driftguard/external_benchmarks.py` | `ExternalVersionPair`, `normalize_external_pair`, `read_external_jsonl`, `import_external_jsonl`, `validate_external_independence` | `dataset`, `models` | 56.0% |
| `src/driftguard/features.py` | `extract_pair_features`, `flatten_numeric_features` | `capabilities`, `embeddings`, `models`, `views` | 97.1% |
| `src/driftguard/history.py` | `HistoricalToolVersion`, `extract_tools_from_json`, `parse_tool_manifest`, `GitManifestHistoryMiner`, `GitSourceHistoryMiner`, `adjacent_version_pairs` | `canonicalize`, `source_extractors` | 92.6% |
| `src/driftguard/hybrid_detector.py` | `structural_guard_probability`, `HybridPoisoningDetector` | `dataset`, `models`, `poisoning` | 0.0% |
| `src/driftguard/labeling.py` | `EvidenceTag`, `LabelDecision`, `recommended_label`, `inter_annotator_agreement` | `models` | 81.4% |
| `src/driftguard/learned_family_benchmark.py` | `LearnedFoldSplit`, `LearnedTemporalConfig`, `LearnedPreparedTrajectory`, `LearnedTrajectoryOutcome`, `PairClassificationMetrics`, `LearnedFamilyStrategyEvaluation`, `LearnedFamilyEvaluation`, `trajectory_training_pairs`, `trajectory_adjacent_pairs`, `split_attack_family_fold`, `prepare_learned_trajectory`, `evaluate_prepared_policy`, `select_learned_policy`, `pair_classification_metrics`, `evaluate_learned_family_fold`, `evaluation_asdict` | `consent_policy`, `dataset`, `learning`, `models`, `stateful_policy`, `trajectory_benchmark` | 95.0% |
| `src/driftguard/learning.py` | `GroupedSplit`, `repository_group_split`, `record_features`, `LogisticPairClassifier` | `canonicalize`, `dataset`, `diff`, `embeddings`, `features`, `models` | 86.3% |
| `src/driftguard/mcptox_adapter.py` | `MCPToxAttack`, `parse_mcptox_response_all`, `pair_mcptox_with_trusted_baselines` | `dataset`, `models` | 92.5% |
| `src/driftguard/models.py` | `ChangeClass`, `ToolSnapshot`, `StructuralDelta`, `ToolDelta`, `SemanticViews`, `CapabilityProfile`, `CapabilityDelta`, `PairFeatures`, `TemporalAssessment`, `RiskAssessment` |  | 100.0% |
| `src/driftguard/mutations.py` | `Mutation`, `benign_clarification`, `add_optional_format_parameter`, `add_required_api_token`, `add_external_upload`, `add_cross_tool_steering`, `add_policy_override`, `broaden_scope`, `add_mutating_behavior`, `apply_named_mutation`, `build_low_and_slow_trajectory` | `dataset`, `models` | 81.5% |
| `src/driftguard/paper_readiness.py` | `PaperExperimentEvidence`, `PaperReadinessAssessment`, `assess_paper_readiness` |  | 100.0% |
| `src/driftguard/poisoning.py` | `transition_text`, `poisoning_security_features`, `PoisoningDetector` | `canonicalize`, `dataset`, `diff`, `features`, `models`, `structural_security` | 92.0% |
| `src/driftguard/poisoning_benchmark.py` | `build_development_poisoning_benchmark` | `dataset`, `models` | 98.5% |
| `src/driftguard/poisoning_challenges.py` | `build_structural_challenge_records` | `dataset`, `models` | 96.2% |
| `src/driftguard/reproducibility.py` | `FileEvidence`, `ExperimentManifest`, `sha256_file`, `build_experiment_manifest`, `write_experiment_manifest`, `verify_experiment_manifest` |  | 0.0% |
| `src/driftguard/research_baselines.py` | `SnapshotPoisoningBaseline`, `PairAblationBaseline` | `dataset`, `models`, `poisoning` | 91.7% |
| `src/driftguard/review_demo.py` | `ReviewStep`, `run_midsem_review_demo`, `render_midsem_report`, `render_midsem_json`, `main` | `canonicalize`, `temporal` | 98.1% |
| `src/driftguard/source_extractors.py` | `SourceToolExtractor`, `PythonDecoratorToolExtractor`, `TypeScriptRegisterToolExtractor` |  | 78.5% |
| `src/driftguard/splits.py` | `SplitManifest`, `TemporalCutoffManifest`, `build_split_manifest`, `apply_split_manifest`, `apply_temporal_cutoff_manifest`, `held_out_family_test_records`, `write_split_manifest`, `read_split_manifest` | `dataset`, `learning` | 86.3% |
| `src/driftguard/stateful_policy.py` | `PolicyActionEvent`, `StatefulTrajectoryOutcome`, `StatefulPolicyMetrics`, `StatefulPolicySelection`, `PreparedTrajectory`, `prepare_stateful_trajectory`, `simulate_stateful_policy`, `evaluate_stateful_policy`, `select_stateful_policy` | `canonicalize`, `consent_policy`, `dataset`, `diff`, `features`, `models`, `temporal`, `trajectory_benchmark` | 94.1% |
| `src/driftguard/statistics.py` | `ConfidenceInterval`, `bootstrap_confidence_interval`, `paired_bootstrap_difference` |  | 84.4% |
| `src/driftguard/structural_security.py` | `structural_poisoning_features` | `dataset`, `models` | 93.8% |
| `src/driftguard/temporal.py` | `TemporalConfig`, `research_risk_signal`, `SequentialDriftMonitor` | `diff`, `features`, `models` | 94.4% |
| `src/driftguard/thresholds.py` | `ThresholdSelection`, `tune_binary_threshold`, `tune_margin_threshold` | `evaluation`, `models` | 91.4% |
| `src/driftguard/trajectory_benchmark.py` | `TemporalStrategy`, `StrategyEvaluation`, `trajectory_signal_trace`, `compare_temporal_strategies`, `controlled_temporal_split` | `canonicalize`, `consent_policy`, `dataset`, `diff`, `features`, `models`, `mutations`, `temporal` | 92.2% |
| `src/driftguard/trajectory_evaluation.py` | `TrajectoryRun`, `TrajectoryMetrics`, `evaluate_trajectory`, `aggregate_trajectory_metrics`, `evaluate_trajectories` | `canonicalize`, `dataset`, `models`, `temporal` | 93.1% |
| `src/driftguard/tree_learning.py` | `XGBoostPairClassifier` | `dataset`, `embeddings`, `learning` | 0.0% |
| `src/driftguard/views.py` | `extract_semantic_views` | `models` | 94.4% |
| `src/driftguard/xgboost_family_benchmark.py` | `evaluate_xgboost_family_fold` | `attack_family_benchmark`, `learned_family_benchmark`, `trajectory_benchmark`, `tree_learning` | 0.0% |
| `tests/test_annotation_workflow.py` | `annotation`, `candidate`, `test_annotation_agreement_reports_c2_c3_boundary_disagreement`, `test_perfect_annotation_agreement_has_kappa_one`, `test_adjudication_builds_reviewed_real_history_pair` |  | not instrumented |
| `tests/test_attack_family_benchmark.py` | `test_attack_family_folds_are_repository_and_family_disjoint`, `test_held_out_c3_trajectories_are_genuinely_bounded`, `test_family_holdout_evaluates_every_temporal_strategy`, `test_stateful_policy_resets_after_c2_reconsent`, `test_stateful_family_holdout_uses_validation_only_threshold_selection` |  | not instrumented |
| `tests/test_calibration.py` | `test_perfect_probabilities_have_zero_brier`, `test_calibration_metrics_detect_confident_error`, `test_calibration_rejects_invalid_probability` |  | not instrumented |
| `tests/test_consent_policy.py` | `test_consent_policy_separates_benign_c2_and_attacks`, `test_policy_selection_uses_security_constraints`, `test_pareto_frontier_contains_only_non_dominated_points` |  | not instrumented |
| `tests/test_core.py` | `test_canonicalization_ignores_key_order_and_description_whitespace`, `test_canonicalization_preserves_literal_whitespace`, `test_canonicalization_normalizes_set_like_schema_arrays`, `test_structural_delta_detects_new_sensitive_required_parameter`, `test_cross_tool_reference_does_not_cross_schema_field_boundaries`, `test_cross_tool_reference_ignores_prose_stopwords_but_keeps_explicit_name`, `test_identical_definition_is_c0` |  | not instrumented |
| `tests/test_corpus.py` | `tool`, `version`, `test_history_candidates_remain_unlabeled_and_include_diff_facts`, `test_candidate_id_is_deterministic` |  | not instrumented |
| `tests/test_corpus_discovery.py` | `test_discovery_finds_extractable_python_typescript_and_json`, `test_discovery_finds_bare_nested_python_tool_decorator`, `test_discovery_reports_unsupported_python_registration_pattern`, `test_discovery_ignores_vendor_directories` |  | not instrumented |
| `tests/test_dataset_pipeline.py` | `base_tool`, `pair`, `test_labeling_framework_preserves_reconsent_boundary`, `test_controlled_mutations_remain_schema_shaped`, `test_low_and_slow_fixture_accumulates_capabilities`, `test_binary_metrics_are_reproducible`, `test_standard_baselines_share_same_records` |  | not instrumented |
| `tests/test_history.py` | `manifest`, `initialize_repo`, `commit`, `test_recursive_manifest_parser_finds_tool_definitions`, `test_git_history_miner_extracts_changed_versions`, `test_git_history_miner_follows_file_renames_without_breaking_lineage` |  | not instrumented |
| `tests/test_learned_family_benchmark.py` | `test_learned_fold_has_three_repository_disjoint_partitions`, `test_training_pairs_cover_all_four_change_classes`, `test_learned_family_benchmark_runs_without_repository_or_family_leakage` |  | not instrumented |
| `tests/test_learning.py` | `tool`, `record`, `test_repository_split_never_leaks_a_repository_between_partitions`, `test_record_features_exports_named_pairwise_security_features`, `test_logistic_pair_classifier_fits_all_four_classes_and_assesses` |  | not instrumented |
| `tests/test_mcptox_adapter.py` | `test_parse_mcptox_keeps_upstream_attack_metadata`, `test_mcptox_pairing_refuses_to_invent_missing_baseline`, `test_mcptox_pairing_uses_authentic_baseline_shape` |  | not instrumented |
| `tests/test_paper_readiness.py` | `test_development_result_is_not_paper_eligible`, `test_reused_development_test_is_disqualifying`, `test_complete_independent_experiment_can_be_claim_eligible` |  | not instrumented |
| `tests/test_paper_research.py` | `test_bounded_step_reports_structural_budget_violation`, `test_bounded_trajectory_compares_local_and_approved_endpoint`, `test_external_pair_keeps_independent_provenance`, `test_bootstrap_interval_is_reproducible_and_contains_mean`, `test_paired_bootstrap_reports_positive_improvement` |  | not instrumented |
| `tests/test_poisoning.py` | `test_security_features_separate_sensitive_existing_state_from_new_exfiltration`, `test_authority_override_feature_uses_relational_context_not_policy_keywords`, `test_detector_fits_repository_disjoint_benchmark_and_scores_poisoning_higher`, `test_held_out_authority_family_is_not_present_in_training_partition`, `test_unicode_concealment_adds_format_control_feature` |  | not instrumented |
| `tests/test_research_baselines.py` | `test_snapshot_baseline_runs_end_to_end`, `test_pair_ablation_baselines_run_end_to_end` |  | not instrumented |
| `tests/test_research_core.py` | `tool`, `snap`, `test_field_aware_views_keep_contract_separate_from_purpose`, `test_capability_delta_surfaces_external_disclosure_and_credentials`, `test_pair_features_are_stable_numeric_inputs_for_ml`, `test_sequential_monitor_can_accumulate_subthreshold_drift`, `test_reapproval_resets_temporal_state`, `test_dataset_records_expose_repository_level_leakage_group`, `TinyEmbeddingProvider`, `test_field_aware_embedding_drift_and_cache` |  | not instrumented |
| `tests/test_review_demo.py` | `test_midsem_demo_detects_accumulated_low_and_slow_drift`, `test_midsem_report_explains_baseline_and_policy_action`, `test_midsem_json_is_machine_readable_and_keeps_reviewer_evidence`, `test_cli_json_mode_prints_the_same_evidence` |  | not instrumented |
| `tests/test_semantic_baselines.py` | `TokenEmbeddingProvider`, `tool`, `pair`, `test_semantic_scores_include_all_field_views`, `test_semantic_baselines_run_on_identical_records` |  | not instrumented |
| `tests/test_source_extractors.py` | `test_python_decorator_extractor_builds_static_schema`, `test_python_extractor_skips_context_parameters`, `test_python_extractor_resolves_literal_module_name_binding`, `test_python_extractor_unwraps_annotated_and_field_description`, `test_source_history_miner_tracks_decorator_changes` |  | not instrumented |
| `tests/test_splits.py` | `tool`, `record`, `test_manifest_is_deterministic_and_repository_disjoint`, `test_manifest_rejects_overlapping_repositories`, `test_held_out_family_never_enters_training`, `test_strict_manifest_rejects_unassigned_repository` |  | not instrumented |
| `tests/test_structural_security.py` | `test_external_default_distinguishes_hidden_sink_from_user_supplied_destination`, `test_safety_hint_contradiction_distinguishes_deception_from_declared_mutation`, `test_documentation_url_does_not_look_like_an_execution_sink_default` |  | not instrumented |
| `tests/test_temporal_split.py` | `test_temporal_cutoff_creates_future_holdout` |  | not instrumented |
| `tests/test_thresholds.py` | `test_threshold_selection_uses_validation_scores_deterministically`, `test_threshold_tie_break_prefers_lower_false_positive_rate`, `test_threshold_selection_can_optimize_malicious_only_view`, `test_margin_threshold_uses_midpoint_of_validation_separation_gap`, `test_margin_threshold_falls_back_when_validation_classes_overlap` |  | not instrumented |
| `tests/test_trajectory_benchmark.py` | `test_controlled_temporal_split_is_repository_disjoint_and_balanced`, `test_sequential_trace_exposes_cumulative_bounded_drift`, `test_strategy_thresholds_are_selected_on_validation_then_applied_to_test` |  | not instrumented |
| `tests/test_trajectory_evaluation.py` | `tool`, `test_trajectory_evaluator_tracks_onset_detection_and_early_alerts`, `test_aggregate_trajectory_metrics_reports_detection_delay` |  | not instrumented |
| `tests/test_typescript_extractor.py` | `test_typescript_register_tool_extractor_reads_literal_zod_schema`, `test_typescript_extractor_skips_dynamic_tool_names`, `test_typescript_source_history_mining` |  | not instrumented |
| `tests/test_xgboost_family_benchmark.py` | `test_xgboost_family_holdout_smoke` |  | not instrumented |
