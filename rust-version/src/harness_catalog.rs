use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{json, Value};

use crate::discovery::Profile;
use crate::gateway::Upstream;
use crate::harness::CatalogConfig;
use crate::review::{ReviewError, ReviewStore};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const SOURCE_TIMEOUT: Duration = Duration::from_secs(10);
const RUN_TIMEOUT: Duration = Duration::from_secs(75);
const MAX_SOURCES: usize = 48;

pub(crate) fn configured_name(name: &str) -> bool {
    // Names are passed to `codex mcp login <name>`; a leading dash would parse as a flag.
    !name.is_empty()
        && !name.starts_with('-')
        && name.len() <= 128
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
        && !matches!(name, "driftguard" | "driftguard-rust")
}

pub(crate) fn routed_entry(settings: &Value) -> bool {
    let flat = settings["command"].as_array();
    let command = flat
        .and_then(|argv| argv.first())
        .or_else(|| settings.get("command"));
    let args = flat
        .and_then(|argv| argv.get(1..))
        .or_else(|| settings["args"].as_array().map(Vec::as_slice));
    args.is_some_and(|args| {
        matches!(args.len(), 5 | 7)
            && args[0] == "--db"
            && args[2] == "serve"
            && (args[3] == "--route" || args[3] == "--registered")
    }) && command
        .and_then(Value::as_str)
        .and_then(|cmd| Path::new(cmd).file_stem())
        .is_some_and(|stem| stem == "driftguard-rust")
}

fn has_headers(value: &Value) -> bool {
    !value.is_null()
        && value != false
        && !value.as_object().is_some_and(|headers| headers.is_empty())
}

pub(crate) fn configured_profile(settings: &Value, name: &str, home: &Path) -> Result<Value> {
    if !settings.is_object()
        || settings
            .get("enabled")
            .is_some_and(|value| !value.is_boolean())
    {
        return Err(ReviewError("The MCP server configuration is invalid.").into());
    }
    let command = settings.get("command");
    let endpoint = settings.get("url").or_else(|| settings.get("httpUrl"));
    if let Some(endpoint) = endpoint.filter(|_| command.is_none()) {
        if settings["type"] == "sse"
            || (settings.get("url").is_some() && settings.get("httpUrl").is_some())
            || ["headers", "http_headers", "env_http_headers", "oauth"]
                .iter()
                .any(|key| has_headers(&settings[*key]))
        {
            return Err(ReviewError(
                "This server uses client-specific authentication or transport.",
            )
            .into());
        }
        let mut profile = json!({"server_id":name, "transport":"http", "url":endpoint,
            "timeout_seconds":SOURCE_TIMEOUT.as_secs()});
        if let Some(token) = settings.get("bearer_token_env_var") {
            if !token.is_string() {
                return Err(ReviewError("The bearer environment reference is invalid.").into());
            }
            profile["auth_token_env"] = token.clone();
        }
        crate::http::validate_endpoint(
            endpoint
                .as_str()
                .ok_or(ReviewError("Expected an MCP endpoint."))?,
        )?;
        return Ok(profile);
    }
    if endpoint.is_some() || command.is_none() {
        return Err(ReviewError("This server uses a client-specific MCP configuration.").into());
    }
    let mut argv = match command {
        Some(Value::String(command)) => vec![json!(command)],
        Some(Value::Array(argv)) if settings["type"] == "local" && !argv.is_empty() => argv.clone(),
        _ => return Err(ReviewError("Expected a configured MCP executable.").into()),
    };
    if let Some(args) = settings.get("args") {
        argv.extend(
            args.as_array()
                .ok_or(ReviewError("Expected configured MCP arguments."))?
                .iter()
                .cloned(),
        );
    }
    if argv.iter().any(|arg| {
        arg.as_str()
            .is_some_and(|text| text.contains("${") || text.contains("{env:"))
    }) {
        return Err(ReviewError("The MCP command requires client-specific expansion.").into());
    }
    if argv
        .first()
        .and_then(Value::as_str)
        .and_then(|cmd| Path::new(cmd).file_stem())
        .and_then(|stem| stem.to_str())
        .is_some_and(|stem| stem == "driftguard-rust" || stem == "driftguard-engine")
        && argv.iter().any(|arg| arg == "serve" || arg == "gateway")
    {
        return Err(ReviewError("This entry is already a DriftGuard gateway.").into());
    }
    let cwd = match settings.get("cwd") {
        Some(value) => PathBuf::from(
            value
                .as_str()
                .ok_or(ReviewError("Expected a configured working directory."))?,
        ),
        None => home.to_path_buf(),
    };
    let mut profile = json!({"server_id":name, "argv":argv, "cwd":cwd, "timeout_seconds":SOURCE_TIMEOUT.as_secs()});
    if let Some(vars) = settings.get("env_vars") {
        profile["pass_env"] = vars.clone();
    }
    Ok(profile)
}

fn upstream(settings: &Value, name: &str, home: &Path) -> Result<Upstream> {
    let profile = configured_profile(settings, name, home)?;
    if profile["transport"] == "http" {
        return Upstream::open(&profile);
    }
    let env = settings
        .get("env")
        .or_else(|| settings.get("environment"))
        .unwrap_or(&Value::Null);
    Upstream::open_catalog_stdio(Profile::for_catalog(&profile, env, home)?)
}

async fn observe(db: &Path, config: &CatalogConfig, name: &str, settings: &Value) -> Result<usize> {
    if !config.unchanged() {
        return Err(ReviewError("The client settings changed during discovery.").into());
    }
    let mut upstream = upstream(settings, name, &config.home)?;
    upstream.initialize().await?;
    let tools = upstream.catalog().await?;
    upstream.verify()?;
    if !config.unchanged() {
        return Err(ReviewError("The client settings changed during discovery.").into());
    }
    ReviewStore::open(db)?.observe_catalog(
        format!("harness:{}:{name}", config.id),
        upstream.identity(),
        &tools,
    )?;
    Ok(tools.len())
}

pub fn sync(db: &Path) -> Result<Value> {
    let configs = crate::harness::catalog_configs(db)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let deadline = tokio::time::Instant::now() + RUN_TIMEOUT;
        let mut servers = Vec::new();
        let mut attempted = 0;
        for (client, config) in configs {
            let config = match config {
                Ok(Some(config)) => config,
                Ok(None) => continue,
                Err(_) => {
                    servers.push(json!({"harness":client,"name":null,"state":"unavailable",
                        "message":"DriftGuard could not read this client's MCP settings."}));
                    continue;
                }
            };
            if client == "codex" {
                let budget = crate::codex_catalog::TIMEOUT.min(deadline.saturating_duration_since(tokio::time::Instant::now()));
                let result = tokio::time::timeout(budget, crate::codex_catalog::collect(db, &config, &mut servers)).await;
                if !matches!(result, Ok(Ok(_))) {
                    servers.push(json!({"harness":client,"name":null,"state":"unavailable",
                        "message":"Codex runtime discovery did not finish. DriftGuard kept the catalogs it received and will try the configured servers."}));
                }
            }
            for (name, settings) in &config.entries {
                if !configured_name(name) || settings == false || settings["enabled"] == false || routed_entry(settings) {
                    continue;
                }
                if servers.iter().any(|row| row["harness"] == client && row["name"] == name.as_str() && row["state"] == "observed") {
                    continue;
                }
                let mut result = json!({"harness":client,"name":name,"state":"unavailable"});
                let timeout = SOURCE_TIMEOUT
                    .min(deadline.saturating_duration_since(tokio::time::Instant::now()));
                if attempted >= MAX_SOURCES || timeout.is_zero() {
                    result["message"] = json!("The discovery limit was reached.");
                } else {
                    attempted += 1;
                    match tokio::time::timeout(timeout, observe(db, &config, name, settings)).await
                    {
                        Ok(Ok(count)) => {
                            result["state"] = json!("observed");
                            result["tools"] = json!(count);
                        }
                        Ok(Err(error)) => {
                            result["sign_in"] = json!(client == "codex" && settings["url"].is_string()
                                && error.downcast_ref::<ReviewError>().is_some_and(|error| error.0 == "The HTTPS server requires authentication."));
                            result["message"] = json!(error.downcast_ref::<ReviewError>().map_or(
                                "DriftGuard could not read the server's tool catalog.",
                                |error| error.0
                            ));
                        }
                        Err(_) => {
                            result["message"] = json!("The tool catalog did not respond in time.")
                        }
                    }
                    if result["state"] == "unavailable" {
                        ReviewStore::open(db)?.catalog_check_failed(&format!("harness:{client}:{name}"))?;
                    }
                }
                if let Some(existing) = servers.iter_mut().find(|row| row["harness"] == client && row["name"] == name.as_str()) {
                    if result["state"] == "observed" {
                        *existing = result;
                    }
                } else {
                    servers.push(result);
                }
            }
        }
        Ok(json!({"servers":servers}))
    })
}

#[cfg(test)]
#[test]
fn configured_names_cannot_be_parsed_as_cli_flags() {
    assert!(configured_name("github"));
    assert!(configured_name("my-server.v2"));
    for name in ["-h", "--help", "--config=evil", "-", ""] {
        assert!(!configured_name(name), "{name}");
    }
    assert!(crate::servers::name(&serde_json::json!("--help")).is_err());
}
