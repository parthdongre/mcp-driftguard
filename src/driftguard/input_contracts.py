"""Bounded, reference-free validation of approved invocation contracts.

Never evaluate regexes, formats, references, or branching applicators. Unsupported
contracts fail closed instead of becoming unvalidated executable tools.
"""
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator

ANNOTATIONS = {'$schema','title','description','default','examples','deprecated','readOnly','writeOnly','$comment','x-mcp-header'}
SCALARS = {'type','enum','const','required','minProperties','maxProperties','minItems','maxItems','minLength','maxLength','minimum','maximum','exclusiveMinimum','exclusiveMaximum'}
CHILDREN = {'properties','items','prefixItems','additionalProperties'}

def supported_input_schema(schema: Any) -> bool:
    stack=[(schema,0)]; visited=0
    draft7=isinstance(schema,dict) and 'draft-07' in schema.get('$schema','')
    while stack:
        node,depth=stack.pop(); visited+=1
        if depth>32 or visited>10000: return False
        if isinstance(node,bool): continue
        if not isinstance(node,dict) or set(node)-ANNOTATIONS-SCALARS-CHILDREN: return False
        props=node.get('properties',{}); prefixes=node.get('prefixItems',[])
        if not isinstance(props,dict) or not isinstance(prefixes,list): return False
        if draft7 and 'prefixItems' in node: return False
        stack.extend((v,depth+1) for v in props.values())
        stack.extend((v,depth+1) for v in prefixes)
        stack.extend((node[k],depth+1) for k in ('items','additionalProperties') if k in node)
    return True

def valid_arguments(schema: dict, arguments: dict) -> bool:
    if not supported_input_schema(schema): return False
    validator=Draft7Validator if 'draft-07' in schema.get('$schema','') else Draft202012Validator
    return validator(schema).is_valid(arguments)
