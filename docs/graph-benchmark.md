# Graph topology drift benchmark

DriftGuard now has a separate benchmark for **discovery-surface topology drift** rather than forcing graph behavior into the per-tool schema benchmark.

The first dataset is `data/graph_synthetic_v0.jsonl`. Each record contains:

- an old complete tool surface,
- a new complete tool surface,
- a change family,
- an independent binary `risky` label.

The initial families cover unchanged topology, benign surface growth, benign references, removed references, imperative redirects, routes toward sensitive-looking tools, newly introduced cycles, and combined sensitive + imperative routes.

## Baseline

`graph_rule_baseline(...)` is intentionally transparent. It scores topology changes such as:

- newly added edges toward sensitive-looking tools,
- newly added imperative cross-tool routes,
- new cycles,
- tools that newly become suspicious from graph evidence.

The baseline does **not** automatically alter MCP enforcement policy yet. The purpose of the benchmark is to establish measurable false-positive/false-negative behavior before graph evidence is allowed to block tools.

Run:

```bash
python experiments/evaluate_graph_baseline.py
```

The report includes accuracy, precision, recall, F1, TP/FP/TN/FN counts, and per-sample predictions.

## Research use

This enables an ablation that the pairwise tool benchmark cannot answer:

```text
per-tool detector only
vs
per-tool + temporal history
vs
per-tool + cross-tool topology evidence
```

The first synthetic graph corpus is only a protocol/experiment scaffold. It is not large enough for publication accuracy claims. A research-grade version should include real MCP server evolution, adversarial multi-tool bundles, renamed tools, indirect multi-hop routes, benign orchestration patterns, and held-out attack families.
