from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any

from .consent_policy import ConsentPolicyThresholds, PolicyAction
from .dataset import PairDatasetRecord, TrajectoryDatasetRecord
from .learning import LogisticPairClassifier
from .models import ChangeClass
from .stateful_policy import PolicyActionEvent, StatefulPolicyMetrics, StatefulPolicySelection
from .trajectory_benchmark import TemporalStrategy

_CLASS_PRIORITY = {
    ChangeClass.NO_MEANINGFUL_CHANGE: 0,
    ChangeClass.BENIGN_MAINTENANCE: 1,
    ChangeClass.CAPABILITY_EXPANSION: 2,
    ChangeClass.MALICIOUS_DRIFT: 3,
}


@dataclass(frozen=True)
class LearnedFoldSplit:
    held_out_family: str
    train: tuple[TrajectoryDatasetRecord, ...]
    policy_validation: tuple[TrajectoryDatasetRecord, ...]
    test: tuple[TrajectoryDatasetRecord, ...]


@dataclass(frozen=True)
class LearnedTemporalConfig:
    reference_probability: float = 0.08
    memory_decay: float = 0.98


@dataclass(frozen=True)
class LearnedPreparedTrajectory:
    trace_id: str
    final_label: ChangeClass
    attack_onset: int | None
    version_ids: tuple[str, ...]
    pair_probabilities: dict[tuple[int, int], dict[str, float]]


@dataclass(frozen=True)
class LearnedTrajectoryOutcome:
    trace_id: str
    final_label: ChangeClass
    attack_onset: int | None
    events: tuple[PolicyActionEvent, ...]
    observations_seen: int


@dataclass(frozen=True)
class PairClassificationMetrics:
    records: int
    macro_f1: float
    malicious_auroc: float | None
    per_class_recall: dict[str, float]
    confusion_matrix: dict[str, dict[str, int]]


@dataclass(frozen=True)
class LearnedFamilyStrategyEvaluation:
    held_out_family: str
    strategy: TemporalStrategy
    selection: StatefulPolicySelection
    policy_validation_metrics: StatefulPolicyMetrics
    test_metrics: StatefulPolicyMetrics


@dataclass(frozen=True)
class LearnedFamilyEvaluation:
    held_out_family: str
    train_repositories: tuple[str, ...]
    policy_validation_repositories: tuple[str, ...]
    test_repositories: tuple[str, ...]
    pair_metrics: PairClassificationMetrics
    strategies: tuple[LearnedFamilyStrategyEvaluation, ...]


def _attack_onset(trajectory: TrajectoryDatasetRecord) -> int | None:
    approved_index = next(
        (
            index
            for index, step in enumerate(trajectory.steps)
            if step.version_id == trajectory.approved_version_id
        ),
        None,
    )
    if approved_index is None:
        raise ValueError(
            f"Approved version {trajectory.approved_version_id!r} missing from "
            f"trajectory {trajectory.trajectory_id!r}"
        )
    if trajectory.final_label is not ChangeClass.MALICIOUS_DRIFT:
        return None
    for absolute_index, step in enumerate(
        trajectory.steps[approved_index + 1 :], start=approved_index + 1
    ):
        if step.attack_family or step.transition_label is ChangeClass.MALICIOUS_DRIFT:
            return absolute_index - approved_index - 1
    return None


def _interval_label(
    trajectory: TrajectoryDatasetRecord,
    old_index: int,
    new_index: int,
) -> ChangeClass:
    if not 0 <= old_index < new_index < len(trajectory.steps):
        raise ValueError("Pair indices must satisfy 0 <= old < new < len(steps)")
    labels = [
        step.transition_label or ChangeClass.NO_MEANINGFUL_CHANGE
        for step in trajectory.steps[old_index + 1 : new_index + 1]
    ]
    return max(labels, key=lambda label: _CLASS_PRIORITY[label])


def _interval_attack_family(
    trajectory: TrajectoryDatasetRecord,
    old_index: int,
    new_index: int,
) -> str | None:
    families = {
        step.attack_family
        for step in trajectory.steps[old_index + 1 : new_index + 1]
        if step.attack_family is not None
    }
    if not families:
        return None
    if len(families) > 1:
        return "+".join(sorted(families))
    return next(iter(families))


def _pair_record(
    trajectory: TrajectoryDatasetRecord,
    old_index: int,
    new_index: int,
    *,
    label: ChangeClass | None = None,
) -> PairDatasetRecord:
    resolved = label or _interval_label(trajectory, old_index, new_index)
    return PairDatasetRecord(
        record_id=f"{trajectory.trajectory_id}:{old_index}->{new_index}",
        repository_id=trajectory.repository_id,
        server_id=trajectory.server_id,
        tool_name=trajectory.tool_name,
        old_tool=trajectory.steps[old_index].tool,
        new_tool=trajectory.steps[new_index].tool,
        label=resolved,
        provenance=(
            "synthetic_attack"
            if resolved is ChangeClass.MALICIOUS_DRIFT
            else "controlled_benign"
        ),
        attack_family=_interval_attack_family(trajectory, old_index, new_index),
        old_version_id=trajectory.steps[old_index].version_id,
        new_version_id=trajectory.steps[new_index].version_id,
        notes="Controlled trajectory-derived pair for development-only family holdout.",
    )


def trajectory_training_pairs(
    trajectory: TrajectoryDatasetRecord,
) -> list[PairDatasetRecord]:
    """Generate all ordered version pairs plus one unchanged C0 anchor.

    All-pair training mirrors the operational setting in which the current definition can
    be compared to any previously re-consented baseline, not just its immediate predecessor.
    """

    records = [
        _pair_record(trajectory, old_index, new_index)
        for old_index in range(len(trajectory.steps) - 1)
        for new_index in range(old_index + 1, len(trajectory.steps))
    ]
    base = trajectory.steps[0]
    records.append(
        PairDatasetRecord(
            record_id=f"{trajectory.trajectory_id}:identity",
            repository_id=trajectory.repository_id,
            server_id=trajectory.server_id,
            tool_name=trajectory.tool_name,
            old_tool=base.tool,
            new_tool=base.tool,
            label=ChangeClass.NO_MEANINGFUL_CHANGE,
            provenance="controlled_benign",
            old_version_id=base.version_id,
            new_version_id=base.version_id,
            notes="Identity C0 anchor for the controlled development benchmark.",
        )
    )
    return records


def trajectory_adjacent_pairs(
    trajectory: TrajectoryDatasetRecord,
    *,
    include_identity: bool = True,
) -> list[PairDatasetRecord]:
    records = [
        _pair_record(trajectory, index - 1, index)
        for index in range(1, len(trajectory.steps))
    ]
    if include_identity:
        base = trajectory.steps[0]
        records.append(
            PairDatasetRecord(
                record_id=f"{trajectory.trajectory_id}:identity",
                repository_id=trajectory.repository_id,
                server_id=trajectory.server_id,
                tool_name=trajectory.tool_name,
                old_tool=base.tool,
                new_tool=base.tool,
                label=ChangeClass.NO_MEANINGFUL_CHANGE,
                provenance="controlled_benign",
                old_version_id=base.version_id,
                new_version_id=base.version_id,
            )
        )
    return records


def split_attack_family_fold(fold: Any) -> LearnedFoldSplit:
    """Split the existing family fold into model-fit, policy-tune and untouched test repos."""

    validation_repositories = sorted({item.repository_id for item in fold.validation})
    if len(validation_repositories) < 3:
        raise ValueError("Learned family evaluation requires at least three validation repositories")
    policy_repository = validation_repositories[-1]
    train_repositories = set(validation_repositories[:-1])
    train = tuple(item for item in fold.validation if item.repository_id in train_repositories)
    policy_validation = tuple(
        item for item in fold.validation if item.repository_id == policy_repository
    )
    test = tuple(fold.test)

    train_ids = {item.repository_id for item in train}
    policy_ids = {item.repository_id for item in policy_validation}
    test_ids = {item.repository_id for item in test}
    if train_ids & policy_ids or train_ids & test_ids or policy_ids & test_ids:
        raise ValueError("Repository leakage across learned family benchmark partitions")

    validation_families = {
        step.attack_family
        for item in train + policy_validation
        for step in item.steps
        if step.attack_family is not None
    }
    if fold.held_out_family in validation_families:
        raise ValueError(f"Held-out family {fold.held_out_family!r} leaked before test")

    return LearnedFoldSplit(
        held_out_family=fold.held_out_family,
        train=train,
        policy_validation=policy_validation,
        test=test,
    )


def _probability_record(
    trajectory: TrajectoryDatasetRecord,
    old_index: int,
    new_index: int,
) -> PairDatasetRecord:
    return _pair_record(
        trajectory,
        old_index,
        new_index,
        label=ChangeClass.NO_MEANINGFUL_CHANGE,
    )


def prepare_learned_trajectory(
    model: LogisticPairClassifier,
    trajectory: TrajectoryDatasetRecord,
) -> LearnedPreparedTrajectory:
    pair_probabilities: dict[tuple[int, int], dict[str, float]] = {}
    for old_index in range(len(trajectory.steps) - 1):
        for new_index in range(old_index + 1, len(trajectory.steps)):
            pair_probabilities[(old_index, new_index)] = model.predict_proba(
                _probability_record(trajectory, old_index, new_index)
            )
    return LearnedPreparedTrajectory(
        trace_id=trajectory.trajectory_id,
        final_label=trajectory.final_label,
        attack_onset=_attack_onset(trajectory),
        version_ids=tuple(step.version_id for step in trajectory.steps[1:]),
        pair_probabilities=pair_probabilities,
    )


def _simulate_prepared(
    prepared: LearnedPreparedTrajectory,
    strategy: TemporalStrategy,
    thresholds: ConsentPolicyThresholds,
    *,
    config: LearnedTemporalConfig | None = None,
) -> LearnedTrajectoryOutcome:
    cfg = config or LearnedTemporalConfig()
    approved_index = 0
    cusum = 0.0
    events: list[PolicyActionEvent] = []
    observations_seen = 0

    for observation_index, version_id in enumerate(prepared.version_ids):
        snapshot_index = observation_index + 1
        baseline = prepared.pair_probabilities[(approved_index, snapshot_index)]
        local = prepared.pair_probabilities[(snapshot_index - 1, snapshot_index)]
        baseline_c3 = baseline.get(ChangeClass.MALICIOUS_DRIFT.value, 0.0)
        local_c3 = local.get(ChangeClass.MALICIOUS_DRIFT.value, 0.0)
        baseline_c2 = baseline.get(ChangeClass.CAPABILITY_EXPANSION.value, 0.0)
        cusum = max(
            0.0,
            cfg.memory_decay * cusum + (local_c3 - cfg.reference_probability),
        )

        if strategy is TemporalStrategy.ADJACENT_ONLY:
            malicious_score = local_c3
        elif strategy is TemporalStrategy.APPROVED_BASELINE:
            malicious_score = baseline_c3
        elif strategy is TemporalStrategy.SEQUENTIAL:
            malicious_score = max(baseline_c3, min(1.0, cusum))
        else:  # pragma: no cover
            raise ValueError(f"Unsupported temporal strategy: {strategy}")

        observations_seen += 1
        if malicious_score >= thresholds.block_threshold:
            events.append(
                PolicyActionEvent(
                    observation_index=observation_index,
                    version_id=version_id,
                    action=PolicyAction.BLOCK,
                    malicious_score=round(float(malicious_score), 6),
                    capability_score=round(float(baseline_c2), 6),
                )
            )
            break

        if baseline_c2 >= thresholds.reconsent_threshold:
            events.append(
                PolicyActionEvent(
                    observation_index=observation_index,
                    version_id=version_id,
                    action=PolicyAction.RECONSENT,
                    malicious_score=round(float(malicious_score), 6),
                    capability_score=round(float(baseline_c2), 6),
                )
            )
            approved_index = snapshot_index
            cusum = 0.0

    return LearnedTrajectoryOutcome(
        trace_id=prepared.trace_id,
        final_label=prepared.final_label,
        attack_onset=prepared.attack_onset,
        events=tuple(events),
        observations_seen=observations_seen,
    )


def _metrics(outcomes: list[LearnedTrajectoryOutcome]) -> StatefulPolicyMetrics:
    malicious = [item for item in outcomes if item.final_label is ChangeClass.MALICIOUS_DRIFT]
    c2 = [item for item in outcomes if item.final_label is ChangeClass.CAPABILITY_EXPANSION]
    benign = [
        item
        for item in outcomes
        if item.final_label
        in {ChangeClass.NO_MEANINGFUL_CHANGE, ChangeClass.BENIGN_MAINTENANCE}
    ]

    post_block = 0
    post_intervention = 0
    pre_block = 0
    delays: list[float] = []
    for outcome in malicious:
        if outcome.attack_onset is None:
            continue
        onset = outcome.attack_onset
        if any(
            event.action is PolicyAction.BLOCK and event.observation_index < onset
            for event in outcome.events
        ):
            pre_block += 1
        post_events = [
            event for event in outcome.events if event.observation_index >= onset
        ]
        if post_events:
            post_intervention += 1
        post_blocks = [event for event in post_events if event.action is PolicyAction.BLOCK]
        if post_blocks:
            post_block += 1
            delays.append(float(post_blocks[0].observation_index - onset))

    def has_action(outcome: LearnedTrajectoryOutcome, action: PolicyAction) -> bool:
        return any(event.action is action for event in outcome.events)

    reconsents = sum(
        event.action is PolicyAction.RECONSENT
        for outcome in outcomes
        for event in outcome.events
    )
    return StatefulPolicyMetrics(
        malicious_post_onset_block_rate=(post_block / len(malicious) if malicious else 0.0),
        malicious_post_onset_intervention_rate=(
            post_intervention / len(malicious) if malicious else 0.0
        ),
        malicious_pre_onset_block_rate=(pre_block / len(malicious) if malicious else 0.0),
        c2_reconsent_rate=(
            sum(has_action(item, PolicyAction.RECONSENT) for item in c2) / len(c2)
            if c2
            else 0.0
        ),
        c2_block_rate=(
            sum(has_action(item, PolicyAction.BLOCK) for item in c2) / len(c2)
            if c2
            else 0.0
        ),
        benign_intervention_rate=(
            sum(bool(item.events) for item in benign) / len(benign) if benign else 0.0
        ),
        mean_post_onset_block_delay=(mean(delays) if delays else None),
        reconsents_per_trace=reconsents / len(outcomes),
        traces=len(outcomes),
    )


def evaluate_prepared_policy(
    prepared: list[LearnedPreparedTrajectory],
    strategy: TemporalStrategy,
    thresholds: ConsentPolicyThresholds,
    *,
    config: LearnedTemporalConfig | None = None,
) -> StatefulPolicyMetrics:
    return _metrics(
        [
            _simulate_prepared(item, strategy, thresholds, config=config)
            for item in prepared
        ]
    )


def _objective(metrics: StatefulPolicyMetrics) -> float:
    delay = metrics.mean_post_onset_block_delay or 0.0
    return (
        5.0 * (1.0 - metrics.malicious_post_onset_block_rate)
        + 2.0 * metrics.malicious_pre_onset_block_rate
        + metrics.benign_intervention_rate
        + 0.50 * metrics.c2_block_rate
        + 0.10 * (1.0 - metrics.c2_reconsent_rate)
        + 0.02 * delay
    )


def select_learned_policy(
    prepared: list[LearnedPreparedTrajectory],
    strategy: TemporalStrategy,
    *,
    config: LearnedTemporalConfig | None = None,
    threshold_step: float = 0.05,
) -> StatefulPolicySelection:
    if not prepared:
        raise ValueError("At least one policy-validation trajectory is required")
    count = round(1.0 / threshold_step)
    grid = tuple(round(index * threshold_step, 6) for index in range(1, count + 1))
    candidates: list[StatefulPolicySelection] = []
    for reconsent in grid:
        for block in grid:
            thresholds = ConsentPolicyThresholds(reconsent, block)
            metrics = evaluate_prepared_policy(
                prepared,
                strategy,
                thresholds,
                config=config,
            )
            feasible = (
                metrics.malicious_post_onset_block_rate >= 0.95
                and metrics.c2_reconsent_rate >= 0.90
                and metrics.malicious_pre_onset_block_rate <= 0.03
                and metrics.c2_block_rate <= 0.05
                and metrics.benign_intervention_rate <= 0.10
            )
            candidates.append(
                StatefulPolicySelection(
                    thresholds=thresholds,
                    metrics=metrics,
                    objective=round(_objective(metrics), 8),
                    feasible=feasible,
                )
            )
    feasible = [item for item in candidates if item.feasible]
    pool = feasible or candidates
    return min(
        pool,
        key=lambda item: (
            item.objective,
            item.thresholds.block_threshold,
            item.thresholds.reconsent_threshold,
        ),
    )


def pair_classification_metrics(
    model: LogisticPairClassifier,
    records: list[PairDatasetRecord],
) -> PairClassificationMetrics:
    try:
        from sklearn.metrics import confusion_matrix, f1_score, recall_score, roc_auc_score
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("scikit-learn is required for learned benchmark metrics") from exc

    labels = [item.value for item in ChangeClass]
    y_true = [record.label.value for record in records]
    probabilities = [model.predict_proba(record) for record in records]
    y_pred = [max(row, key=row.get) for row in probabilities]
    recalls = recall_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    binary_truth = [
        int(label == ChangeClass.MALICIOUS_DRIFT.value)
        for label in y_true
    ]
    malicious_scores = [
        row.get(ChangeClass.MALICIOUS_DRIFT.value, 0.0)
        for row in probabilities
    ]
    auroc = (
        float(roc_auc_score(binary_truth, malicious_scores))
        if len(set(binary_truth)) == 2
        else None
    )
    return PairClassificationMetrics(
        records=len(records),
        macro_f1=round(
            float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
            6,
        ),
        malicious_auroc=(round(auroc, 6) if auroc is not None else None),
        per_class_recall={
            label: round(float(value), 6)
            for label, value in zip(labels, recalls, strict=True)
        },
        confusion_matrix={
            true_label: {
                predicted_label: int(matrix[row_index][column_index])
                for column_index, predicted_label in enumerate(labels)
            }
            for row_index, true_label in enumerate(labels)
        },
    )


def evaluate_learned_family_fold(
    fold: Any,
    *,
    config: LearnedTemporalConfig | None = None,
) -> LearnedFamilyEvaluation:
    split = split_attack_family_fold(fold)
    training_records = [
        record
        for trajectory in split.train
        for record in trajectory_training_pairs(trajectory)
    ]
    model = LogisticPairClassifier().fit(training_records)

    policy_prepared = [
        prepare_learned_trajectory(model, item)
        for item in split.policy_validation
    ]
    test_prepared = [
        prepare_learned_trajectory(model, item)
        for item in split.test
    ]
    strategies: list[LearnedFamilyStrategyEvaluation] = []
    for strategy in TemporalStrategy:
        selection = select_learned_policy(
            policy_prepared,
            strategy,
            config=config,
        )
        test_metrics = evaluate_prepared_policy(
            test_prepared,
            strategy,
            selection.thresholds,
            config=config,
        )
        strategies.append(
            LearnedFamilyStrategyEvaluation(
                held_out_family=fold.held_out_family,
                strategy=strategy,
                selection=selection,
                policy_validation_metrics=selection.metrics,
                test_metrics=test_metrics,
            )
        )

    test_records = [
        record
        for trajectory in split.test
        for record in trajectory_adjacent_pairs(trajectory)
    ]
    return LearnedFamilyEvaluation(
        held_out_family=fold.held_out_family,
        train_repositories=tuple(sorted({item.repository_id for item in split.train})),
        policy_validation_repositories=tuple(
            sorted({item.repository_id for item in split.policy_validation})
        ),
        test_repositories=tuple(sorted({item.repository_id for item in split.test})),
        pair_metrics=pair_classification_metrics(model, test_records),
        strategies=tuple(strategies),
    )


def evaluation_asdict(evaluation: LearnedFamilyEvaluation) -> dict[str, Any]:
    return asdict(evaluation)
