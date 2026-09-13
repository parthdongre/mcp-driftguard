from pathlib import Path

from driftguard.evaluation import evaluate_file

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "synthetic_v0.jsonl"


def main() -> None:
    report = evaluate_file(DATASET)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
