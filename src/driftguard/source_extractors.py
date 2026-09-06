from __future__ import annotations

import ast
import re
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
    return ast.unparse(node)


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
        return {
            "anyOf": [
                _json_schema_for_annotation(node.left),
                _json_schema_for_annotation(node.right),
            ]
        }

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
    """Statically extract common `@mcp.tool()` definitions from Python source."""

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


_REGISTER_TOOL_RE = re.compile(r"\b[A-Za-z_$][\w$]*\.registerTool\s*\(")


def _balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    if start >= len(text) or text[start] != opener:
        raise ValueError(f"Expected {opener!r} at position {start}")
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    raise ValueError(f"Unterminated {opener}{closer} block")


def _split_top_level(text: str, delimiter: str = ",") -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    round_depth = 0
    square_depth = 0
    curly_depth = 0

    for index, char in enumerate(text):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "(":
            round_depth += 1
        elif char == ")":
            round_depth -= 1
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth -= 1
        elif char == "{":
            curly_depth += 1
        elif char == "}":
            curly_depth -= 1
        elif (
            char == delimiter
            and round_depth == 0
            and square_depth == 0
            and curly_depth == 0
        ):
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _js_string(expression: str) -> str | None:
    value = expression.strip()
    if len(value) < 2 or value[0] not in {"'", '"', "`"} or value[-1] != value[0]:
        return None
    if value[0] == "`" and "${" in value:
        return None
    inner = value[1:-1]
    return inner.replace(f"\\{value[0]}", value[0]).replace("\\n", "\n")


def _object_entries(expression: str) -> dict[str, str]:
    value = expression.strip()
    if not value.startswith("{"):
        return {}
    try:
        body, _ = _balanced(value, 0, "{", "}")
    except ValueError:
        return {}

    entries: dict[str, str] = {}
    for part in _split_top_level(body):
        pieces = _split_top_level(part, delimiter=":")
        if len(pieces) < 2:
            continue
        key = pieces[0].strip().strip("'\"`")
        entries[key] = ":".join(pieces[1:]).strip()
    return entries


def _simple_js_value(expression: str) -> Any:
    text = expression.strip()
    string_value = _js_string(text)
    if string_value is not None:
        return string_value
    if text == "true":
        return True
    if text == "false":
        return False
    if text in {"null", "undefined"}:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def _zod_parameter_schema(expression: str) -> tuple[dict[str, Any], bool]:
    value = expression.strip()
    required = ".optional(" not in value and ".optional()" not in value and ".default(" not in value
    schema: dict[str, Any] = {}

    if "z.string(" in value or "z.string()" in value:
        schema["type"] = "string"
    elif "z.number(" in value or "z.number()" in value:
        schema["type"] = "number"
    elif "z.boolean(" in value or "z.boolean()" in value:
        schema["type"] = "boolean"
    elif "z.bigint(" in value or "z.bigint()" in value:
        schema["type"] = "integer"
    elif "z.array(" in value:
        schema["type"] = "array"
    elif "z.object(" in value:
        schema["type"] = "object"

    enum_match = re.search(r"z\.enum\s*\(\s*\[([^\]]*)\]", value, flags=re.DOTALL)
    if enum_match:
        enum_values = [
            item
            for raw in _split_top_level(enum_match.group(1))
            if (item := _js_string(raw)) is not None
        ]
        if enum_values:
            schema["type"] = "string"
            schema["enum"] = enum_values

    description_match = re.search(
        r"\.describe\s*\(\s*(['\"`])((?:\\.|(?!\1).)*)\1\s*\)",
        value,
        flags=re.DOTALL,
    )
    if description_match:
        schema["description"] = description_match.group(2)

    default_match = re.search(r"\.default\s*\(([^)]*)\)", value, flags=re.DOTALL)
    if default_match:
        default_value = _simple_js_value(default_match.group(1))
        if default_value is not None:
            schema["default"] = default_value

    return schema, required


def _typescript_input_schema(expression: str) -> dict[str, Any]:
    value = expression.strip()
    object_text: str | None = None
    zod_index = value.find("z.object")
    if zod_index >= 0:
        open_paren = value.find("(", zod_index)
        if open_paren >= 0:
            try:
                content, _ = _balanced(value, open_paren, "(", ")")
                object_text = content.strip()
            except ValueError:
                object_text = None
    elif value.startswith("{"):
        object_text = value

    if not object_text:
        return {"type": "object", "properties": {}}

    entries = _object_entries(object_text)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter_expression in entries.items():
        schema, is_required = _zod_parameter_schema(parameter_expression)
        properties[name] = schema
        if is_required:
            required.append(name)

    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result


def _typescript_annotations(expression: str) -> dict[str, Any]:
    annotations: dict[str, Any] = {}
    for key, value in _object_entries(expression).items():
        parsed = _simple_js_value(value)
        if parsed is not None:
            annotations[key] = parsed
    return annotations


@dataclass(frozen=True)
class TypeScriptRegisterToolExtractor:
    """Conservatively extract common official-SDK `server.registerTool(...)` calls.

    This parser is intentionally narrow: it reads literal tool names/configuration and
    common Zod input schemas without evaluating TypeScript or JavaScript. Dynamic names,
    computed configuration, imported schema variables, and arbitrary expressions are
    skipped or represented with an empty/partial schema rather than executed.
    """

    def extract(self, text: str) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for match in _REGISTER_TOOL_RE.finditer(text):
            open_paren = text.find("(", match.start())
            try:
                call_body, _ = _balanced(text, open_paren, "(", ")")
            except ValueError:
                continue
            args = _split_top_level(call_body)
            if len(args) < 2:
                continue
            name = _js_string(args[0])
            if name is None:
                continue
            config = _object_entries(args[1])
            if not config:
                continue

            description = _js_string(config.get("description", "")) or ""
            tool: dict[str, Any] = {
                "name": name,
                "description": description,
                "inputSchema": _typescript_input_schema(config.get("inputSchema", "")),
            }
            title = _js_string(config.get("title", ""))
            if title is not None:
                tool["title"] = title
            annotations_expression = config.get("annotations")
            if annotations_expression:
                annotations = _typescript_annotations(annotations_expression)
                if annotations:
                    tool["annotations"] = annotations
            tools.append(tool)
        return tools
