use std::fmt;

use serde::de::{self, MapAccess, Visitor};
use serde::Deserializer;
use serde_json::{value::RawValue, Map, Value};

struct ObjectVisitor(usize);

impl<'de> Visitor<'de> for ObjectVisitor {
    type Value = Value;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a JSON object with unique keys")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = Map::new();
        while let Some((key, raw)) = map.next_entry::<String, &RawValue>()? {
            let value = parse_value(raw.get(), self.0 + 1).map_err(de::Error::custom)?;
            if values.insert(key, value).is_some() {
                return Err(de::Error::custom("Duplicate JSON object key"));
            }
        }
        Ok(Value::Object(values))
    }
}

pub fn parse(input: &[u8]) -> serde_json::Result<Value> {
    let raw: &RawValue = serde_json::from_slice(input)?;
    parse_value(raw.get(), 0)
}

fn parse_value(input: &str, depth: usize) -> serde_json::Result<Value> {
    if depth > 40 {
        return Err(de::Error::custom("JSON nesting limit exceeded"));
    }
    match input.as_bytes().first() {
        Some(b'{') => {
            serde_json::Deserializer::from_str(input).deserialize_map(ObjectVisitor(depth))
        }
        Some(b'[') => serde_json::from_str::<Vec<&RawValue>>(input)?
            .into_iter()
            .map(|raw| parse_value(raw.get(), depth + 1))
            .collect::<serde_json::Result<Vec<_>>>()
            .map(Value::Array),
        _ => serde_json::from_str(input),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn rejects_duplicate_keys_at_any_depth() {
        assert!(parse(br#"{"action":"overview","action":"approve"}"#).is_err());
        assert!(parse(br#"{"tools":[{"description":"A","description":"B"}]}"#).is_err());
        assert_eq!(
            parse(br#"{"tools":[{"x":[null,true,1,2.5]}]}"#).unwrap(),
            json!({"tools":[{"x":[null,true,1,2.5]}]})
        );
    }

    #[test]
    fn preserves_distinct_large_numbers() {
        let first = parse(br#"{"n":18446744073709551616}"#).unwrap();
        let second = parse(br#"{"n":18446744073709551617}"#).unwrap();
        assert_ne!(first["n"], second["n"]);
        assert_eq!(second.to_string(), r#"{"n":18446744073709551617}"#);
        assert_eq!(
            parse(br#"{"$serde_json::private::Number":"42"}"#).unwrap(),
            json!({"$serde_json::private::Number":"42"})
        );
    }
}
