from pathlib import Path

from driftguard.graph_evaluation import evaluate_graph_file

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "graph_synthetic_v0.jsonl"


def main() -> None:
    report = evaluate_graph_file(DATASET)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
