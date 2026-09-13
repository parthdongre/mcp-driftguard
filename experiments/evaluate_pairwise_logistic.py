from pathlib import Path

from driftguard.canonicalize import make_snapshot
from driftguard.diff import build_delta
from driftguard.evaluation import load_jsonl
from driftguard.ml import PairwiseLogisticDetector

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "synthetic_v0.jsonl"


def main() -> None:
    samples = load_jsonl(DATASET)
    rows: list[dict[str, object]] = []
    correct = 0
    abstained = 0

    for index, held_out in enumerate(samples):
        training = samples[:index] + samples[index + 1 :]
        detector = PairwiseLogisticDetector().fit(training)

        old = make_snapshot(
            server_id=f"loo:{held_out.sample_id}",
            tool=held_out.old_tool,
            approval_state="approved",
        )
        new = make_snapshot(
            server_id=f"loo:{held_out.sample_id}",
            tool=held_out.new_tool,
        )
        assessment = detector(build_delta(old, new))
        is_correct = assessment.change_class == held_out.label
        correct += int(is_correct)
        abstained += int(assessment.abstained)

        rows.append(
            {
                "sample_id": held_out.sample_id,
                "expected": held_out.label.value,
                "predicted": assessment.change_class.value,
                "confidence": assessment.confidence,
                "abstained": assessment.abstained,
                "correct": is_correct,
            }
        )

    total = len(samples)
    print(
        {
            "protocol": "leave-one-out",
            "total": total,
            "accuracy": round(correct / total, 4) if total else 0.0,
            "abstention_rate": round(abstained / total, 4) if total else 0.0,
            "predictions": rows,
        }
    )


if __name__ == "__main__":
    main()
