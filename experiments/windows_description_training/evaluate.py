#!/usr/bin/env python3
"""Evaluate rule, TF-IDF, and DeBERTa predictions on frozen held-out pairs."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_driftguard.heuristics import find_suspicious_patterns
from train import LABEL_NAMES, LABEL2ID, RUN, DATA, OUT, MODELS, load_rows, pair_text, validate_frozen_manifest


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def softmax_rows(logits: Any) -> list[list[float]]:
    import torch

    return torch.softmax(logits.float(), dim=-1).cpu().tolist()


def confusion_counts(y_true: list[int], y_pred: list[int]) -> dict[str, Any]:
    names = [LABEL_NAMES[index] for index in range(3)]
    matrix = [[sum(1 for truth, pred in zip(y_true, y_pred) if truth == i and pred == j) for j in range(3)] for i in range(3)]
    per_label = {}
    for index, name in enumerate(names):
        tp = matrix[index][index]
        fp = sum(matrix[other][index] for other in range(3) if other != index)
        fn = sum(matrix[index][other] for other in range(3) if other != index)
        support = sum(matrix[index])
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[name] = {"support": support, "precision": precision, "recall": recall, "f1": f1}
    return {"labels": names, "confusion_matrix_rows_true_columns_predicted": matrix, "per_label": per_label}


def expansion_metrics(y_true: list[int], scores: list[float], threshold: float) -> dict[str, Any]:
    y_pred = [1 if score >= threshold else 0 for score in scores]
    expansion_count = sum(value == 1 for value in y_true)
    benign_count = sum(value == 0 for value in y_true)
    tp = sum(truth == 1 and pred == 1 for truth, pred in zip(y_true, y_pred))
    fp_benign = sum(truth == 0 and pred == 1 for truth, pred in zip(y_true, y_pred))
    fn = sum(truth == 1 and pred == 0 for truth, pred in zip(y_true, y_pred))
    precision = tp / (tp + fp_benign) if tp + fp_benign else 0.0
    recall = tp / expansion_count if expansion_count else 0.0
    return {
        "threshold": threshold,
        "expansion_true_positives": tp,
        "expansion_false_negatives": fn,
        "benign_false_review_prompts": fp_benign,
        "expansion_denominator": expansion_count,
        "benign_denominator": benign_count,
        "expansion_precision": precision,
        "expansion_recall": recall,
        "false_review_prompts_per_100_benign_edits": 100.0 * fp_benign / benign_count if benign_count else None,
    }


def precision_recall_curve(y_true: list[int], scores: list[float]) -> list[dict[str, Any]]:
    thresholds = sorted(set([0.0, 1.000001] + [float(score) for score in scores]), reverse=True)
    return [expansion_metrics(y_true, scores, threshold) for threshold in thresholds]


def choose_broader_threshold(y_true: list[int], scores: list[float], max_benign_rate: float = 0.10) -> dict[str, Any]:
    candidates = sorted(set([0.0, 1.000001] + [float(score) for score in scores]))
    valid = [expansion_metrics(y_true, scores, threshold) for threshold in candidates]
    valid = [row for row in valid if (row["false_review_prompts_per_100_benign_edits"] or 0.0) <= max_benign_rate * 100]
    if not valid:
        return {"threshold": 1.000001, "selection": "no validation threshold met the benign review budget", "validation_operating_point": expansion_metrics(y_true, scores, 1.000001)}
    best = max(valid, key=lambda row: (row["expansion_recall"], row["expansion_precision"], row["threshold"]))
    return {"threshold": best["threshold"], "selection": "maximum expansion recall subject to validation benign review rate <= 10%", "validation_operating_point": best}


def recall_at_review_budget(y_true: list[int], scores: list[float], budgets: list[float]) -> list[dict[str, Any]]:
    output = []
    for budget in budgets:
        candidates = sorted(set([1.000001] + [float(score) for score in scores]))
        valid = []
        for threshold in candidates:
            metric = expansion_metrics(y_true, scores, threshold)
            rate = metric["false_review_prompts_per_100_benign_edits"]
            if rate is not None and rate <= budget * 100 + 1e-9:
                valid.append(metric)
        selected = max(valid, key=lambda row: (row["expansion_recall"], row["expansion_precision"], row["threshold"])) if valid else expansion_metrics(y_true, scores, 1.000001)
        output.append({"benign_review_budget": budget, **selected})
    return output


def choose_unclear_threshold(y_true: list[int], scores: list[float]) -> float:
    candidates = sorted(set([0.0, 1.000001] + [float(score) for score in scores]))
    best_threshold, best_f1 = 1.000001, -1.0
    for threshold in candidates:
        predicted = [score >= threshold for score in scores]
        tp = sum(truth == 2 and pred for truth, pred in zip(y_true, predicted))
        fp = sum(truth != 2 and pred for truth, pred in zip(y_true, predicted))
        fn = sum(truth == 2 and not pred for truth, pred in zip(y_true, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best_f1:
            best_threshold, best_f1 = threshold, f1
    return best_threshold


def class_predictions(probabilities: list[list[float]], broader_threshold: float, unclear_threshold: float) -> list[int]:
    predictions = []
    for row in probabilities:
        if row[2] >= unclear_threshold and row[2] > row[1]:
            predictions.append(2)
        elif row[1] >= broader_threshold:
            predictions.append(1)
        else:
            predictions.append(0)
    return predictions


def rule_predictions(rows: list[dict[str, Any]]) -> tuple[list[int], list[list[float]], list[list[str]]]:
    predictions, probabilities, codes = [], [], []
    for row in rows:
        hits = find_suspicious_patterns(row["current_description"])
        labels = [code for code, _ in hits]
        code = 1 if hits else 0
        predictions.append(code)
        probabilities.append([1.0 - float(bool(hits)), float(bool(hits)), 0.0])
        codes.append(labels)
    return predictions, probabilities, codes


def tfidf_predictions(model: Any, rows: list[dict[str, Any]]) -> tuple[list[int], list[list[float]]]:
    import numpy as np

    matrix = model.predict_proba([pair_text(row) for row in rows])
    classes = list(model.named_steps["classifier"].classes_)
    full = np.zeros((len(rows), 3), dtype=float)
    for column, label in enumerate(classes):
        full[:, int(label)] = matrix[:, column]
    return np.argmax(full, axis=1).tolist(), full.tolist()


def deberta_predictions(model: Any, tokenizer: Any, rows: list[dict[str, Any]], batch_size: int, max_length: int) -> tuple[list[int], list[list[float]]]:
    import numpy as np
    import torch
    from torch.utils.data import DataLoader
    from transformers import DataCollatorWithPadding

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    class PairDataset:
        def __len__(self) -> int:
            return len(rows)

        def __getitem__(self, index: int) -> dict[str, Any]:
            row = rows[index]
            return tokenizer(row["approved_description"], row["current_description"], truncation=True, max_length=max_length)

    loader = DataLoader(PairDataset(), batch_size=batch_size, shuffle=False, num_workers=0, collate_fn=DataCollatorWithPadding(tokenizer, padding="longest", return_tensors="pt"))
    model.to(device)
    model.eval()
    probabilities: list[list[float]] = []
    with torch.no_grad():
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            logits = model(**batch).logits.float()
            probabilities.extend(softmax_rows(logits))
    return np.argmax(np.asarray(probabilities), axis=1).tolist(), probabilities


def labels_to_ids(values: list[str]) -> list[int]:
    result = []
    for value in values:
        normalized = value.upper()
        if normalized in {"ALLOW", "SAME_OR_NARROWER", "BENIGN"}:
            result.append(0)
        elif normalized in {"FLAG", "BROADER", "EXPANSION", "EXPANDED"}:
            result.append(1)
        else:
            result.append(2)
    return result


def metric_bundle(rows: list[dict[str, Any]], probabilities: dict[str, list[list[float]]], rules: tuple[list[int], list[list[float]], list[list[str]]], thresholds: dict[str, dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    y_true = [int(row["label"]) for row in rows]
    rule_preds, rule_probs, rule_codes = rules
    probabilities_with_rules = {**probabilities, "driftguard_rules": rule_probs}
    model_names = list(probabilities) + ["driftguard_rules"]
    thresholds = thresholds or {}
    model_thresholds: dict[str, dict[str, float]] = {}
    all_preds: dict[str, list[int]] = {"driftguard_rules": rule_preds}
    metrics: dict[str, Any] = {"count": len(rows), "label_counts": dict(Counter(LABEL_NAMES[value] for value in y_true)), "label_source_counts": dict(Counter(row.get("label_source", "external") for row in rows)), "by_method": {}, "scope_only": {}}
    for name in model_names:
        values = probabilities_with_rules[name]
        broader_threshold = thresholds.get(name, {}).get("broader_threshold", 0.5)
        unclear_threshold = thresholds.get(name, {}).get("unclear_threshold", 0.5)
        preds = class_predictions(values, broader_threshold, unclear_threshold) if name != "driftguard_rules" else rule_preds
        all_preds[name] = preds
        model_thresholds[name] = {"broader_threshold": broader_threshold, "unclear_threshold": unclear_threshold}
        score = [value[1] for value in values]
        metrics["by_method"][name] = {
            "thresholds": model_thresholds[name],
            "classification": confusion_counts(y_true, preds),
            "expansion_at_selected_threshold": expansion_metrics(y_true, score, broader_threshold),
            "precision_recall_curve": precision_recall_curve(y_true, score),
            "recall_at_similar_benign_review_rates": recall_at_review_budget(y_true, score, [0.01, 0.05, 0.10]),
            "unclear_abstention_rate": sum(value == 2 for value in preds) / len(preds) if preds else 0.0,
            "false_review_prompts_per_100_benign_edits": expansion_metrics(y_true, score, broader_threshold)["false_review_prompts_per_100_benign_edits"],
        }
    for source in sorted({str(row.get("label_source", "unknown")) for row in rows}):
        indices = [index for index, row in enumerate(rows) if row.get("label_source", "unknown") == source]
        if not indices:
            continue
        source_truth = [y_true[index] for index in indices]
        for method in model_names:
            preds = [all_preds[method][index] for index in indices]
            metrics["by_method"][method].setdefault("by_label_source", {})[source] = {
                "count": len(indices),
                "label_counts": dict(Counter(LABEL_NAMES[value] for value in source_truth)),
                "classification": confusion_counts(source_truth, preds),
            }
    scope_indices = [index for index, row in enumerate(rows) if row.get("changed_dimension") == "scope"]
    if scope_indices:
        scope_truth = [y_true[index] for index in scope_indices]
        for method in model_names:
            metrics["scope_only"][method] = {
                "count": len(scope_indices),
                "label_counts": dict(Counter(LABEL_NAMES[value] for value in scope_truth)),
                "classification": confusion_counts(scope_truth, [all_preds[method][index] for index in scope_indices]),
            }
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = {
            "example_id": row.get("example_id"),
            "true_label": LABEL_NAMES[y_true[index]],
            "true_label_id": y_true[index],
            "label_source": row.get("label_source"),
            "source_kind": row.get("source_kind"),
            "split": row.get("split", "external"),
            "changed_dimension": row.get("changed_dimension"),
            "scope_only": row.get("changed_dimension") == "scope",
            "approved_description": row.get("approved_description") or row.get("before") or "",
            "current_description": row.get("current_description") or row.get("after") or "",
            "evidence_before": row.get("evidence_before"),
            "evidence_after": row.get("evidence_after"),
            "provenance": row.get("provenance", {"source": row.get("source"), "category": row.get("category"), "id": row.get("id")}),
            "model_outputs": {},
            "driftguard_rule_codes": rule_codes[index] if index < len(rule_codes) else [],
        }
        for method in model_names:
            item["model_outputs"][method] = {
                "predicted_label": LABEL_NAMES[all_preds[method][index]],
                "predicted_label_id": all_preds[method][index],
                "probabilities": {LABEL_NAMES[label]: float(probabilities_with_rules[method][index][label]) for label in range(3)},
            }
        records.append(item)
    return metrics, records


def select_validation_thresholds(rows: list[dict[str, Any]], predictions: dict[str, list[list[float]]]) -> dict[str, Any]:
    y_true = [int(row["label"]) for row in rows]
    result = {}
    for method, values in predictions.items():
        p1 = [row[1] for row in values]
        p2 = [row[2] for row in values]
        broader = choose_broader_threshold(y_true, p1)
        unclear = choose_unclear_threshold(y_true, p2)
        result[method] = {
            "broader_threshold": broader["threshold"],
            "unclear_threshold": unclear,
            "validation_selection": broader["selection"],
            "validation_operating_point": broader["validation_operating_point"],
        }
    return result


def load_all(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    import joblib
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    frozen = validate_frozen_manifest()
    run_config_path = RUN / "run_config.json"
    if not run_config_path.exists():
        raise FileNotFoundError("run train.py after the smoke test before evaluation")
    run_config = json.loads(run_config_path.read_text(encoding="utf-8"))
    model_revision = run_config["model_revision"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForSequenceClassification.from_pretrained(MODELS / "best", trust_remote_code=False, use_safetensors=True).to(device)
    tokenizer = AutoTokenizer.from_pretrained(MODELS / "best", trust_remote_code=False, use_fast=True)
    tfidf = joblib.load(MODELS / "tfidf_logistic.joblib")

    validation_rows = load_rows("validation")
    validation_predictions = {}
    for name, model_obj in (("tfidf_logistic", tfidf),):
        _, validation_predictions[name] = tfidf_predictions(model_obj, validation_rows)
    _, validation_predictions["deberta"] = deberta_predictions(model, tokenizer, validation_rows, 4, int(run_config["max_length"]))
    thresholds = select_validation_thresholds(validation_rows, validation_predictions)
    write_json(RUN / "validation_thresholds.json", {"selected_on": "validation only", "methods": thresholds})

    all_splits: dict[str, list[dict[str, Any]]] = {
        "validation": validation_rows,
        "test": load_rows("test"),
        "time_challenge": load_all(DATA / "time_challenge.jsonl"),
    }
    metrics: dict[str, Any] = {
        "status": "research_only_provisional_weak_labels; no independent human annotations available",
        "previous_6feature_reference": {
            "expansion_recall": "0/11",
            "benign_false_quarantines": "15/131",
            "source": "user-supplied starting benchmark",
            "direct_142_pair_replay": "unavailable: this checkout contains no prior 142-pair corpus or six-feature model; the closest pinned external comparison is the 144-record CAPGATE real-history subset",
        },
        "model_id": run_config["model_id"],
        "model_revision": model_revision,
        "split_manifest_sha256": hashlib.sha256((DATA / "split_manifest.json").read_bytes()).hexdigest(),
        "thresholds_selected_on_validation_only": thresholds,
        "capsule": {"seed": 42, "ordered_pair": ["approved_description", "current_description"], "live_gateway_installation": False},
        "splits": {},
        "external_capgate": {"status": "not available"},
    }
    predictions_dir = OUT / "predictions"
    errors_dir = OUT / "analysis"
    predictions_dir.mkdir(parents=True, exist_ok=True)
    errors_dir.mkdir(parents=True, exist_ok=True)
    for split, rows in all_splits.items():
        if not rows:
            continue
        if split == "time_challenge":
            rows = [row for row in rows if row.get("label") in LABEL_NAMES]
            if not rows:
                continue
        _, tfidf_probs = tfidf_predictions(tfidf, rows)
        _, deberta_probs = deberta_predictions(model, tokenizer, rows, 4, int(run_config["max_length"]))
        rule_values = rule_predictions(rows)
        methods = {"tfidf_logistic": tfidf_probs, "deberta": deberta_probs}
        split_metrics, records = metric_bundle(rows, methods, rule_values, thresholds)
        metrics["splits"][split] = split_metrics
        with (predictions_dir / f"{split}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        errors = []
        for record in records:
            wrong = [method for method, output in record["model_outputs"].items() if output["predicted_label"] != record["true_label"]]
            if wrong:
                errors.append({**record, "misclassified_by": wrong})
        errors.sort(key=lambda row: (row["label_source"] or "", row["true_label"], row["example_id"]))
        with (errors_dir / f"{split}_errors.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for error in errors:
                handle.write(json.dumps(error, ensure_ascii=False, sort_keys=True) + "\n")
        metrics["splits"][split]["error_count_any_learned_model"] = len(errors)

    capgate_path = DATA / "source_cache" / "capgate_dataset.json"
    if not capgate_path.exists():
        capgate_path = OUT / "source_cache" / "capgate_dataset.json"
    if capgate_path.exists():
        full = json.loads(capgate_path.read_text(encoding="utf-8"))
        external = [row for row in full if row.get("category") == "real_benign"]
        external_rows = []
        external_ids = []
        for row in external:
            before = row.get("before", "")
            after = row.get("after", "")
            external_ids.append({
                "capgate_id": row.get("id"),
                "source": row.get("source"),
                "tool": row.get("tool"),
                "label": row.get("label"),
                "before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
                "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
                "ordered_pair_sha256": hashlib.sha256((before + "\0" + after).encode("utf-8")).hexdigest(),
            })
            external_rows.append({
                "example_id": "capgate:" + str(row.get("id")),
                "label": 0 if str(row.get("label", "")).upper() == "ALLOW" else 1,
                "label_source": "capgate_rule_diagnostic",
                "source_kind": "external_capgate_real_history",
                "source": row.get("source"),
                "tool": row.get("tool"),
                "approved_description": before,
                "current_description": after,
                "changed_dimension": row.get("expanded_dimension") or "unknown",
                "evidence_before": row.get("annotation_reason"),
                "evidence_after": row.get("expanded_dimension"),
                "provenance": {"capgate_id": row.get("id"), "source": row.get("source"), "category": row.get("category"), "origin": row.get("origin"), "annotation_rule": row.get("annotation_rule")},
            })
        _, ext_tfidf_probs = tfidf_predictions(tfidf, external_rows)
        _, ext_deberta_probs = deberta_predictions(model, tokenizer, external_rows, 4, int(run_config["max_length"]))
        ext_rule = rule_predictions(external_rows)
        ext_metrics, ext_records = metric_bundle(external_rows, {"tfidf_logistic": ext_tfidf_probs, "deberta": ext_deberta_probs}, ext_rule, thresholds)
        metrics["external_capgate"] = {
            "status": "separate external diagnostic; CAPGATE labels are rule-derived, not independent human labels",
            "benchmark_rows_included": len(external_rows),
            "rows_excluded_constructed_and_malicious_anchor": len(full) - len(external_rows),
            "label_counts": dict(Counter(LABEL_NAMES[row["label"]] for row in external_rows)),
            "by_source_repository": {source: sum(row.get("source") == source for row in external_rows) for source in sorted({row.get("source", "") for row in external_rows})},
            "metrics": ext_metrics,
        }
        source_manifest = json.loads((DATA / "source_manifest.json").read_text(encoding="utf-8"))
        write_json(DATA / "capgate_external_manifest.json", {
            "source": source_manifest.get("capgate"),
            "benchmark_filter": "category == real_benign; constructed and malicious-anchor rows excluded",
            "included_rows": external_ids,
            "included_count": len(external_ids),
            "portable_text": False,
            "note": "Pair text remains in the local source cache because rights vary by originating repository; IDs and hashes are included for reproducibility.",
        })
        with (predictions_dir / "capgate_external.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in ext_records:
                record.pop("approved_description", None)
                record.pop("current_description", None)
                record.pop("evidence_before", None)
                record.pop("evidence_after", None)
                provenance = record.get("provenance", {})
                record["provenance"] = {key: provenance.get(key) for key in ("capgate_id", "source", "category", "origin", "annotation_rule")}
                manifest_row = next(item for item in external_ids if "capgate:" + str(item["capgate_id"]) == record["example_id"])
                record["description_hashes"] = {"approved": manifest_row["before_sha256"], "current": manifest_row["after_sha256"], "ordered_pair": manifest_row["ordered_pair_sha256"]}
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        with (errors_dir / "capgate_external_errors.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in ext_records:
                if any(value["predicted_label"] != record["true_label"] for value in record["model_outputs"].values()):
                    record.pop("approved_description", None)
                    record.pop("current_description", None)
                    record.pop("evidence_before", None)
                    record.pop("evidence_after", None)
                    provenance = record.get("provenance", {})
                    record["provenance"] = {key: provenance.get(key) for key in ("capgate_id", "source", "category", "origin", "annotation_rule")}
                    manifest_row = next(item for item in external_ids if "capgate:" + str(item["capgate_id"]) == record["example_id"])
                    record["description_hashes"] = {"approved": manifest_row["before_sha256"], "current": manifest_row["after_sha256"], "ordered_pair": manifest_row["ordered_pair_sha256"]}
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    write_json(OUT / "metrics.json", metrics)
    write_json(errors_dir / "summary.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "test_error_file": "../predictions/test.jsonl and test_errors.jsonl",
        "scope_only_counts_by_test_label": metrics.get("splits", {}).get("test", {}).get("scope_only", {}),
        "CAPGATE_is_separate": True,
    })
    print(json.dumps({"status": metrics["status"], "heldout_splits": {key: value.get("count") for key, value in metrics["splits"].items()}, "capgate_external": metrics["external_capgate"].get("benchmark_rows_included")}, indent=2))


if __name__ == "__main__":
    main()
