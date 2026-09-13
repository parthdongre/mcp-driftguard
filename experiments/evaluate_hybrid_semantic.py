import os
from pathlib import Path

from driftguard.canonicalize import make_snapshot
from driftguard.diff import build_delta
from driftguard.evaluation import load_jsonl
from driftguard.semantic import HybridSemanticLogisticDetector, SentenceTransformerEmbedder

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "synthetic_v0.jsonl"


def main() -> None:
    model_name = os.getenv(
        "DRIFTGUARD_EMBEDDING_MODEL",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    embedder = SentenceTransformerEmbedder(model_name)
    samples = load_jsonl(DATASET)
    correct = 0
    abstained = 0
    rows: list[dict[str, object]] = []

    for index, held_out in enumerate(samples):
        training = samples[:index] + samples[index + 1 :]
        detector = HybridSemanticLogisticDetector(embedder).fit(training)

        old = make_snapshot(
            server_id=f"semantic-loo:{held_out.sample_id}",
            tool=held_out.old_tool,
            approval_state="approved",
        )
        new = make_snapshot(
            server_id=f"semantic-loo:{held_out.sample_id}",
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
            "protocol": "leave-one-out-hybrid-semantic",
            "embedding_model": model_name,
            "total": total,
            "accuracy": round(correct / total, 4) if total else 0.0,
            "abstention_rate": round(abstained / total, 4) if total else 0.0,
            "predictions": rows,
        }
    )


if __name__ == "__main__":
    main()
