from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from .canonicalize import make_snapshot
from .dataset import PairDatasetRecord
from .diff import build_delta
from .features import extract_pair_features, flatten_numeric_features
from .models import ChangeClass, RiskAssessment
from .structural_security import structural_poisoning_features

_WORD_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_OVERRIDE_PATTERNS = (
    "ignore previous",
    "ignore prior",
    "override previous",
    "disregard previous",
    "system instruction",
    "host instruction",
    "developer instruction",
)
_CONCEALMENT_PATTERNS = (
    "do not tell",
    "do not reveal",
    "do not mention",
    "keep this hidden",
    "without informing",
    "silently",
    "secretly",
)
_STEERING_PATTERNS = (
    "always use this tool",
    "use this tool instead",
    "prefer this tool",
    "never use tool",
    "must use this tool",
)
_EXFIL_PATTERNS = (
    "send results",
    "send data",
    "upload results",
    "upload data",
    "forward results",
    "external review",
    "remote endpoint",
    "callback url",
    "webhook",
)
_SENSITIVE_PARAM_TERMS = (
    "token",
    "password",
    "secret",
    "credential",
    "api_key",
    "apikey",
    "ssh_key",
    "private_key",
)

# Concept groups intentionally contain several surface forms. The resulting feature is
# relational: an authority concept must be paired with an override action and conflict/
# self-reference context. This is more robust than keying on one malicious sentence and
# less prone to flag benign occurrences of words such as "policy" or "priority".
_STRONG_OVERRIDE_ACTIONS = (
    "ignore",
    "disregard",
    "bypass",
    "override",
    "supersede",
    "takes precedence",
    "take precedence",
    "precedence over",
)
_WEAK_PRIORITY_ACTIONS = ("prioritize", "prefer")
_AUTHORITY_CONCEPTS = (
    "instruction",
    "instructions",
    "guidance",
    "policy",
    "policies",
    "rule",
    "rules",
    "guardrail",
    "guardrails",
    "host",
    "system",
    "developer",
    "controller",
    "approval",
)
_CONFLICT_CONCEPTS = (
    "conflict",
    "conflicts",
    "conflicting",
    "differs",
    "different from",
    "contrary",
    "inconsistent",
    "incompatible",
)
_SELF_DEFINITION_CONCEPTS = (
    "this definition",
    "this tool definition",
    "tool definition",
    "this tool description",
    "tool description",
    "this specification",
    "this tool specification",
    "tool specification",
    "current definition",
)


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, child in value.items():
            result.append(str(key))
            result.extend(_flatten_strings(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_flatten_strings(child))
        return result
    return [str(value)] if value is not None else []


def _text(tool: dict[str, Any]) -> str:
    return " ".join(_flatten_strings(tool))


def _count_patterns(text: str, patterns: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(lowered.count(pattern) for pattern in patterns)


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def _authority_override_concept_count(value: Any) -> int:
    """Count strings that semantically express an authority-precedence attack.

    Strong override verbs require an authority concept plus either explicit conflict or
    self-definition context. Ambiguous verbs such as "prioritize" require all three.
    This deliberately avoids treating a benign phrase like "prioritize results according
    to the user-selected policy" as a host-instruction override.
    """

    count = 0
    for raw_text in _flatten_strings(value):
        text = raw_text.lower()
        authority = _contains_any(text, _AUTHORITY_CONCEPTS)
        conflict = _contains_any(text, _CONFLICT_CONCEPTS)
        self_definition = _contains_any(text, _SELF_DEFINITION_CONCEPTS)
        strong_action = _contains_any(text, _STRONG_OVERRIDE_ACTIONS)
        weak_action = _contains_any(text, _WEAK_PRIORITY_ACTIONS)
        strong_override = authority and strong_action and (conflict or self_definition)
        weak_override = authority and conflict and self_definition and weak_action
        if strong_override or weak_override:
            count += 1
    return count


def _unicode_security_counts(text: str) -> dict[str, float]:
    format_controls = 0
    bidi_controls = 0
    zero_width = 0
    for char in text:
        category = unicodedata.category(char)
        codepoint = ord(char)
        if category == "Cf":
            format_controls += 1
        if codepoint in {
            0x202A,
            0x202B,
            0x202D,
            0x202E,
            0x202C,
            0x2066,
            0x2067,
            0x2068,
            0x2069,
        }:
            bidi_controls += 1
        if codepoint in {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}:
            zero_width += 1
    return {
        "unicode_format_controls": float(format_controls),
        "unicode_bidi_controls": float(bidi_controls),
        "unicode_zero_width": float(zero_width),
    }


def transition_text(record: PairDatasetRecord) -> str:
    """Text representation for lexical poisoning models.

    The representation keeps old and new schemas separate and explicitly exposes tokens
    introduced by the new version. This reduces the tendency to classify inherently
    sensitive but already-approved tools as poisoned merely because they contain words
    such as `token`, `send`, or `delete`.
    """

    old_json = json.dumps(record.old_tool, sort_keys=True, ensure_ascii=False)
    new_json = json.dumps(record.new_tool, sort_keys=True, ensure_ascii=False)
    old_tokens = {token.lower() for token in _WORD_RE.findall(old_json)}
    new_tokens = {token.lower() for token in _WORD_RE.findall(new_json)}
    added_tokens = " ".join(sorted(new_tokens - old_tokens))
    return f"OLD {old_json}\nNEW {new_json}\nADDED {added_tokens}"


def poisoning_security_features(record: PairDatasetRecord) -> dict[str, float]:
    """Interpretable security features for C3-vs-rest poisoning detection."""

    old = make_snapshot(
        server_id=record.server_id,
        tool=record.old_tool,
        approval_state="approved",
    )
    new = make_snapshot(server_id=record.server_id, tool=record.new_tool)
    delta = build_delta(old, new)
    features = extract_pair_features(delta)
    result = flatten_numeric_features(features)
    result.update(structural_poisoning_features(record, features))

    old_text = _text(record.old_tool)
    new_text = _text(record.new_tool)
    old_lower = old_text.lower()
    new_lower = new_text.lower()

    for name, patterns in (
        ("override", _OVERRIDE_PATTERNS),
        ("concealment", _CONCEALMENT_PATTERNS),
        ("steering", _STEERING_PATTERNS),
        ("exfil", _EXFIL_PATTERNS),
    ):
        result[f"security__{name}_added"] = float(
            max(0, _count_patterns(new_text, patterns) - _count_patterns(old_text, patterns))
        )

    result["security__authority_override_concept_added"] = float(
        max(
            0,
            _authority_override_concept_count(record.new_tool)
            - _authority_override_concept_count(record.old_tool),
        )
    )

    old_unicode = _unicode_security_counts(old_text)
    new_unicode = _unicode_security_counts(new_text)
    result.update(
        {
            f"security__new_{key}": max(0.0, value - old_unicode[key])
            for key, value in new_unicode.items()
        }
    )

    new_required = {
        str(item).lower()
        for item in (record.new_tool.get("inputSchema", {}) or {}).get("required", [])
    }
    old_required = {
        str(item).lower()
        for item in (record.old_tool.get("inputSchema", {}) or {}).get("required", [])
    }
    added_required = new_required - old_required
    result["security__sensitive_required_added"] = float(
        sum(any(term in name for term in _SENSITIVE_PARAM_TERMS) for name in added_required)
    )

    external_added = float(bool(delta.structural.urls_added))
    secrets_added = float(
        any(term in new_lower and term not in old_lower for term in _SENSITIVE_PARAM_TERMS)
    )
    transmit_added = float("transmit" in features.capability_delta.operations_added)
    disclose_added = float("disclose" in features.capability_delta.effects_added)
    broad_added = float("broad" in features.capability_delta.scopes_added)
    mutation_added = float("mutate" in features.capability_delta.effects_added)
    destroy_added = float("destroy" in features.capability_delta.effects_added)

    result["interaction__external_x_transmit"] = external_added * transmit_added
    result["interaction__external_x_secrets"] = external_added * secrets_added
    result["interaction__secrets_x_disclose"] = secrets_added * disclose_added
    result["interaction__broad_x_disclose"] = broad_added * disclose_added
    result["interaction__conceal_x_override"] = (
        result["security__concealment_added"] * result["security__override_added"]
    )
    result["interaction__steering_x_override"] = (
        result["security__steering_added"] * result["security__override_added"]
    )
    result["interaction__authority_override"] = result[
        "security__authority_override_concept_added"
    ]
    result["interaction__destructive_change"] = max(mutation_added, destroy_added)
    return result


class PoisoningDetector:
    """Hybrid binary detector for malicious MCP tool-definition drift.

    The detector combines word and character n-grams with typed structural/capability
    features. C0/C1/C2 are negative; only C3 is treated as poisoning. This distinction
    is important because legitimate capability expansion should normally trigger
    re-consent rather than be mislabeled as malicious.
    """

    def __init__(self, *, threshold: float = 0.5, class_weight: str | None = "balanced") -> None:
        self.threshold = float(threshold)
        self.class_weight = class_weight
        self._word_vectorizer = None
        self._char_vectorizer = None
        self._numeric_vectorizer = None
        self._model = None

    def fit(self, records: Iterable[PairDatasetRecord]) -> PoisoningDetector:
        try:
            from scipy.sparse import hstack
            from sklearn.feature_extraction import DictVectorizer
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
        except ImportError as exc:
            raise RuntimeError(
                "scikit-learn/scipy are required; install mcp-driftguard[ml]"
            ) from exc

        records = list(records)
        if not records:
            raise ValueError("At least one training record is required")
        y = [record.label is ChangeClass.MALICIOUS_DRIFT for record in records]
        if len(set(y)) < 2:
            raise ValueError("PoisoningDetector training requires benign and malicious records")

        texts = [transition_text(record) for record in records]
        numeric = [poisoning_security_features(record) for record in records]
        self._word_vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=1,
            max_features=35000,
            sublinear_tf=True,
            strip_accents="unicode",
        )
        self._char_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=1,
            max_features=50000,
            sublinear_tf=True,
        )
        self._numeric_vectorizer = DictVectorizer(sparse=True)
        x = hstack(
            [
                self._word_vectorizer.fit_transform(texts),
                self._char_vectorizer.fit_transform(texts),
                self._numeric_vectorizer.fit_transform(numeric),
            ],
            format="csr",
        )
        self._model = LogisticRegression(
            C=4.0,
            max_iter=4000,
            class_weight=self.class_weight,
            random_state=42,
        )
        self._model.fit(x, y)
        return self

    def _matrix(self, records: list[PairDatasetRecord]):
        if any(
            item is None
            for item in (
                self._word_vectorizer,
                self._char_vectorizer,
                self._numeric_vectorizer,
                self._model,
            )
        ):
            raise RuntimeError("PoisoningDetector has not been fitted")
        from scipy.sparse import hstack

        texts = [transition_text(record) for record in records]
        numeric = [poisoning_security_features(record) for record in records]
        return hstack(
            [
                self._word_vectorizer.transform(texts),
                self._char_vectorizer.transform(texts),
                self._numeric_vectorizer.transform(numeric),
            ],
            format="csr",
        )

    def predict_proba(self, records: Iterable[PairDatasetRecord]) -> list[float]:
        records = list(records)
        if not records:
            return []
        x = self._matrix(records)
        probabilities = self._model.predict_proba(x)
        classes = list(self._model.classes_)
        malicious_index = classes.index(True)
        return [float(row[malicious_index]) for row in probabilities]

    def predict(
        self,
        records: Iterable[PairDatasetRecord],
        *,
        threshold: float | None = None,
    ) -> list[bool]:
        cutoff = self.threshold if threshold is None else float(threshold)
        return [probability >= cutoff for probability in self.predict_proba(records)]

    def assess(
        self,
        record: PairDatasetRecord,
        *,
        threshold: float | None = None,
    ) -> RiskAssessment:
        probability = self.predict_proba([record])[0]
        cutoff = self.threshold if threshold is None else float(threshold)
        poisoned = probability >= cutoff
        reason = (
            "Hybrid poisoning model: lexical/character drift plus structural and relational "
            "security features."
        )
        return RiskAssessment(
            change_class=(
                ChangeClass.MALICIOUS_DRIFT if poisoned else ChangeClass.BENIGN_MAINTENANCE
            ),
            risk_score=round(100.0 * probability, 2),
            probabilities={"C3": round(probability, 6), "not_C3": round(1.0 - probability, 6)},
            reasons=[reason],
            recommended_action="quarantine" if poisoned else "allow_or_apply_consent_policy",
        )
