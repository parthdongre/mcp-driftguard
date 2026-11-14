use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::error::Error;

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

/// Recognize the reference-free subset used for tool invocation.
pub fn supports(schema: &Value) -> bool {
    let draft = match schema.get("$schema").map(Value::as_str) {
        None => DRAFT_2020,
        Some(Some(uri)) => uri.strip_suffix('#').unwrap_or(uri),
        Some(None) => return false,
    };
    let draft7 = matches!(draft, DRAFT_7 | "https://json-schema.org/draft-07/schema");
    if !draft7 && draft != DRAFT_2020 {
        return false;
    }
    let mut remaining = MAX_SCHEMA_NODES;
    supports_node(schema, draft7, 0, &mut remaining)
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
        "items" | "additionalProperties" => supports_node(value, draft7, depth + 1, remaining),
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
    let mut remaining = MAX_VALIDATION_STEPS;
    supports(schema) && matches_node(schema, instance, &mut remaining) && remaining > 0
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
    let mut clean = Vec::with_capacity(content.len());
    for item in content {
        let text = item
            .get("text")
            .and_then(Value::as_str)
            .filter(|_| item["type"] == "text")
            .ok_or("Tool result must contain text items.")?;
        if joined.len().saturating_add(text.len()) > MAX_RESULT_BYTES {
            return Err("Tool result exceeds the byte limit.".into());
        }
        joined.push_str(text);
        clean.push(json!({"type":"text", "text":text}));
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
