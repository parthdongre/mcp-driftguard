use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::discovery::{Peer, Profile};
use crate::harness::CatalogConfig;
use crate::review::{ReviewError, ReviewStore};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const MAX_PAGES: usize = 128;

fn profile(config: &CatalogConfig) -> Result<Profile> {
    let name = if cfg!(windows) { "codex.exe" } else { "codex" };
    let local = config.home.join(".local/bin").join(name);
    let app = PathBuf::from(
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    );
    let executable = if local.is_file() {
        local
    } else if config.isolated {
        return Err(
            ReviewError("No Codex runtime is available in the isolated harness home.").into(),
        );
    } else if cfg!(target_os = "macos") && app.is_file() {
        app
    } else {
        PathBuf::from(name)
    };
    let mut argv = vec![json!(executable), json!("app-server")];
    for (name, settings) in &config.entries {
        if matches!(
            name.as_str(),
            "driftguard-rust" | "driftguard" | "driftguard-filesystem"
        ) || crate::harness_catalog::routed_entry(settings)
        {
            if !name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.".contains(&byte))
            {
                continue;
            }
            argv.extend([
                json!("-c"),
                json!(format!(
                    "mcp_servers.{}.enabled=false",
                    serde_json::to_string(name)?
                )),
            ]);
        }
    }
    let names: BTreeSet<_> = config
        .entries
        .values()
        .flat_map(|settings| {
            settings["env_vars"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .chain(settings["bearer_token_env_var"].as_str())
        })
        .collect();
    let mut environment = BTreeMap::new();
    if let Some(directory) = config.path.parent() {
        environment.insert("CODEX_HOME", directory);
    }
    Profile::for_catalog(
        &json!({
            "server_id":"codex-runtime","argv":argv,"cwd":config.home,"pass_env":names,
            "max_message_bytes":16 * 1024 * 1024, "timeout_seconds":20,
        }),
        &json!(environment),
        &config.home,
    )
}

fn read_source(
    db: &Path,
    config: &CatalogConfig,
    peer: &Peer,
    name: &str,
    row: &Value,
) -> Result<usize> {
    if row.get("toolsError").is_some_and(|error| !error.is_null())
        || row["authStatus"] == "notLoggedIn"
    {
        return Err(ReviewError(
            "Codex could not load this catalog. Check its MCP status and sign-in.",
        )
        .into());
    }
    let tools = row["tools"]
        .as_object()
        .ok_or(ReviewError("Codex returned an invalid tool catalog."))?;
    if tools.is_empty() && row["serverCapabilities"]["tools"].is_null() {
        return Err(ReviewError("Codex exposed no tools for this source.").into());
    }
    if tools.iter().any(|(name, tool)| tool["name"] != *name) {
        return Err(ReviewError("Codex returned mismatched tool names.").into());
    }
    let tools: Vec<_> = tools.values().cloned().collect();
    if tools.iter().any(|tool| peer.contains_secret(tool)) {
        return Err(ReviewError("A tool definition contains a configured credential.").into());
    }
    // The per-source binding is independent of tool content, so a tool change
    // can be compared with its stored baseline.
    let source = format!("harness:codex:{name}");
    let binding = config.entries.get(name);
    let identity = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&json!([source, binding]))?)
    );
    if !config.unchanged() {
        return Err(ReviewError("The Codex configuration changed during discovery.").into());
    }
    ReviewStore::open(db)?.observe_catalog(source, &identity, &tools)?;
    Ok(tools.len())
}

pub async fn collect(
    db: &Path,
    config: &CatalogConfig,
    servers: &mut Vec<Value>,
) -> Result<BTreeSet<String>> {
    if config.isolated && !config.home.join(".local/bin/codex").is_file() {
        return Ok(BTreeSet::new());
    }
    let mut peer = Peer::open_codex_catalog(profile(config)?)?;
    peer.request(
        "initialize",
        json!({
            "clientInfo":{"name":"driftguard","version":env!("CARGO_PKG_VERSION")},
            "capabilities":{"optOutNotificationMethods":["mcpServer/startupStatus/updated"]}
        }),
    )
    .await?;
    peer.notify("initialized").await?;
    let mut cursor: Option<String> = None;
    let mut cursors = BTreeSet::new();
    let mut observed = BTreeSet::new();
    let mut seen = BTreeSet::new();
    for _ in 0..MAX_PAGES {
        let mut params = json!({"limit":4,"detail":"toolsAndAuthOnly"});
        if let Some(cursor) = &cursor {
            params["cursor"] = json!(cursor);
        }
        let response = peer.request("mcpServerStatus/list", params).await?;
        let rows = response["data"]
            .as_array()
            .ok_or(ReviewError("Codex returned an invalid server catalog."))?;
        for row in rows {
            let Some(name) = row["name"]
                .as_str()
                .filter(|name| super::harness_catalog::configured_name(name))
            else {
                continue;
            };
            if name == "driftguard-filesystem"
                || config.entries.get(name).is_some_and(|settings| {
                    settings["enabled"] == false || crate::harness_catalog::routed_entry(settings)
                })
                || observed.contains(name)
                || !seen.insert(name.to_owned())
            {
                continue;
            }
            match read_source(db, config, &peer, name, row) {
                Ok(count) => {
                    observed.insert(name.to_owned());
                    servers.push(
                        json!({"harness":"codex","name":name,"state":"observed","tools":count}),
                    );
                }
                Err(error) => {
                    servers.push(json!({"harness":"codex","name":name,"state":"unavailable",
                    "sign_in":row["authStatus"] == "notLoggedIn" && config.entries.get(name).is_some_and(|entry| entry["url"].is_string()),
                    "message":error.downcast_ref::<ReviewError>()
                        .map_or("DriftGuard could not save this Codex catalog.", |error| error.0)}))
                }
            }
        }
        match response.get("nextCursor") {
            None | Some(Value::Null) => return Ok(observed),
            Some(Value::String(next)) if !next.is_empty() && cursors.insert(next.clone()) => {
                cursor = Some(next.clone())
            }
            _ => return Err(ReviewError("Codex returned invalid catalog pagination.").into()),
        }
    }
    Err(ReviewError("Codex discovery exceeded its page limit.").into())
}

pub const TIMEOUT: Duration = Duration::from_secs(40);
