use serde_json::{json, Value};

const OPERATIONS: &[(&str, &str)] = &[
    ("authenticate", "authenticate|login|authorize|oauth"),
    ("delete", "delete|remove|erase|destroy"),
    ("execute", "execute|run|shell|command|script"),
    ("fetch", "fetch|download|retrieve|request"),
    ("read", "read|view|inspect|search|list|query|get|find|show"),
    ("transmit", "send|upload|post|forward|transmit|publish"),
    (
        "write",
        "write|create|update|modify|edit|save|move|rename|copy|append|replace|patch",
    ),
];

const RESOURCES: &[(&str, &str)] = &[
    ("calendar", "calendar|appointment|meeting|schedule"),
    (
        "credentials",
        "credential|credentials|token|api key|password|secret|ssh key",
    ),
    (
        "database",
        "database|sql|table|tables|schema|schemas|postgres|sqlite",
    ),
    ("design", "design|figma|canvas|component"),
    ("email", "email|mail|recipient|inbox"),
    (
        "filesystem",
        "file|files|filesystem|directory|directories|path|folder|folders",
    ),
    ("messaging", "message|messages|chat|slack|teams|discord"),
    ("network", "network|url|http|https|endpoint|domain|webhook"),
    ("payment", "payment|card|bank|transaction|invoice"),
    ("process", "process|shell|command|terminal|script"),
    (
        "repository",
        "repository|repo|github|gitlab|source code|repositories|commit|branch|pull request",
    ),
];

fn normalize(value: &str) -> String {
    let mut result = String::new();
    let mut previous = ' ';
    for character in value.chars() {
        if character == '_' || character == '-' {
            result.push(' ');
        } else {
            if character.is_ascii_uppercase()
                && (previous.is_ascii_lowercase() || previous.is_ascii_digit())
            {
                result.push(' ');
            }
            result.extend(character.to_lowercase());
        }
        previous = character;
    }
    result
}

fn labels_in(text: &str, terms: &'static [(&str, &str)]) -> Vec<&'static str> {
    terms
        .iter()
        .filter_map(|(label, candidates)| {
            candidates
                .split('|')
                .any(|term| {
                    if term.contains(' ') {
                        text.contains(term)
                    } else {
                        text.split(|character: char| !character.is_alphanumeric())
                            .any(|word| word == term)
                    }
                })
                .then_some(*label)
        })
        .collect()
}

pub fn labels(definition: &Value) -> Value {
    let name = normalize(definition["name"].as_str().unwrap_or_default());
    let title = normalize(definition["title"].as_str().unwrap_or_default());
    let description = normalize(definition["description"].as_str().unwrap_or_default());
    let purpose_end = description
        .char_indices()
        .find(|(index, character)| {
            *character == '\n'
                || (matches!(character, '.' | '!' | '?')
                    && description[*index + 1..].starts_with(char::is_whitespace))
        })
        .map_or(description.len(), |(index, _)| index);
    let purpose = &description[..purpose_end];
    let operations = [&name[..], &title[..], purpose]
        .into_iter()
        .map(|value| labels_in(value, OPERATIONS))
        .find(|labels| !labels.is_empty())
        .unwrap_or_default();
    let resources = labels_in(&format!("{name} {title} {purpose}"), RESOURCES);
    json!({"operations":operations, "resources":resources})
}

pub fn decision_operations(description: &str) -> Vec<&'static str> {
    labels_in(&normalize(description), OPERATIONS)
}
