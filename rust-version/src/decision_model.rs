use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::review::ReviewError;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parameters {
    version: u8,
    id: String,
    weights: [f64; 6],
    intercept: f64,
    allow_max: f64,
    quarantine_min: f64,
}

pub struct DecisionModel {
    parameters: Parameters,
    digest: String,
}

pub struct Assessment {
    pub action: &'static str,
    pub evidence: Value,
}

impl DecisionModel {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > 16_384 {
            return Err(ReviewError("Decision model exceeds its size limit.").into());
        }
        let parameters: Parameters = serde_json::from_value(crate::input::parse(bytes)?)
            .map_err(|_| ReviewError("Invalid decision model format."))?;
        if parameters.version != 1
            || parameters.id.is_empty()
            || parameters.id.len() > 80
            || !parameters
                .id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
            || !parameters
                .weights
                .iter()
                .chain([&parameters.intercept])
                .all(|value| value.abs() <= 100.0)
            || !(0.0..=0.2).contains(&parameters.allow_max)
            || !(0.8..=1.0).contains(&parameters.quarantine_min)
        {
            return Err(ReviewError("Invalid decision model parameters.").into());
        }
        Ok(Self {
            parameters,
            digest: format!("{:x}", Sha256::digest(bytes)),
        })
    }

    pub fn assess(&self, baseline: &Value, current: &Value) -> Assessment {
        let features = features(baseline, current);
        let logit = self.parameters.intercept
            + self
                .parameters
                .weights
                .iter()
                .zip(features)
                .map(|(weight, value)| weight * value)
                .sum::<f64>();
        let score = 1.0 / (1.0 + (-logit).exp());
        let within_policy = [0, 1, 2, 3, 4]
            .into_iter()
            .all(|index| features[index] == 0.0)
            && equivalent_plain_descriptions(baseline, current);
        let action = if score >= self.parameters.quarantine_min {
            "quarantined"
        } else if score <= self.parameters.allow_max && within_policy {
            "approved"
        } else {
            "pending"
        };
        Assessment {
            action,
            evidence: json!({"id":self.parameters.id,"artifact_sha256":self.digest,
                "score":score,"action":action,"within_policy":within_policy}),
        }
    }
}

fn equivalent_plain_descriptions(old: &Value, new: &Value) -> bool {
    let normalize = |value: &Value| {
        let text = value["description"].as_str()?.trim();
        let text = text.strip_suffix(['.', '!']).unwrap_or(text);
        (!text.is_empty()
            && text
                .chars()
                .all(|character| character.is_ascii_alphanumeric() || character == ' '))
        .then(|| text.split_ascii_whitespace().collect::<Vec<_>>().join(" "))
    };
    normalize(old).is_some_and(|old| normalize(new).is_some_and(|new| old == new))
}

pub fn features(old: &Value, new: &Value) -> [f64; 6] {
    let text = |value: &Value| value["description"].as_str().unwrap_or_default().to_owned();
    let old_text = text(old);
    let new_text = text(new);
    let old_len = old_text.len();
    let new_len = new_text.len();
    let old_labels = crate::catalog::decision_operations(&old_text);
    let added = crate::catalog::decision_operations(&new_text)
        .iter()
        .any(|operation| !old_labels.contains(operation));
    let only_description = old
        .as_object()
        .zip(new.as_object())
        .is_some_and(|(old, new)| {
            old.iter()
                .filter(|(key, _)| key.as_str() != "description")
                .eq(new.iter().filter(|(key, _)| key.as_str() != "description"))
        });
    let flag = |value: bool| if value { 1.0 } else { 0.0 };
    [
        flag(old["inputSchema"] != new["inputSchema"]),
        flag(old["outputSchema"] != new["outputSchema"]),
        flag(added),
        flag(old["annotations"] != new["annotations"]),
        flag(!only_description),
        old_len.abs_diff(new_len) as f64 / old_len.max(new_len).max(1) as f64,
    ]
}
