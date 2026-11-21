#!/usr/bin/env python3
"""Smoke-test and fit the ordered DriftGuard description-pair classifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "artifacts" / "windows-mcp-description-training"
DATA = OUT / "data"
RUN = OUT / "run"
MODELS = OUT / "models"
MODEL_ID = "cross-encoder/nli-deberta-v3-small"
LABEL_NAMES = {0: "same_or_narrower", 1: "broader", 2: "unclear"}
LABEL2ID = {value: key for key, value in LABEL_NAMES.items()}
SEED = 42


def log(event: str, **fields: Any) -> None:
    record = {"time_utc": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    RUN.mkdir(parents=True, exist_ok=True)
    with (RUN / "logs" / "training.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


def load_rows(split: str) -> list[dict[str, Any]]:
    path = DATA / "pairs.jsonl"
    if not path.exists():
        raise FileNotFoundError("run prepare.py before training")
    with path.open("r", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return [row for row in rows if row.get("split") == split and row.get("label") in LABEL_NAMES]


def validate_frozen_manifest() -> dict[str, Any]:
    manifest_path = DATA / "split_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pairs_hash = hashlib.sha256((DATA / "pairs.jsonl").read_bytes()).hexdigest()
    index_hash = hashlib.sha256((DATA / "split_index.json").read_bytes()).hexdigest()
    if pairs_hash != manifest.get("pairs_jsonl_sha256") or index_hash != manifest.get("split_index_sha256"):
        raise ValueError("frozen data or split index hash changed after preparation")
    split_index = json.loads((DATA / "split_index.json").read_text(encoding="utf-8"))
    if len(split_index) != len({row["example_id"] for row in split_index}):
        raise ValueError("split index contains duplicate example IDs")
    return manifest


def pair_text(row: dict[str, Any]) -> str:
    # Both TF-IDF and the transformer see the same ordered before/after pair.
    return "APPROVED DESCRIPTION: " + row["approved_description"] + "\nCURRENT DESCRIPTION: " + row["current_description"]


def environment_record(torch: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"python": sys.version, "torch": torch.__version__, "torch_cuda": torch.version.cuda, "cuda_available": torch.cuda.is_available()}
    try:
        result["nvidia_smi"] = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], text=True, timeout=10
        ).strip()
    except Exception as error:
        result["nvidia_smi_error"] = str(error)
    if torch.cuda.is_available():
        result["device_name"] = torch.cuda.get_device_name(0)
        result["device_capability"] = list(torch.cuda.get_device_capability(0))
        result["bf16_supported"] = bool(torch.cuda.is_bf16_supported())
        props = torch.cuda.get_device_properties(0)
        result["total_vram_bytes"] = int(props.total_memory)
    return result


def resolve_revision(model_id: str, explicit_revision: str | None) -> str:
    from huggingface_hub import HfApi

    requested = explicit_revision or "main"
    info = HfApi().model_info(model_id, revision=requested)
    if not info.sha:
        raise RuntimeError("Hugging Face did not return a commit SHA; refusing an unpinned checkpoint")
    return info.sha


def make_model(model_id: str, revision: str, torch: Any, transformers: Any) -> tuple[Any, Any]:
    AutoConfig = transformers.AutoConfig
    AutoModel = transformers.AutoModel
    AutoModelForSequenceClassification = transformers.AutoModelForSequenceClassification
    config = AutoConfig.from_pretrained(model_id, revision=revision, trust_remote_code=False)
    config.num_labels = 3
    config.id2label = LABEL_NAMES.copy()
    config.label2id = LABEL2ID.copy()
    backbone = AutoModel.from_pretrained(
        model_id,
        revision=revision,
        trust_remote_code=False,
        use_safetensors=True,
    )
    model = AutoModelForSequenceClassification.from_config(config)
    prefix = model.base_model_prefix
    if not hasattr(model, prefix) or getattr(backbone, "base_model_prefix", prefix) != prefix:
        raise RuntimeError(f"unexpected checkpoint base prefix: {prefix}")
    setattr(model, prefix, backbone)
    model.config.id2label = LABEL_NAMES.copy()
    model.config.label2id = LABEL2ID.copy()
    model.config.num_labels = 3
    return model, config


def reset_seed(torch: Any, seed: int = SEED) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def tokenize_pair(tokenizer: Any, row: dict[str, Any], max_length: int) -> dict[str, Any]:
    return tokenizer(
        row["approved_description"],
        row["current_description"],
        truncation=True,
        max_length=max_length,
        add_special_tokens=True,
    )


def count_truncated(tokenizer: Any, rows: list[dict[str, Any]], max_length: int) -> int:
    truncated = 0
    for index, row in enumerate(rows, 1):
        result = tokenizer(row["approved_description"], row["current_description"], truncation=False, add_special_tokens=True)
        truncated += len(result["input_ids"]) > max_length
        if index % 1000 == 0:
            log("token_length_scan", scanned=index, total=len(rows), truncated=truncated)
    return int(truncated)


def evaluate_logits(model: Any, rows: list[dict[str, Any]], tokenizer: Any, torch: Any, device: Any, batch_size: int, max_length: int) -> tuple[list[int], list[list[float]]]:
    import numpy as np
    from torch.utils.data import DataLoader

    class PairDataset:
        def __init__(self, values: list[dict[str, Any]]) -> None:
            self.values = values

        def __len__(self) -> int:
            return len(self.values)

        def __getitem__(self, index: int) -> dict[str, Any]:
            return {**tokenize_pair(tokenizer, self.values[index], max_length), "labels": int(self.values[index]["label"])}

    collator = transformers_collator(tokenizer, torch)
    loader = DataLoader(PairDataset(rows), batch_size=batch_size, shuffle=False, num_workers=0, collate_fn=collator)
    model.eval()
    predictions: list[int] = []
    probabilities: list[list[float]] = []
    with torch.no_grad():
        for batch in loader:
            labels = batch.pop("labels")
            batch = {key: value.to(device) for key, value in batch.items()}
            logits = model(**batch).logits.float()
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
            predictions.extend(np.argmax(probs, axis=1).tolist())
            probabilities.extend(probs.tolist())
    return predictions, probabilities


def transformers_collator(tokenizer: Any, torch: Any) -> Any:
    from transformers import DataCollatorWithPadding

    base = DataCollatorWithPadding(tokenizer=tokenizer, padding="longest", return_tensors="pt")

    def collate(features: list[dict[str, Any]]) -> dict[str, Any]:
        labels = [feature.pop("labels") for feature in features]
        batch = base(features)
        batch["labels"] = torch.tensor(labels, dtype=torch.long)
        return batch

    return collate


def make_tfidf_baseline(train_rows: list[dict[str, Any]]) -> Any:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=120_000, sublinear_tf=True, strip_accents="unicode")),
        ("char", TfidfVectorizer(analyzer="char", ngram_range=(3, 5), min_df=2, max_features=120_000, sublinear_tf=True)),
    ])
    classifier = LogisticRegression(C=4.0, max_iter=1200, class_weight="balanced", random_state=SEED, solver="lbfgs")
    pipeline = Pipeline([("features", features), ("classifier", classifier)])
    pipeline.fit([pair_text(row) for row in train_rows], [row["label"] for row in train_rows])
    return pipeline


def _save_safetensors(model: Any, tokenizer: Any, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(path, safe_serialization=True)
    tokenizer.save_pretrained(path)


def _run_smoke(args: argparse.Namespace) -> None:
    import numpy as np
    import torch
    import transformers
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer

    reset_seed(torch)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to proceed with the requested transformer fit")
    environment = environment_record(torch)
    revision = resolve_revision(args.model_id, args.revision)
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, revision=revision, trust_remote_code=False, use_fast=True)
    if tokenizer.pad_token_id is None:
        raise RuntimeError("checkpoint tokenizer has no padding token")
    model, _ = make_model(args.model_id, revision, torch, transformers)
    model.to("cuda")
    model.train()
    rows = load_rows("train")[:64]
    if len(rows) < 64:
        raise RuntimeError(f"smoke test needs 64 labeled training rows, found {len(rows)}")
    collator = transformers_collator(tokenizer, torch)

    class SmokeDataset:
        def __len__(self) -> int:
            return len(rows)

        def __getitem__(self, index: int) -> dict[str, Any]:
            return {**tokenize_pair(tokenizer, rows[index], args.max_length), "labels": int(rows[index]["label"])}

    loader = DataLoader(SmokeDataset(), batch_size=args.batch_size, shuffle=False, num_workers=0, collate_fn=collator)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    precision = "bf16" if torch.cuda.is_bf16_supported() else "fp16"
    dtype = torch.bfloat16 if precision == "bf16" else torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=precision == "fp16")
    torch.cuda.reset_peak_memory_stats()
    optimizer.zero_grad(set_to_none=True)
    batch_count = len(loader)
    last_loss = 0.0
    for index, batch in enumerate(loader, 1):
        labels = batch.pop("labels").to("cuda")
        batch = {key: value.to("cuda") for key, value in batch.items()}
        with torch.autocast(device_type="cuda", dtype=dtype):
            logits = model(**batch).logits
            loss = torch.nn.functional.cross_entropy(logits.float(), labels) / args.gradient_accumulation
        scaler.scale(loss).backward()
        if index % args.gradient_accumulation == 0 or index == batch_count:
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad(set_to_none=True)
        last_loss = float(loss.detach().cpu()) * args.gradient_accumulation
    model.eval()
    probe = tokenizer(rows[0]["approved_description"], rows[0]["current_description"], return_tensors="pt", truncation=True, max_length=args.max_length)
    with torch.no_grad():
        reference = model(**{key: value.to("cuda") for key, value in probe.items()}).logits.float().cpu().numpy()
    smoke_path = MODELS / "smoke"
    shutil.rmtree(smoke_path, ignore_errors=True)
    _save_safetensors(model, tokenizer, smoke_path)
    reloaded = transformers.AutoModelForSequenceClassification.from_pretrained(smoke_path, trust_remote_code=False, use_safetensors=True).to("cuda")
    with torch.no_grad():
        actual = reloaded(**{key: value.to("cuda") for key, value in probe.items()}).logits.float().cpu().numpy()
    if reference.shape != (1, 3) or not np.allclose(reference, actual, rtol=1e-4, atol=1e-4):
        raise RuntimeError("smoke checkpoint reload did not reproduce the same three-class logits")
    result = {
        "status": "passed",
        "rows": 64,
        "model_id": args.model_id,
        "model_revision": revision,
        "ordered_inputs": ["approved_description", "current_description"],
        "task_head": "freshly initialized three-label head; only the pretrained base encoder was loaded",
        "trust_remote_code": False,
        "save_format": "safetensors",
        "precision": precision,
        "loss_last_batch": last_loss,
        "reload_logits_max_abs_diff": float(np.max(np.abs(reference - actual))),
        "peak_cuda_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "environment": environment,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    (RUN / "smoke_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("smoke_passed", **{key: value for key, value in result.items() if key not in {"environment"}})


def _run_full(args: argparse.Namespace) -> None:
    import numpy as np
    import torch
    import transformers
    from sklearn.metrics import f1_score
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer
    import joblib

    smoke_result_path = RUN / "smoke_result.json"
    if not smoke_result_path.exists() or json.loads(smoke_result_path.read_text(encoding="utf-8")).get("status") != "passed":
        raise RuntimeError("run and pass --smoke before the full fit")
    reset_seed(torch)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to start the full transformer fit")
    environment = environment_record(torch)
    revision = resolve_revision(args.model_id, args.revision)
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, revision=revision, trust_remote_code=False, use_fast=True)
    model, _ = make_model(args.model_id, revision, torch, transformers)
    train_rows = load_rows("train")
    validation_rows = load_rows("validation")
    if len(train_rows) < 10_000 or len(validation_rows) < 1000:
        raise RuntimeError(f"minimum split sizes not met: train={len(train_rows)} validation={len(validation_rows)}")
    model.to("cuda")
    model.config.label2id = LABEL2ID.copy()
    model.config.id2label = LABEL_NAMES.copy()
    model.config.num_labels = 3
    precision = "bf16" if torch.cuda.is_bf16_supported() else "fp16"
    dtype = torch.bfloat16 if precision == "bf16" else torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=precision == "fp16")
    truncated_train = count_truncated(tokenizer, train_rows, args.max_length)
    truncated_validation = count_truncated(tokenizer, validation_rows, args.max_length)
    collator = transformers_collator(tokenizer, torch)

    class PairDataset:
        def __init__(self, values: list[dict[str, Any]]) -> None:
            self.values = values

        def __len__(self) -> int:
            return len(self.values)

        def __getitem__(self, index: int) -> dict[str, Any]:
            return {**tokenize_pair(tokenizer, self.values[index], args.max_length), "labels": int(self.values[index]["label"])}

    generator = torch.Generator()
    generator.manual_seed(SEED)
    train_loader = DataLoader(PairDataset(train_rows), batch_size=args.batch_size, shuffle=True, generator=generator, num_workers=0, collate_fn=collator)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    updates_per_epoch = math.ceil(len(train_loader) / args.gradient_accumulation)
    total_updates = updates_per_epoch * args.epochs
    warmup = max(1, int(total_updates * 0.06))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: min((step + 1) / warmup, max(0.0, (total_updates - step) / max(1, total_updates - warmup))))
    best_score = -1.0
    best_state: dict[str, Any] | None = None
    best_epoch = 0
    epoch_history: list[dict[str, Any]] = []
    torch.cuda.reset_peak_memory_stats()
    training_started = time.monotonic()
    log("training_started", rows=len(train_rows), validation_rows=len(validation_rows), epochs=args.epochs, device_batch_size=args.batch_size, gradient_accumulation=args.gradient_accumulation, effective_batch_size=args.batch_size * args.gradient_accumulation, max_length=args.max_length, learning_rate=args.learning_rate, precision=precision, truncated_train=truncated_train, truncated_validation=truncated_validation, total_optimizer_steps=total_updates, environment=environment, model_id=args.model_id, model_revision=revision, seed=SEED)
    for epoch in range(1, args.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        losses: list[float] = []
        started = time.monotonic()
        total_batches = len(train_loader)
        for batch_index, batch in enumerate(train_loader, 1):
            labels = batch.pop("labels").to("cuda")
            batch = {key: value.to("cuda") for key, value in batch.items()}
            group_start = ((batch_index - 1) // args.gradient_accumulation) * args.gradient_accumulation
            divisor = min(args.gradient_accumulation, total_batches - group_start)
            with torch.autocast(device_type="cuda", dtype=dtype):
                logits = model(**batch).logits
                loss = torch.nn.functional.cross_entropy(logits.float(), labels) / divisor
            scaler.scale(loss).backward()
            losses.append(float(loss.detach().cpu()) * divisor)
            if batch_index % args.gradient_accumulation == 0 or batch_index == total_batches:
                scaler.step(optimizer)
                scaler.update()
                optimizer.zero_grad(set_to_none=True)
                scheduler.step()
            if batch_index % 250 == 0:
                log("training_progress", epoch=epoch, batch=batch_index, batches=total_batches, mean_loss=sum(losses[-250:]) / len(losses[-250:]), lr=optimizer.param_groups[0]["lr"], peak_cuda_memory_allocated_bytes=int(torch.cuda.max_memory_allocated()))
        predictions, probabilities = evaluate_logits(model, validation_rows, tokenizer, torch, "cuda", args.batch_size, args.max_length)
        truth = [int(row["label"]) for row in validation_rows]
        score = float(f1_score(truth, predictions, labels=[0, 1, 2], average="macro", zero_division=0))
        epoch_dir = MODELS / f"epoch-{epoch:02d}"
        _save_safetensors(model, tokenizer, epoch_dir)
        stats = {
            "epoch": epoch,
            "mean_training_loss": sum(losses) / max(1, len(losses)),
            "validation_macro_f1": score,
            "validation_count": len(validation_rows),
            "elapsed_seconds": time.monotonic() - started,
            "peak_cuda_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "peak_cuda_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
            "checkpoint": str(epoch_dir.relative_to(ROOT)),
        }
        epoch_history.append(stats)
        write_path = RUN / "epoch_metrics.json"
        write_path.write_text(json.dumps(epoch_history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log("epoch_finished", **stats)
        if score > best_score:
            best_score, best_epoch = score, epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    if best_state is None:
        raise RuntimeError("no validation-selected checkpoint was produced")
    model.load_state_dict(best_state)
    best_dir = MODELS / "best"
    shutil.rmtree(best_dir, ignore_errors=True)
    _save_safetensors(model, tokenizer, best_dir)
    import sklearn
    import transformers as transformers_package
    import accelerate
    import datasets
    import huggingface_hub
    import safetensors
    import sentencepiece

    baseline = make_tfidf_baseline(train_rows)
    joblib.dump(baseline, MODELS / "tfidf_logistic.joblib", compress=3)
    config = {
        "seed": SEED,
        "model_id": args.model_id,
        "model_revision": revision,
        "model_revision_source": args.revision or "resolved from Hugging Face main at run start",
        "labels": LABEL_NAMES,
        "task_head": "explicitly reinitialized from config; pretrained base encoder weights only",
        "token_input_order": ["approved_description", "current_description"],
        "max_length": args.max_length,
        "dynamic_padding": True,
        "device_batch_size": args.batch_size,
        "gradient_accumulation": args.gradient_accumulation,
        "effective_batch_size": args.batch_size * args.gradient_accumulation,
        "learning_rate": args.learning_rate,
        "epochs": args.epochs,
        "precision": precision,
        "dataloader_workers": 0,
        "safe_serialization": True,
        "trust_remote_code": False,
        "truncated_train_rows": truncated_train,
        "truncated_validation_rows": truncated_validation,
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "best_epoch": best_epoch,
        "best_validation_macro_f1_provisional": best_score,
        "split_manifest_sha256": hashlib.sha256((DATA / "split_manifest.json").read_bytes()).hexdigest(),
        "environment": environment,
        "dependency_versions": {
            "torch": torch.__version__, "transformers": transformers_package.__version__, "accelerate": accelerate.__version__,
            "datasets": datasets.__version__, "huggingface_hub": huggingface_hub.__version__, "scikit_learn": sklearn.__version__,
            "safetensors": safetensors.__version__, "sentencepiece": sentencepiece.__version__,
        },
        "total_training_seconds": time.monotonic() - training_started,
        "peak_cuda_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "peak_cuda_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        "status": "research_only_provisional_weak_label_metrics",
    }
    (RUN / "run_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log("training_complete", best_epoch=best_epoch, best_validation_macro_f1=best_score, peak_cuda_memory_allocated_bytes=config["peak_cuda_memory_allocated_bytes"], peak_cuda_memory_reserved_bytes=config["peak_cuda_memory_reserved_bytes"], total_training_seconds=config["total_training_seconds"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="run the required 64-row CUDA/save/reload smoke test")
    parser.add_argument("--model-id", default=MODEL_ID)
    parser.add_argument("--revision", help="pinned checkpoint commit SHA; otherwise resolve main to SHA at run start")
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    frozen = validate_frozen_manifest()
    log("frozen_split_validated", split_manifest_sha256=hashlib.sha256((DATA / "split_manifest.json").read_bytes()).hexdigest(), pair_sha256=frozen["pairs_jsonl_sha256"], split_index_sha256=frozen["split_index_sha256"])
    if args.smoke:
        _run_smoke(args)
    else:
        _run_full(args)


if __name__ == "__main__":
    main()
