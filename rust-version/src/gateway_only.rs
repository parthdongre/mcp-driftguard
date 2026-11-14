use std::collections::BTreeSet;
use std::error::Error;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use toml_edit::{value, Array, DocumentMut, Item, Table};

use crate::discovery::{Peer, Profile};
use crate::review::ReviewError;

type Result<T> = std::result::Result<T, Box<dyn Error>>;

fn configuration(servers: &[Value]) -> DocumentMut {
    let mut config = DocumentMut::new();
    let mut features = Table::new();
    for feature in ["apps", "plugins", "hooks"] {
        features[feature] = value(false);
    }
    config["features"] = Item::Table(features);
    config["sandbox_mode"] = value("read-only");
    let mut entries = Table::new();
    for server in servers {
        let mut entry = Table::new();
        entry["command"] = value(server["command"].as_str().unwrap());
        let args: Array = server["args"]
            .as_array()
            .unwrap()
            .iter()
            .map(|arg| arg.as_str().unwrap())
            .collect();
        entry["args"] = value(args);
        entries.insert(server["server_id"].as_str().unwrap(), Item::Table(entry));
    }
    config["mcp_servers"] = Item::Table(entries);
    config
}

async fn verify(executable: &Path, root: &Path, allowed: &BTreeSet<&str>) -> Result<Vec<Value>> {
    let profile = Profile::for_catalog(
        &json!({"server_id":"gateway-only","argv":[executable,"app-server","--strict-config"],
            "cwd":root,"timeout_seconds":30,"max_message_bytes":16*1024*1024}),
        &json!({"CODEX_HOME":root.join("home")}),
        root,
    )?;
    let mut codex = Peer::open_codex_catalog(profile)?;
    codex
        .request(
            "initialize",
            json!({"clientInfo":{"name":"driftguard-gateway-only","version":"1"}}),
        )
        .await?;
    codex.notify("initialized").await?;
    let thread = codex
        .request(
            "thread/start",
            json!({
                "cwd":root, "ephemeral":true, "sandbox":"read-only", "approvalPolicy":"never",
            }),
        )
        .await?;
    let thread_id = thread["thread"]["id"]
        .as_str()
        .ok_or(ReviewError("Codex did not start the verification session."))?;
    let mut cursor = Value::Null;
    let mut seen = BTreeSet::new();
    let mut failed = Vec::new();
    for _ in 0..128 {
        let page = codex
            .request(
                "mcpServerStatus/list",
                json!({"limit":16,"cursor":cursor,"detail":"toolsAndAuthOnly","threadId":thread_id}),
            )
            .await?;
        let rows = page["data"].as_array().ok_or(ReviewError(
            "Codex did not return a verifiable MCP catalog.",
        ))?;
        for row in rows {
            let name = row["name"]
                .as_str()
                .ok_or(ReviewError("Codex returned an unnamed MCP server."))?;
            if !allowed.contains(name) {
                return Err(ReviewError(
                    "Codex exposed an MCP server outside the gateway allowlist. Launch cancelled.",
                )
                .into());
            }
            if !seen.insert(name.to_owned()) {
                return Err(
                    ReviewError("Codex returned duplicate MCP routes. Launch cancelled.").into(),
                );
            }
            if let Some(state) = startup_failure(row) {
                failed.push(json!({"server_id":name,"state":state}));
            }
        }
        cursor = page["nextCursor"].clone();
        if cursor.is_null() {
            if seen.len() != allowed.len() {
                return Err(ReviewError(
                    "Codex did not report every configured gateway route. Launch cancelled.",
                )
                .into());
            }
            return Ok(failed);
        }
        if !cursor.is_string() {
            break;
        }
    }
    Err(ReviewError("Codex did not return a complete MCP catalog. Launch cancelled.").into())
}

fn startup_failure(row: &Value) -> Option<&'static str> {
    if row["authStatus"] == "notLoggedIn" || row["runtimeStatus"] == "authenticationRequired" {
        Some("sign_in_required")
    } else if !row["toolsError"].is_null()
        || !row["tools"].is_object()
        || (row["runtimeStatus"] != "connected" && !row["serverInfo"].is_object())
        || matches!(
            row["runtimeStatus"].as_str(),
            Some("failed" | "cancelled" | "disabled")
        )
    {
        Some("startup_failed")
    } else {
        None
    }
}

fn quote(path: &Path) -> Result<String> {
    let text = path
        .to_str()
        .ok_or(ReviewError("The launch path must use UTF-8."))?;
    Ok(format!("'{}'", text.replace('\'', "'\"'\"'")))
}

pub fn launch(db: &Path, open_terminal: bool) -> Result<Value> {
    if open_terminal && !cfg!(target_os = "macos") {
        return Err(ReviewError("Use the verified launch command in your terminal.").into());
    }
    let rows = crate::servers::list(db)?;
    let servers = rows.as_array().unwrap();
    if servers.is_empty() {
        return Err(ReviewError("Register a gateway server before launching Codex.").into());
    }
    let (mut ready, skipped) = servers
        .iter()
        .cloned()
        .partition::<Vec<_>, _>(|server| server["state"] == "catalog_ready");
    let mut skipped: Vec<_> = skipped
        .iter()
        .map(|server| {
            json!({
                "server_id":server["server_id"], "state":server["state"],
            })
        })
        .collect();
    if ready.is_empty() {
        return Ok(json!({"opened":false,"servers":[],"skipped":skipped}));
    }
    let (home, _) = crate::harness::home()?;
    let installed = home
        .join(".local/bin")
        .join(if cfg!(windows) { "codex.exe" } else { "codex" });
    let executable = if installed.is_file() {
        installed
    } else {
        PathBuf::from("codex")
    };
    let root = tempfile::Builder::new()
        .prefix("driftguard-codex-only-")
        .tempdir()?;
    let codex_home = root.path().join("home");
    std::fs::create_dir(&codex_home)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let allowed = loop {
        std::fs::write(
            codex_home.join("config.toml"),
            configuration(&ready).to_string(),
        )?;
        let names: BTreeSet<_> = ready
            .iter()
            .filter_map(|server| server["server_id"].as_str())
            .collect();
        let failed = runtime.block_on(verify(&executable, root.path(), &names))?;
        if failed.is_empty() {
            break names.into_iter().map(str::to_owned).collect::<Vec<_>>();
        }
        ready.retain(|server| {
            !failed
                .iter()
                .any(|failure| failure["server_id"] == server["server_id"])
        });
        skipped.extend(failed);
        if ready.is_empty() {
            return Ok(json!({"opened":false,"servers":[],"skipped":skipped}));
        }
    };
    let command = format!(
        "cd {} && export CODEX_HOME={} && exec {} --strict-config",
        quote(root.path())?,
        quote(&codex_home)?,
        quote(&executable)?
    );
    if open_terminal {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let script = root.path().join("DriftGuard Codex.command");
            std::fs::write(&script, format!("#!/bin/sh\n{command}\n"))?;
            std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700))?;
            if !std::process::Command::new("/usr/bin/open")
                .arg("-a")
                .arg("Terminal")
                .arg(&script)
                .status()?
                .success()
            {
                return Err(ReviewError("Could not open Terminal.").into());
            }
        }
    }
    let _workspace = root.keep();
    Ok(json!({"command":command,"servers":allowed,"opened":open_terminal,"skipped":skipped}))
}

#[cfg(test)]
#[test]
fn codex_discovery_rows_are_not_evidence_of_startup() {
    assert_eq!(
        startup_failure(&json!({"name":"example","tools":{}})),
        Some("startup_failed")
    );
    assert_eq!(
        startup_failure(&json!({"runtimeStatus":"authenticationRequired","tools":{}})),
        Some("sign_in_required")
    );
    assert_eq!(
        startup_failure(&json!({"runtimeStatus":"failed","serverInfo":{},"tools":{}})),
        Some("startup_failed")
    );
    assert_eq!(
        startup_failure(
            &json!({"runtimeStatus":"connected","toolsError":"unavailable","tools":{}})
        ),
        Some("startup_failed")
    );
    assert_eq!(
        startup_failure(&json!({"runtimeStatus":"connected","tools":{}})),
        None
    );
}
