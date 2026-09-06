from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Protocol


class SourceToolExtractor(Protocol):
    def extract(self, text: str) -> list[dict[str, Any]]: ...


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _annotation_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _json_schema_for_annotation(node: ast.AST | None) -> dict[str, Any]:
    if node is None:
        return {}

    if isinstance(node, ast.Name):
        mapping = {
            "str": {"type": "string"},
            "int": {"type": "integer"},
            "float": {"type": "number"},
            "bool": {"type": "boolean"},
            "dict": {"type": "object"},
            "list": {"type": "array"},
        }
        return dict(mapping.get(node.id, {}))

    if isinstance(node, ast.Subscript):
        base = _annotation_name(node.value).split(".")[-1]
        if base in {"list", "List", "Sequence", "set", "Set", "tuple", "Tuple"}:
            return {
                "type": "array",
                "items": _json_schema_for_annotation(node.slice),
            }
        if base in {"dict", "Dict", "Mapping"}:
            return {"type": "object"}
        if base in {"Optional"}:
            return _json_schema_for_annotation(node.slice)
        if base in {"Literal"}:
            values: list[Any] = []
            target = node.slice
            elements = target.elts if isinstance(target, ast.Tuple) else [target]
            for item in elements:
                value = _literal(item)
                if value is not None:
                    values.append(value)
            schema: dict[str, Any] = {"enum": values}
            if values and all(isinstance(value, str) for value in values):
                schema["type"] = "string"
            return schema

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left_name = _annotation_name(node.left)
        right_name = _annotation_name(node.right)
        if left_name in {"None", "NoneType"}:
            return _json_schema_for_annotation(node.right)
        if right_name in {"None", "NoneType"}:
            return _json_schema_for_annotation(node.left)
        return {"anyOf": [_json_schema_for_annotation(node.left), _json_schema_for_annotation(node.right)]}

    return {}


def _decorator_info(node: ast.AST) -> tuple[bool, dict[str, Any]]:
    target = node.func if isinstance(node, ast.Call) else node
    is_tool = isinstance(target, ast.Attribute) and target.attr == "tool"
    if not is_tool:
        return False, {}

    kwargs: dict[str, Any] = {}
    if isinstance(node, ast.Call):
        for keyword in node.keywords:
            if keyword.arg:
                value = _literal(keyword.value)
                if value is not None:
                    kwargs[keyword.arg] = value
    return True, kwargs


def _parameter_schema(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    args = list(function.args.posonlyargs) + list(function.args.args)
    defaults = [None] * (len(args) - len(function.args.defaults)) + list(function.args.defaults)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for arg, default in zip(args, defaults, strict=True):
        annotation_text = _annotation_name(arg.annotation)
        if arg.arg in {"self", "cls", "ctx", "context"} or annotation_text.endswith("Context"):
            continue
        schema = _json_schema_for_annotation(arg.annotation)
        if default is not None:
            value = _literal(default)
            if value is not None:
                schema["default"] = value
        else:
            required.append(arg.arg)
        properties[arg.arg] = schema

    for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True):
        annotation_text = _annotation_name(arg.annotation)
        if arg.arg in {"ctx", "context"} or annotation_text.endswith("Context"):
            continue
        schema = _json_schema_for_annotation(arg.annotation)
        if default is not None:
            value = _literal(default)
            if value is not None:
                schema["default"] = value
        else:
            required.append(arg.arg)
        properties[arg.arg] = schema

    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


@dataclass(frozen=True)
class PythonDecoratorToolExtractor:
    """Statically extract common `@mcp.tool()` definitions from Python source.

    The extractor never imports or executes the source. The inferred input schema is
    intentionally conservative and supports common primitive annotations only.
    """

    def extract(self, text: str) -> list[dict[str, Any]]:
        tree = ast.parse(text)
        tools: list[dict[str, Any]] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorator_kwargs: dict[str, Any] | None = None
            for decorator in node.decorator_list:
                is_tool, kwargs = _decorator_info(decorator)
                if is_tool:
                    decorator_kwargs = kwargs
                    break
            if decorator_kwargs is None:
                continue

            name = decorator_kwargs.get("name") or node.name
            description = decorator_kwargs.get("description") or ast.get_docstring(node) or ""
            tool: dict[str, Any] = {
                "name": str(name),
                "description": str(description),
                "inputSchema": _parameter_schema(node),
            }
            if "title" in decorator_kwargs:
                tool["title"] = decorator_kwargs["title"]
            if isinstance(decorator_kwargs.get("annotations"), dict):
                tool["annotations"] = decorator_kwargs["annotations"]
            tools.append(tool)

        return tools
