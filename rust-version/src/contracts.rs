use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::error::Error;

use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Map, Number, Value};

const DRAFT_7: &str = "http://json-schema.org/draft-07/schema";
const DRAFT_2020: &str = "https://json-schema.org/draft/2020-12/schema";
const TYPES: &[&str] = &[
    "null", "boolean", "object", "array", "number", "integer", "string",
];
const MAX_SCHEMA_DEPTH: usize = 32;
const MAX_SCHEMA_NODES: usize = 10_000;
const MAX_VALIDATION_STEPS: usize = 100_000;
const MAX_RESULT_BYTES: usize = 1_048_576;
const MAX_RESULT_ITEMS: usize = 256;
/// Bounds work per instance value: every branch is evaluated against the same value.
const MAX_BRANCHES: usize = 512;
/// Decoded media bytes per result; base64 must still fit the 1 MiB result limit.
const MAX_MEDIA_BYTES: usize = 512 * 1024;
/// Keywords with no effect on validation. A `$ref` with only these siblings is replaced.
const ANNOTATION_KEYS: &[&str] = &[
    "$schema",
    "title",
    "description",
    "default",
    "examples",
    "deprecated",
    "readOnly",
    "writeOnly",
    "$comment",
    "x-mcp-header",
    "format",
    "contentEncoding",
    "contentMediaType",
    "discriminator",
];

/// Recognize the supported subset used for tool invocation.
///
/// Local `$ref` pointers into the root `$defs` or `definitions` are inlined first under a
/// node budget, so shared definitions cannot multiply validation work and recursive ones
/// are rejected. Nothing is fetched. `format` is an annotation and is not asserted, the
/// 2020-12 default. Regexes are never evaluated, so `pattern` stays unsupported.
pub fn supports(schema: &Value) -> bool {
    contract(schema).is_some()
}

fn contract(schema: &Value) -> Option<Value> {
    let draft = match schema.get("$schema").map(Value::as_str) {
        None => DRAFT_2020,
        Some(Some(uri)) => uri.strip_suffix('#').unwrap_or(uri),
        Some(None) => return None,
    };
    let draft7 = matches!(draft, DRAFT_7 | "https://json-schema.org/draft-07/schema");
    if !draft7 && draft != DRAFT_2020 {
        return None;
    }
    let root = schema.as_object()?;
    let mut budget = Budget {
        nodes: MAX_SCHEMA_NODES,
        branches: MAX_BRANCHES,
    };
    let expanded = expand_node(schema, root, 0, &mut Vec::new(), &mut budget)?;
    let mut remaining = MAX_SCHEMA_NODES;
    supports_node(&expanded, draft7, 0, &mut remaining).then_some(expanded)
}

struct Budget {
    nodes: usize,
    branches: usize,
}

fn definition<'a>(root: &'a Map<String, Value>, reference: &str) -> Option<&'a Value> {
    ["$defs", "definitions"].iter().find_map(|container| {
        let name = reference
            .strip_prefix("#/")?
            .strip_prefix(container)?
            .strip_prefix('/')?;
        if name.is_empty() || name.contains(['/', '%']) {
            return None;
        }
        let name = name.replace("~1", "/").replace("~0", "~");
        root.get(*container)?.as_object()?.get(&name)
    })
}

/// Produce an equivalent reference-free contract without annotation-only keywords.
fn expand_node(
    node: &Value,
    root: &Map<String, Value>,
    depth: usize,
    active: &mut Vec<String>,
    budget: &mut Budget,
) -> Option<Value> {
    if depth > MAX_SCHEMA_DEPTH || !consume(&mut budget.nodes) {
        return None;
    }
    let Some(fields) = node.as_object() else {
        return node.is_boolean().then(|| node.clone());
    };
    if let Some(reference) = fields.get("$ref") {
        let reference = reference.as_str()?;
        if active.iter().any(|seen| seen == reference) {
            return None;
        }
        let target = definition(root, reference)?;
        active.push(reference.to_owned());
        let expanded = expand_node(target, root, depth + 1, active, budget);
        active.pop();
        let expanded = expanded?;
        let siblings = fields
            .iter()
            .filter(|(key, _)| *key != "$ref")
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect::<Map<_, _>>();
        if siblings
            .keys()
            .all(|key| ANNOTATION_KEYS.contains(&key.as_str()))
        {
            return Some(expanded);
        }
        let siblings = expand_node(&Value::Object(siblings), root, depth + 1, active, budget)?;
        return Some(json!({"allOf": [expanded, siblings]}));
    }
    let mut result = Map::new();
    for (key, value) in fields {
        match key.as_str() {
            "$defs" | "definitions" if depth == 0 => {
                // Reachable only through `$ref`, which is inlined above.
                value.as_object()?;
            }
            "format" | "contentEncoding" | "contentMediaType" => {
                value.as_str()?;
            }
            "discriminator" => {
                value.as_object()?;
            }
            "properties" => {
                let mut properties = Map::new();
                for (name, child) in value.as_object()? {
                    properties.insert(
                        name.clone(),
                        expand_node(child, root, depth + 1, active, budget)?,
                    );
                }
                result.insert(key.clone(), Value::Object(properties));
            }
            "prefixItems" | "anyOf" | "oneOf" | "allOf" => {
                let children = value.as_array()?;
                if key != "prefixItems" {
                    budget.branches = budget.branches.checked_sub(children.len())?;
                }
                let children = children
                    .iter()
                    .map(|child| expand_node(child, root, depth + 1, active, budget))
                    .collect::<Option<Vec<_>>>()?;
                result.insert(key.clone(), Value::Array(children));
            }
            "items" | "additionalProperties" | "not" => {
                result.insert(
                    key.clone(),
                    expand_node(value, root, depth + 1, active, budget)?,
                );
            }
            _ => {
                result.insert(key.clone(), value.clone());
            }
        }
    }
    Some(Value::Object(result))
}

fn supports_node(schema: &Value, draft7: bool, depth: usize, remaining: &mut usize) -> bool {
    if depth > MAX_SCHEMA_DEPTH || !consume(remaining) {
        return false;
    }
    let Some(fields) = schema.as_object() else {
        return schema.is_boolean();
    };
    fields.iter().all(|(key, value)| match key.as_str() {
        "$schema" => depth == 0 && value.is_string(),
        "title" | "description" | "$comment" => value.is_string(),
        "deprecated" | "readOnly" | "writeOnly" => value.is_boolean(),
        "examples" => value.is_array(),
        "default" | "const" | "x-mcp-header" => true,
        "type" => value.as_str().map_or_else(
            || unique_strings(value, false, |name| TYPES.contains(&name)),
            |name| TYPES.contains(&name),
        ),
        "enum" => value.as_array().is_some_and(|items| !items.is_empty()),
        "required" => unique_strings(value, true, |_| true),
        "minProperties" | "maxProperties" | "minItems" | "maxItems" | "minLength" | "maxLength" => {
            value
                .as_number()
                .and_then(Decimal::parse)
                .is_some_and(|number| !number.negative && number.is_integer())
        }
        "minimum" | "maximum" | "exclusiveMinimum" | "exclusiveMaximum" => {
            value.as_number().and_then(Decimal::parse).is_some()
        }
        "properties" => value.as_object().is_some_and(|properties| {
            properties
                .values()
                .all(|child| supports_node(child, draft7, depth + 1, remaining))
        }),
        "items" | "additionalProperties" | "not" => {
            supports_node(value, draft7, depth + 1, remaining)
        }
        "anyOf" | "oneOf" | "allOf" => value.as_array().is_some_and(|branches| {
            !branches.is_empty()
                && branches
                    .iter()
                    .all(|child| supports_node(child, draft7, depth + 1, remaining))
        }),
        "prefixItems" if !draft7 => value.as_array().is_some_and(|prefix| {
            !prefix.is_empty()
                && prefix
                    .iter()
                    .all(|child| supports_node(child, draft7, depth + 1, remaining))
        }),
        _ => false,
    })
}

fn unique_strings(value: &Value, allow_empty: bool, allowed: impl Fn(&str) -> bool) -> bool {
    let Some(items) = value.as_array() else {
        return false;
    };
    let mut unique = BTreeSet::new();
    (allow_empty || !items.is_empty())
        && items.iter().all(|item| {
            item.as_str()
                .is_some_and(|name| allowed(name) && unique.insert(name))
        })
}

/// Evaluate only supported contracts. The budget also bounds nested enum and const comparisons.
pub fn valid(schema: &Value, instance: &Value) -> bool {
    let Some(contract) = contract(schema) else {
        return false;
    };
    let mut remaining = MAX_VALIDATION_STEPS;
    // An exhausted budget leaves `remaining` at zero, so a `not` branch that stopped early
    // cannot turn into a pass.
    matches_node(&contract, instance, &mut remaining) && remaining > 0
}

fn matches_node(schema: &Value, instance: &Value, remaining: &mut usize) -> bool {
    if !consume(remaining) {
        return false;
    }
    if let Some(boolean) = schema.as_bool() {
        return boolean;
    }
    let fields = schema
        .as_object()
        .expect("contract checked before validation");
    if fields
        .get("type")
        .is_some_and(|kind| !matches_type(kind, instance))
        || fields
            .get("const")
            .is_some_and(|expected| !equal(expected, instance, 0, remaining))
        || fields
            .get("enum")
            .and_then(Value::as_array)
            .is_some_and(|choices| {
                !choices
                    .iter()
                    .any(|choice| equal(choice, instance, 0, remaining))
            })
    {
        return false;
    }
    let branches = |key: &str| fields.get(key).and_then(Value::as_array);
    if branches("allOf").is_some_and(|all| {
        !all.iter()
            .all(|branch| matches_node(branch, instance, remaining))
    }) || branches("anyOf").is_some_and(|any| {
        !any.iter()
            .any(|branch| matches_node(branch, instance, remaining))
    }) || branches("oneOf").is_some_and(|one| {
        let mut matched = 0;
        for branch in one {
            if matches_node(branch, instance, remaining) {
                matched += 1;
                if matched > 1 {
                    break;
                }
            }
        }
        matched != 1
    }) || fields
        .get("not")
        .is_some_and(|negated| matches_node(negated, instance, remaining))
    {
        return false;
    }
    match instance {
        Value::Object(object) => matches_object(fields, object, remaining),
        Value::Array(items) => matches_array(fields, items, remaining),
        Value::String(value) => {
            if fields.contains_key("minLength") || fields.contains_key("maxLength") {
                matches_count(fields, value.chars().count(), "minLength", "maxLength")
            } else {
                true
            }
        }
        Value::Number(value) => matches_number(fields, value),
        _ => true,
    }
}

fn matches_type(kind: &Value, instance: &Value) -> bool {
    if let Some(kinds) = kind.as_array() {
        return kinds.iter().any(|kind| matches_type(kind, instance));
    }
    match kind.as_str() {
        Some("null") => instance.is_null(),
        Some("boolean") => instance.is_boolean(),
        Some("object") => instance.is_object(),
        Some("array") => instance.is_array(),
        Some("number") => instance.is_number(),
        Some("integer") => instance
            .as_number()
            .and_then(Decimal::parse)
            .is_some_and(|n| n.is_integer()),
        Some("string") => instance.is_string(),
        _ => false,
    }
}

fn matches_object(
    fields: &Map<String, Value>,
    instance: &Map<String, Value>,
    remaining: &mut usize,
) -> bool {
    if !matches_count(fields, instance.len(), "minProperties", "maxProperties")
        || fields
            .get("required")
            .and_then(Value::as_array)
            .is_some_and(|required| {
                !required
                    .iter()
                    .all(|key| instance.contains_key(key.as_str().expect("checked property name")))
            })
    {
        return false;
    }
    let properties = fields.get("properties").and_then(Value::as_object);
    let additional = fields.get("additionalProperties");
    if properties.is_none() && additional.is_none() {
        return true;
    }
    instance.iter().all(|(key, value)| {
        properties
            .and_then(|properties| properties.get(key))
            .or(additional)
            .is_none_or(|schema| matches_node(schema, value, remaining))
    })
}

fn matches_array(fields: &Map<String, Value>, items: &[Value], remaining: &mut usize) -> bool {
    if !matches_count(fields, items.len(), "minItems", "maxItems") {
        return false;
    }
    let prefix = fields.get("prefixItems").and_then(Value::as_array);
    let rest = fields.get("items");
    if prefix.is_none() && rest.is_none() {
        return true;
    }
    items.iter().enumerate().all(|(index, value)| {
        prefix
            .and_then(|prefix| prefix.get(index))
            .or(rest)
            .is_none_or(|schema| matches_node(schema, value, remaining))
    })
}

fn matches_count(fields: &Map<String, Value>, count: usize, minimum: &str, maximum: &str) -> bool {
    if !fields.contains_key(minimum) && !fields.contains_key(maximum) {
        return true;
    }
    let count = Decimal::parse(&Number::from(count)).expect("usize is a bounded decimal");
    limit(fields, &count, minimum, |order| order != Ordering::Less)
        && limit(fields, &count, maximum, |order| order != Ordering::Greater)
}

fn matches_number(fields: &Map<String, Value>, number: &Number) -> bool {
    let limits = ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"];
    if !limits.iter().any(|key| fields.contains_key(*key)) {
        return true;
    }
    let Some(number) = Decimal::parse(number) else {
        return false;
    };
    limit(fields, &number, "minimum", |order| order != Ordering::Less)
        && limit(fields, &number, "maximum", |order| {
            order != Ordering::Greater
        })
        && limit(fields, &number, "exclusiveMinimum", |order| {
            order == Ordering::Greater
        })
        && limit(fields, &number, "exclusiveMaximum", |order| {
            order == Ordering::Less
        })
}

fn limit(
    fields: &Map<String, Value>,
    number: &Decimal,
    key: &str,
    accepts: impl Fn(Ordering) -> bool,
) -> bool {
    fields.get(key).is_none_or(|bound| {
        bound
            .as_number()
            .and_then(Decimal::parse)
            .is_some_and(|bound| accepts(number.compare(&bound)))
    })
}

fn equal(left: &Value, right: &Value, depth: usize, remaining: &mut usize) -> bool {
    if depth > 40 || !consume(remaining) {
        return false;
    }
    match (left, right) {
        (Value::Number(left), Value::Number(right)) => {
            match (Decimal::parse(left), Decimal::parse(right)) {
                (Some(left), Some(right)) => left.compare(&right) == Ordering::Equal,
                _ => false,
            }
        }
        (Value::Array(left), Value::Array(right)) => {
            left.len() == right.len()
                && left
                    .iter()
                    .zip(right)
                    .all(|(left, right)| equal(left, right, depth + 1, remaining))
        }
        (Value::Object(left), Value::Object(right)) => {
            left.len() == right.len()
                && left.iter().all(|(key, left)| {
                    right
                        .get(key)
                        .is_some_and(|right| equal(left, right, depth + 1, remaining))
                })
        }
        _ => left == right,
    }
}

fn consume(remaining: &mut usize) -> bool {
    match remaining.checked_sub(1) {
        Some(left) => {
            *remaining = left;
            true
        }
        None => false,
    }
}

/// A finite JSON number as significant digits and a base-ten scale. Never round
/// through f64 before enforcing an approved numeric bound.
struct Decimal {
    negative: bool,
    digits: Vec<u8>,
    scale: i32,
}

impl Decimal {
    fn parse(value: &Number) -> Option<Self> {
        let encoded = value.as_str();
        if encoded.len() > 4096 {
            return None;
        }
        let negative = encoded.starts_with('-');
        let absolute = encoded.strip_prefix('-').unwrap_or(encoded);
        let (mantissa, exponent) = match absolute.split_once(['e', 'E']) {
            Some((mantissa, exponent)) => (mantissa, exponent.parse::<i32>().ok()?),
            None => (absolute, 0),
        };
        if !(-10_000..=10_000).contains(&exponent) {
            return None;
        }
        let (whole, fraction) = mantissa.split_once('.').unwrap_or((mantissa, ""));
        let digits = whole
            .bytes()
            .chain(fraction.bytes())
            .skip_while(|digit| *digit == b'0')
            .collect::<Vec<_>>();
        let end = digits.iter().rposition(|digit| *digit != b'0');
        let Some(end) = end else {
            return Some(Self {
                negative: false,
                digits: Vec::new(),
                scale: 0,
            });
        };
        let scale = exponent - fraction.len() as i32 + (digits.len() - end - 1) as i32;
        let mut digits = digits;
        digits.truncate(end + 1);
        Some(Self {
            negative,
            digits,
            scale,
        })
    }

    fn is_integer(&self) -> bool {
        self.scale >= 0
    }

    fn compare(&self, other: &Self) -> Ordering {
        if self.negative != other.negative {
            return other.negative.cmp(&self.negative);
        }
        let absolute = match (self.digits.is_empty(), other.digits.is_empty()) {
            (true, true) => Ordering::Equal,
            (true, false) => Ordering::Less,
            (false, true) => Ordering::Greater,
            (false, false) => (self.digits.len() as i32 + self.scale)
                .cmp(&(other.digits.len() as i32 + other.scale))
                .then_with(|| self.digits.cmp(&other.digits)),
        };
        if self.negative {
            absolute.reverse()
        } else {
            absolute
        }
    }
}

/// Forward only bounded text and structured content validated against the approved schema.
pub fn check_result(result: Value, output: Option<&Value>) -> Result<Value, Box<dyn Error>> {
    let content = result
        .get("content")
        .and_then(Value::as_array)
        .filter(|items| items.len() <= MAX_RESULT_ITEMS)
        .ok_or("Tool result has invalid content or exceeds the item limit.")?;
    let is_error = result
        .get("isError")
        .map(Value::as_bool)
        .unwrap_or(Some(false))
        .ok_or("Tool result has an invalid isError flag.")?;
    let mut joined = String::new();
    let mut media = 0;
    let mut clean = Vec::with_capacity(content.len());
    for item in content {
        let kind = item["type"].as_str().unwrap_or_default();
        if kind == "text" {
            let text = item
                .get("text")
                .and_then(Value::as_str)
                .ok_or("Tool result text item is invalid.")?;
            if joined.len().saturating_add(text.len()) > MAX_RESULT_BYTES {
                return Err("Tool result exceeds the byte limit.".into());
            }
            joined.push_str(text);
            clean.push(json!({"type":"text", "text":text}));
            continue;
        }
        let Some(decoded) = media_bytes(item)? else {
            return Err("Only text, image and audio tool results are supported.".into());
        };
        media += decoded.len();
        if media > MAX_MEDIA_BYTES {
            return Err("Tool result media exceeds the byte limit.".into());
        }
        if contains_private_key(&String::from_utf8_lossy(&decoded)) {
            return Err("Tool result media contains private key material.".into());
        }
        clean.push(json!({"type":kind, "data":item["data"],
            "mimeType":item["mimeType"].as_str().unwrap_or_default().to_ascii_lowercase()}));
    }
    if contains_private_key(&joined) {
        return Err("Tool result contains private key material.".into());
    }
    let mut forwarded = json!({"content":clean, "isError":is_error});
    if let Some(schema) = output {
        if !schema.is_object()
            || schema.get("type").is_some_and(|kind| kind != "object")
            || !supports(schema)
        {
            return Err("Tool output contract is unsupported.".into());
        }
        if !is_error || result.get("structuredContent").is_some() {
            let structured = &result["structuredContent"];
            if !structured.is_object() || !valid(schema, structured) {
                return Err("Structured result violates the approved output contract.".into());
            }
            if contains_private_key(&serde_json::to_string(structured)?) {
                return Err("Structured result contains private key material.".into());
            }
            forwarded["structuredContent"] = structured.clone();
        }
    }
    if serde_json::to_vec(&forwarded)?.len() > MAX_RESULT_BYTES {
        return Err("Tool result exceeds the byte limit.".into());
    }
    Ok(forwarded)
}

/// Decoded bytes of an allowed image or audio item, or `None` for other item types.
/// SVG is excluded because it can carry script.
fn media_bytes(item: &Value) -> Result<Option<Vec<u8>>, Box<dyn Error>> {
    let allowed: &[&str] = match item["type"].as_str() {
        Some("image") => &["image/png", "image/jpeg", "image/gif", "image/webp"],
        Some("audio") => &[
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/ogg",
            "audio/webm",
            "audio/flac",
        ],
        _ => return Ok(None),
    };
    let mime = item["mimeType"].as_str().map(str::to_ascii_lowercase);
    if !mime.is_some_and(|mime| allowed.contains(&mime.as_str())) {
        return Err("Tool result media type is not allowed.".into());
    }
    let data = item["data"]
        .as_str()
        .filter(|data| data.len() <= MAX_MEDIA_BYTES / 3 * 4 + 4)
        .ok_or("Tool result media is invalid or exceeds the byte limit.")?;
    Ok(Some(STANDARD.decode(data).map_err(|_| {
        Box::<dyn Error>::from("Tool result media is not valid base64.")
    })?))
}

/// Decoded media as text, so credential checks also cover values hidden in binary data.
pub(crate) fn media_text(result: &Value) -> String {
    result["content"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|item| media_bytes(item).ok().flatten())
        .map(|bytes| String::from_utf8_lossy(&bytes).into_owned())
        .collect()
}

pub(crate) fn contains_private_key(value: &str) -> bool {
    [
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN DSA PRIVATE KEY-----",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----",
    ]
    .iter()
    .any(|marker| value.contains(marker))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn supports_objects_arrays_and_unicode_counts() {
        let schema = json!({
            "type": "object", "required": ["items"], "additionalProperties": false,
            "properties": {"items": {"type": "array", "prefixItems": [
                {"type": "string", "maxLength": 1}, {"type": "integer", "minimum": 1}
            ], "items": false, "minItems": 2}}
        });
        assert!(supports(&schema));
        assert!(valid(&schema, &json!({"items": ["📚", 2]})));
        assert!(!valid(&schema, &json!({"items": ["éa", 2]})));
        assert!(!valid(&schema, &json!({"items": ["é", 2, null]})));
        assert!(!valid(&schema, &json!({"items": ["é", 2], "extra": true})));
    }

    #[test]
    fn rejects_unsupported_or_malformed_contracts() {
        for schema in [
            json!({"$ref": "https://example.com/schema.json"}),
            json!({"properties": {"name": {"pattern": "x"}}}),
            json!({"additionalProperties": 1}),
            json!({"required": ["name", "name"]}),
            json!({"type": ["string", "invalid"]}),
            json!({"minLength": -1}),
            json!({"minItems": 1.5}),
            json!({"$schema":"http://json-schema.org/draft-07/schema#", "prefixItems":[true]}),
        ] {
            assert!(!supports(&schema), "{schema}");
            assert!(!valid(&schema, &json!({})), "{schema}");
        }
    }

    #[test]
    fn validates_pydantic_and_zod_generated_contracts() {
        let pydantic = json!({
            "type": "object", "required": ["query"],
            "$defs": {
                "Color": {"enum": ["red", "green"], "type": "string"},
                "Filter": {"type": "object", "required": ["color"], "additionalProperties": false,
                    "properties": {"color": {"$ref": "#/$defs/Color"},
                                   "since": {"type": "string", "format": "date-time"}}}
            },
            "properties": {
                "query": {"type": "string"},
                "limit": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}], "default": null},
                "filter": {"anyOf": [{"$ref": "#/$defs/Filter"}, {"type": "null"}]}
            }
        });
        assert!(supports(&pydantic));
        assert!(valid(&pydantic, &json!({"query": "x"})));
        assert!(valid(
            &pydantic,
            &json!({"query": "x", "limit": null, "filter": {"color": "red"}})
        ));
        assert!(valid(
            &pydantic,
            &json!({"query": "x", "filter": {"color": "red", "since": "?"}})
        ));
        assert!(!valid(&pydantic, &json!({"query": "x", "limit": 0})));
        assert!(!valid(
            &pydantic,
            &json!({"query": "x", "filter": {"color": "blue"}})
        ));
        assert!(!valid(
            &pydantic,
            &json!({"query": "x", "filter": {"color": "red", "extra": 1}})
        ));
        let zod = json!({
            "$schema": "http://json-schema.org/draft-07/schema#", "type": "object",
            "definitions": {"Mode": {"type": "string", "enum": ["fast", "full"]}},
            "properties": {"url": {"type": "string", "format": "uri"},
                "mode": {"$ref": "#/definitions/Mode", "description": "Scan depth"},
                "tags": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}},
            "required": ["url"], "additionalProperties": false
        });
        assert!(supports(&zod));
        assert!(valid(
            &zod,
            &json!({"url": "https://a", "mode": "fast", "tags": ["a", 1]})
        ));
        assert!(!valid(&zod, &json!({"url": "https://a", "mode": "slow"})));
        assert!(!valid(&zod, &json!({"url": "https://a", "tags": [true]})));
    }

    #[test]
    fn one_of_requires_exactly_one_match_and_not_inverts() {
        let one =
            json!({"properties": {"v": {"oneOf": [{"type": "integer"}, {"type": "number"}]}}});
        assert!(valid(&one, &json!({"v": 1.5})));
        assert!(!valid(&one, &json!({"v": 1})));
        let negated = json!({"properties": {"v": {"not": {"type": "string"}}}});
        assert!(valid(&negated, &json!({"v": 1})));
        assert!(!valid(&negated, &json!({"v": "s"})));
        let combined = json!({"$defs": {"S": {"type": "string"}},
            "properties": {"v": {"$ref": "#/$defs/S", "maxLength": 2}}});
        assert!(valid(&combined, &json!({"v": "ab"})));
        assert!(!valid(&combined, &json!({"v": "abc"})));
    }

    #[test]
    fn unsafe_references_and_unbounded_branches_fail_closed() {
        let mut levels = Map::new();
        for level in 0..30 {
            let next = format!("#/$defs/L{}", level + 1);
            levels.insert(
                format!("L{level}"),
                json!({"anyOf": [{"$ref": next}, {"$ref": next}]}),
            );
        }
        levels.insert("L30".into(), json!({"type": "string"}));
        let wide: Vec<Value> = (0..=MAX_BRANCHES)
            .map(|value| json!({"const": value}))
            .collect();
        for schema in [
            json!({"$defs": levels, "properties": {"v": {"$ref": "#/$defs/L0"}}}),
            json!({"$ref": "#/$defs/missing", "$defs": {}}),
            json!({"$ref": "#/$defs/a/b", "$defs": {"a": {"b": {}}}}),
            json!({"$ref": "#/$defs/%61", "$defs": {"a": {}}}),
            json!({"$defs": {"N": {"properties": {"c": {"$ref": "#/$defs/N"}}}},
                   "properties": {"r": {"$ref": "#/$defs/N"}}}),
            json!({"properties": {"v": {"$defs": {}}}}),
            json!({"properties": {"v": {"format": 1}}}),
            json!({"anyOf": []}),
            json!({"if": {}, "then": {}}),
            json!({"properties": {"v": {"anyOf": wide}}}),
        ] {
            assert!(!supports(&schema), "{schema}");
            assert!(!valid(&schema, &json!({})), "{schema}");
        }
    }

    #[test]
    fn forwards_allowed_media_and_rejects_unsafe_media() {
        let png = STANDARD.encode(b"\x89PNG\r\n\x1a\n");
        let result = json!({"content": [
            {"type": "image", "data": png, "mimeType": "IMAGE/PNG", "annotations": {"x": 1}},
            {"type": "audio", "data": "UklGRg==", "mimeType": "audio/wav"}
        ]});
        assert_eq!(
            check_result(result, None).unwrap()["content"],
            json!([{"type": "image", "data": png, "mimeType": "image/png"},
                   {"type": "audio", "data": "UklGRg==", "mimeType": "audio/wav"}])
        );
        let key = STANDARD.encode(b"\x89PNG-----BEGIN PRIVATE KEY-----");
        let large = STANDARD.encode(vec![0_u8; MAX_MEDIA_BYTES + 1]);
        for item in [
            json!({"type": "image", "data": "PHN2Zz4=", "mimeType": "image/svg+xml"}),
            json!({"type": "image", "data": "not base64!", "mimeType": "image/png"}),
            json!({"type": "audio", "data": "AAAA", "mimeType": "image/png"}),
            json!({"type": "image", "data": key, "mimeType": "image/png"}),
            json!({"type": "image", "data": large, "mimeType": "image/png"}),
            json!({"type": "resource_link", "uri": "file:///secret"}),
        ] {
            assert!(check_result(json!({"content": [item]}), None).is_err());
        }
        let hidden = json!({"content": [{"type": "image", "mimeType": "image/png",
            "data": STANDARD.encode(b"token-123")}]});
        assert_eq!(media_text(&hidden), "token-123");
    }

    #[test]
    fn compares_numbers_exactly_with_nested_enum_values() {
        let schema: Value = serde_json::from_str(
            r#"{"type":"integer","exclusiveMinimum":9007199254740993,"maximum":9007199254740994}"#,
        )
        .unwrap();
        assert!(!valid(&schema, &json!(9007199254740993_u64)));
        assert!(valid(&schema, &json!(9007199254740994_u64)));
        assert!(!valid(&schema, &json!(9007199254740995_u64)));
        let schema = json!({"const":{"nested":[2.0, true]}});
        assert!(valid(&schema, &json!({"nested":[2, true]})));
        assert!(!valid(&schema, &json!({"nested":[2, 1]})));
        let schema = json!({"type":"number","maximum":-0.123});
        let too_large: Value = serde_json::from_str("-0.122999999999999999999999999").unwrap();
        assert!(!valid(&schema, &too_large));
    }

    #[test]
    fn checks_structured_output_and_filters_extra_fields() {
        let schema = json!({"properties":{"value":{"type":"integer"}},"required":["value"]});
        let result = json!({
            "content":[{"type":"text","text":"read","annotations":{"secret": "drop"}}],
            "structuredContent":{"value":2},"metadata":"drop"
        });
        let clean = check_result(result.clone(), Some(&schema)).unwrap();
        assert_eq!(
            clean,
            json!({
                "content":[{"type":"text","text":"read"}],"isError":false,"structuredContent":{"value":2}
            })
        );
        assert!(check_result(result, None)
            .unwrap()
            .get("structuredContent")
            .is_none());
        assert!(check_result(json!({"content":[]}), Some(&schema)).is_err());
        assert!(check_result(json!({"content":[],"isError":true}), Some(&schema)).is_ok());
        assert!(check_result(
            json!({"content":[],"isError":true,"structuredContent":{"value":"bad"}}),
            Some(&schema)
        )
        .is_err());
        assert!(check_result(json!({"content":[{"type":"image","data":"bad"}]}), None).is_err());
    }

    #[test]
    fn blocks_key_material_across_text_items_and_in_structured_output() {
        let split = json!({"content":[{"type":"text","text":"-----BEGIN RSA"},
                                      {"type":"text","text":" PRIVATE KEY-----"}]});
        assert!(check_result(split, None).is_err());
        let structured = json!({"content":[],"structuredContent":{
            "-----BEGIN OPENSSH PRIVATE KEY-----":"bad"
        }});
        assert!(check_result(structured, Some(&json!({}))).is_err());
    }
}
