from copy import deepcopy

import pytest

from driftguard.dataset import PairDatasetRecord
from driftguard.learning import GroupedSplit
from driftguard.models import ChangeClass
from driftguard.semantic_xgboost import compare, validate_splits


def records(group):
    result = []
    for label in ChangeClass:
        old = {"name": "read_sample", "description": f"Read sample from {group}."}
        new = deepcopy(old)
        if label == ChangeClass.BENIGN_MAINTENANCE:
            new["description"] = f"Read the sample from {group}."
        if label == ChangeClass.CAPABILITY_EXPANSION:
            new["inputSchema"] = {"type": "object", "properties": {"limit": {"type": "integer"}}}
        if label == ChangeClass.MALICIOUS_DRIFT:
            # An illustrative label on harmless text for testing the experiment.
            new["description"] = f"Summarize the selected sample from {group}."
        result.append(PairDatasetRecord(
            record_id=f"{group}/{label}", repository_id=group, server_id="sample",
            tool_name="read_sample", old_tool=old, new_tool=new,
            label=label, provenance="controlled_benign",
        ))
    return result


def test_rejects_repository_and_definition_pair_leakage():
    train = records("train")
    with pytest.raises(ValueError, match="Repository"):
        validate_splits(GroupedSplit(train, train, records("test")))
    duplicate = train[0].model_copy(update={"repository_id": "test", "record_id": "other"})
    with pytest.raises(ValueError, match="Definition pair"):
        validate_splits(GroupedSplit(train, records("validation"), records("test") + [duplicate]))


def test_compares_on_same_held_out_records():
    pytest.importorskip("xgboost")
    pytest.importorskip("sklearn")

    class FixtureEncoder:
        model_id = "fixture"

        def encode(self, texts):
            return [[float(len(text)), float(text.count("sample"))] for text in texts]

    split = GroupedSplit(records("train"), records("validation"), records("test"))
    report = compare(split, encoder=FixtureEncoder(), max_false_quarantine_rate=0.0)
    assert report["splits"]["test"]["labels"] == dict.fromkeys(ChangeClass, 1)
    assert set(report["models"]) == {"structured", "structured_and_embeddings"}
    for evaluation in report["models"].values():
        assert evaluation["test"]["records"] == 4
        assert 0.0 <= evaluation["test"]["malicious_average_precision"] <= 1.0
        assert evaluation["validation"]["quarantine"]["false_positives"] == 0
