from __future__ import annotations

import json
from typing import Any

from .models import SemanticViews, ToolSnapshot


def _stable_json(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _text(*parts: Any) -> str:
    return "\n".join(str(part).strip() for part in parts if part not in (None, ""))


def extract_semantic_views(snapshot: ToolSnapshot) -> SemanticViews:
    """Split a tool into research-relevant views before embedding or classification.

    The goal is to prevent one large JSON embedding from hiding a small but critical
    change such as a newly required token parameter or a destructive annotation.
    """

    tool = snapshot.canonical_tool
    input_schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    output_schema = tool.get("outputSchema") or tool.get("output_schema") or {}
    annotations = tool.get("annotations") or {}
    metadata = tool.get("_meta") or tool.get("meta") or tool.get("metadata") or {}

    purpose = _text(tool.get("name"), tool.get("title"), tool.get("description"))
    return SemanticViews(
        purpose=purpose,
        input_contract=_stable_json(input_schema),
        output_contract=_stable_json(output_schema),
        capability_safety=_text(_stable_json(annotations), _stable_json(metadata)),
        full_schema=_stable_json(tool),
    )
