"""Bounded validation of approved invocation contracts.

Supported: the core type/size/range keywords, the ``anyOf``/``oneOf``/``allOf``/``not``
applicators, and local ``$ref`` pointers into the root ``$defs`` or ``definitions``.
References are inlined before validation under a node budget, so shared definitions
cannot multiply validation work and recursive definitions fail closed. No reference is
ever fetched. ``format`` is accepted as an annotation and not asserted, which is the
JSON Schema 2020-12 default. Regexes are never evaluated, so a contract that uses
``pattern`` or ``patternProperties`` is unsupported. Unsupported contracts fail closed
instead of becoming unvalidated tools.
"""
from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator

ANNOTATIONS = {'$schema', 'title', 'description', 'default', 'examples', 'deprecated',
               'readOnly', 'writeOnly', '$comment', 'x-mcp-header', 'format',
               'contentEncoding', 'contentMediaType', 'discriminator'}
STRING_ANNOTATIONS = {'format', 'contentEncoding', 'contentMediaType'}
SCALARS = {'type', 'enum', 'const', 'required', 'minProperties', 'maxProperties', 'minItems',
           'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum',
           'exclusiveMaximum'}
CHILDREN = {'properties', 'items', 'prefixItems', 'additionalProperties', 'not'}
BRANCHES = {'anyOf', 'oneOf', 'allOf'}
DEFINITIONS = ('$defs', 'definitions')
MAX_DEPTH = 32
MAX_NODES = 10000
# Bounds work per instance value: every branch is evaluated against the same value.
MAX_BRANCHES = 512


class _Unsupported(Exception):
    pass


def _definition(root: dict, reference: Any) -> Any:
    if not isinstance(reference, str):
        raise _Unsupported
    for container in DEFINITIONS:
        prefix = f'#/{container}/'
        if reference.startswith(prefix):
            name = reference[len(prefix):]
            if not name or '/' in name or '%' in name:
                raise _Unsupported
            name = name.replace('~1', '/').replace('~0', '~')
            table = root.get(container)
            if isinstance(table, dict) and name in table:
                return table[name]
    raise _Unsupported


def _expand(schema: Any) -> Any:
    """Inline local references and drop non-asserted annotations, within fixed budgets."""
    if not isinstance(schema, dict):
        raise _Unsupported
    root = schema
    budget = {'nodes': 0, 'branches': 0}

    def walk(node: Any, depth: int, active: tuple[str, ...]) -> Any:
        budget['nodes'] += 1
        if depth > MAX_DEPTH or budget['nodes'] > MAX_NODES:
            raise _Unsupported
        if isinstance(node, bool):
            return node
        if not isinstance(node, dict):
            raise _Unsupported
        if '$ref' in node:
            reference = node['$ref']
            if reference in active:
                raise _Unsupported  # Recursive definitions are not inlined.
            target = walk(_definition(root, reference), depth + 1, (*active, reference))
            siblings = {key: value for key, value in node.items() if key != '$ref'}
            if not set(siblings) - ANNOTATIONS:
                return target
            return {'allOf': [target, walk(siblings, depth + 1, active)]}
        unknown = set(node) - ANNOTATIONS - SCALARS - CHILDREN - BRANCHES
        if depth == 0:
            unknown -= set(DEFINITIONS)
        if unknown:
            raise _Unsupported
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key in DEFINITIONS:
                if not isinstance(value, dict):
                    raise _Unsupported
                continue  # Only reachable through $ref, which is inlined above.
            if key == '$schema' and not isinstance(value, str):
                raise _Unsupported
            if key in STRING_ANNOTATIONS:
                if not isinstance(value, str):
                    raise _Unsupported
                continue
            if key == 'discriminator':
                if not isinstance(value, dict):
                    raise _Unsupported
                continue
            if key == 'properties':
                if not isinstance(value, dict):
                    raise _Unsupported
                result[key] = {name: walk(child, depth + 1, active)
                               for name, child in value.items()}
            elif key == 'prefixItems':
                if not isinstance(value, list):
                    raise _Unsupported
                result[key] = [walk(child, depth + 1, active) for child in value]
            elif key in BRANCHES:
                if not isinstance(value, list) or not value:
                    raise _Unsupported
                budget['branches'] += len(value)
                if budget['branches'] > MAX_BRANCHES:
                    raise _Unsupported
                result[key] = [walk(child, depth + 1, active) for child in value]
            elif key in {'items', 'additionalProperties', 'not'}:
                result[key] = walk(value, depth + 1, active)
            else:
                result[key] = value
        return result

    try:
        return walk(schema, 0, ())
    except RecursionError:
        raise _Unsupported from None


def _contract(schema: Any) -> tuple[dict, bool] | None:
    try:
        expanded = _expand(schema)
    except _Unsupported:
        return None
    draft7 = 'draft-07' in schema.get('$schema', '')
    if draft7 and _contains_key(expanded, 'prefixItems'):
        return None
    return expanded, draft7


def _contains_key(schema: Any, key: str) -> bool:
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if key in node:
                return True
            for name, value in node.items():
                if name == 'properties' and isinstance(value, dict):
                    stack.extend(value.values())
                elif isinstance(value, (dict, list)) and name not in ('enum', 'const', 'default', 'examples'):
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return False


def supported_input_schema(schema: Any) -> bool:
    return _contract(schema) is not None


def valid_arguments(schema: dict, arguments: dict) -> bool:
    contract = _contract(schema)
    if contract is None:
        return False
    expanded, draft7 = contract
    validator = Draft7Validator if draft7 else Draft202012Validator
    # No format checker: format stays an annotation. References were inlined already.
    return validator(expanded).is_valid(arguments)
