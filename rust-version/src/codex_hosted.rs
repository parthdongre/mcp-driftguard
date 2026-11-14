use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::sync::Notify;

use crate::discovery::{Peer, Profile};
use crate::review::ReviewError;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
pub const SERVER: &str = "codex-hosted";
const CONNECTOR: &str = "codex_apps";
const TIMEOUT: Duration = Duration::from_secs(25);

pub struct Hosted {
    peer: Peer,
    settings: PathBuf,
    configuration_hash: [u8; 32],
    workspace: tempfile::TempDir,
    identity: String,
    thread: String,
    tools: BTreeMap<String, Value>,
}

impl Hosted {
    pub fn open(home: &Path) -> Result<Self> {
        let (system_home, _) = crate::harness::home()?;
        let settings = home.join("config.toml");
        let config = crate::harness::read_text(&settings, 1024 * 1024)?.unwrap_or_default();
        let installed =
            system_home
                .join(".local/bin")
                .join(if cfg!(windows) { "codex.exe" } else { "codex" });
        let executable = if installed.is_file() {
            installed
        } else {
            PathBuf::from("codex")
        };
        let mut argv = vec![
            json!(executable),
            json!("app-server"),
            json!("--disable"),
            json!("hooks"),
            json!("-c"),
            json!("sandbox_mode='read-only'"),
        ];
        let document: toml_edit::DocumentMut = config
            .parse()
            .map_err(|_| ReviewError("Codex settings could not be parsed."))?;
        if let Some(entries) = document
            .get("mcp_servers")
            .and_then(toml_edit::Item::as_table_like)
        {
            for (name, _) in entries.iter() {
                if !name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
                {
                    return Err(ReviewError("A Codex MCP name cannot be isolated. Rename it before connecting hosted apps.").into());
                }
                argv.extend([
                    json!("-c"),
                    json!(format!("mcp_servers.{name}.enabled=false")),
                ]);
            }
        }
        let workspace = tempfile::Builder::new()
            .prefix("driftguard-hosted-")
            .tempdir()?;
        let profile = Profile::for_catalog(
            &json!({"server_id":SERVER,"argv":argv,"cwd":workspace.path(),
                "max_message_bytes":16*1024*1024,"timeout_seconds":TIMEOUT.as_secs()}),
            &json!({"CODEX_HOME":home}),
            &system_home,
        )?;
        let peer = Peer::open_codex_catalog(profile)?;
        let configuration_hash = Sha256::digest(config.as_bytes()).into();
        Ok(Self {
            peer,
            settings,
            configuration_hash,
            workspace,
            identity: String::new(),
            thread: String::new(),
            tools: BTreeMap::new(),
        })
    }

    pub async fn initialize(&mut self) -> Result<()> {
        self.peer
            .request(
                "initialize",
                json!({"clientInfo":{"name":"driftguard-hosted","version":"1"}}),
            )
            .await
            .map_err(|_| ReviewError("Codex hosted connector initialization failed."))?;
        self.peer.notify("initialized").await?;
        let account = self
            .peer
            .request("account/read", json!({"refreshToken":false}))
            .await
            .map_err(|_| ReviewError("Codex could not read the active account."))?;
        if !account["account"].is_object() {
            return Err(ReviewError("Sign in to Codex before connecting its hosted apps.").into());
        }
        self.identity = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&json!([
                "codex-hosted-v1",
                self.settings,
                self.configuration_hash,
                account["account"]
            ]))?)
        );
        let thread = self.peer.request("thread/start",json!({
            "cwd":self.workspace.path(),"ephemeral":true,"sandbox":"read-only","approvalPolicy":"never",
        })).await?;
        self.thread = thread["thread"]["id"]
            .as_str()
            .ok_or(ReviewError(
                "Codex did not create a hosted connector session.",
            ))?
            .to_owned();
        Ok(())
    }

    pub async fn catalog(&mut self) -> Result<Vec<Value>> {
        self.verify()?;
        let mut cursor = Value::Null;
        let mut cursors = BTreeSet::new();
        for _ in 0..128 {
            let page = self.peer.request("mcpServerStatus/list",json!({
                "threadId":self.thread,"cursor":cursor,"limit":8,"detail":"toolsAndAuthOnly",
            })).await?;
            let rows = page["data"]
                .as_array()
                .ok_or(ReviewError("Codex returned an invalid hosted catalog."))?;
            if let Some(row) = rows.iter().find(|row| row["name"] == CONNECTOR) {
                if row["authStatus"] == "notLoggedIn"
                    || row["runtimeStatus"] == "authenticationRequired"
                {
                    return Err(
                        ReviewError("Sign in to Codex before connecting its hosted apps.").into(),
                    );
                }
                if !row["toolsError"].is_null() {
                    return Err(ReviewError("Codex could not load the hosted catalog.").into());
                }
                let entries = row["tools"].as_object().ok_or(ReviewError(
                    "Codex returned an invalid hosted tool catalog.",
                ))?;
                self.tools = entries
                    .iter()
                    .filter(|(name, definition)| compatible(name, definition))
                    .map(|(name, definition)| (name.clone(), definition.clone()))
                    .collect();
                return Ok(self.tools.values().cloned().collect());
            }
            cursor = page["nextCursor"].clone();
            if !cursor
                .as_str()
                .is_some_and(|next| cursors.insert(next.to_owned()))
            {
                break;
            }
        }
        Err(ReviewError("The signed-in Codex process did not expose its hosted apps.").into())
    }

    pub async fn call(&mut self, name: &str, arguments: &Value) -> Result<Value> {
        self.verify()?;
        if !self.tools.contains_key(name) {
            return Err(ReviewError("This tool is outside the current hosted catalog.").into());
        }
        self.peer
            .request(
                "mcpServer/tool/call",
                json!({
                    "threadId":self.thread,"server":CONNECTOR,"tool":name,"arguments":arguments,
                }),
            )
            .await
    }

    pub fn verify(&self) -> Result<()> {
        let config = crate::harness::read_text(&self.settings, 1024 * 1024)?.unwrap_or_default();
        let hash: [u8; 32] = Sha256::digest(config.as_bytes()).into();
        if hash != self.configuration_hash {
            return Err(ReviewError("Codex settings changed. Start a new gateway session.").into());
        }
        if !self.peer.connected() {
            return Err(ReviewError(
                "The hosted Codex process disconnected. Reconnect the gateway.",
            )
            .into());
        }
        Ok(())
    }

    pub fn identity(&self) -> &str {
        &self.identity
    }
    pub fn timeout(&self) -> Duration {
        TIMEOUT
    }
    pub fn changed(&self) -> Arc<Notify> {
        self.peer.changed()
    }
    pub fn contains_secret(&self, value: &Value) -> bool {
        self.peer.contains_secret(value)
    }
}

fn compatible(name: &str, definition: &Value) -> bool {
    let valid_name = name.len() <= 128
        && name
            .split_once('.')
            .is_some_and(|(app, tool)| !app.is_empty() && !tool.is_empty())
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte));
    valid_name && definition["name"] == name && crate::gateway::callable(definition)
}

#[cfg(test)]
#[test]
fn hosted_routing_requires_a_valid_exact_name_and_supported_contract() {
    let mut tool = json!({"name":"alpaca.get_calendar","inputSchema":{"type":"object"}});
    assert!(compatible("alpaca.get_calendar", &tool));
    assert!(!compatible("alpaca.some_other_tool", &tool));
    tool["inputSchema"] = json!({"$ref":"https://example.com/schema"});
    assert!(!compatible("alpaca.get_calendar", &tool));
}
