use std::ffi::OsString;
use std::io::{self, BufRead, Read, Write};
use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::discovery::{LEGACY, VERSION};
use crate::review::{ReviewError, ReviewStore};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const SAMPLE: &str = "driftguard-sample";
const SAMPLE_TEXT: &str = "DriftGuard live integration check\n";

pub fn live(db: &Path, request: &Value) -> Result<Value> {
    let action = request["action"].as_str().unwrap_or_default();
    let mut message = None;
    let mut changed = None;
    if action != "live_status" {
        let client = request["harness"].as_str().unwrap_or("codex");
        let mut args = vec![
            OsString::from(if action == "live_connect" {
                "connect"
            } else {
                "disconnect"
            }),
            OsString::from(client),
        ];
        if action == "live_connect" {
            let profile = match std::env::var_os("DRIFTGUARD_RUST_PROFILE") {
                Some(path) => PathBuf::from(path).canonicalize()?,
                None => sample_profile(db)?,
            };
            args.push(profile.into_os_string());
        }
        let entry = crate::harness::run(db, args.into_iter())?;
        changed = Some((
            if action == "live_connect" {
                "harness_configured"
            } else {
                "harness_disconnected"
            },
            format!("harness:{client}:driftguard-rust"),
        ));
        message = Some(if action == "live_connect" {
            format!(
                "Configured {}. Open a new session to start its MCP gateway.",
                entry["name"].as_str().unwrap_or(client)
            )
        } else {
            format!("Disconnected {}.", entry["name"].as_str().unwrap_or(client))
        });
    }
    let mut store = ReviewStore::open(db)?;
    if let Some((kind, source)) = changed {
        store.record_mcp_event(kind, &source)?;
    }
    let overview = store.request(&json!({"action":"overview"}))?;
    let entries = crate::harness::run(db, [OsString::from("list")].into_iter())?;
    let health = overview["gateway_health"]
        .as_array()
        .ok_or(ReviewError("Missing gateway status."))?;
    let mut harnesses = Vec::new();
    let mut clients = 0;
    for entry in entries
        .as_array()
        .ok_or(ReviewError("Missing coding harness status."))?
    {
        let prefix = format!("gateway:{}:", entry["id"].as_str().unwrap_or_default());
        let installed = entry["connected"] == true;
        let attached = if installed || entry["id"] == "codex" {
            health
                .iter()
                .filter(|row| {
                    row["active"] == true
                        && row["server_id"]
                            .as_str()
                            .is_some_and(|source| source.starts_with(&prefix))
                })
                .map(|row| row["sessions"].as_u64().unwrap_or_default())
                .sum::<u64>()
        } else {
            0
        };
        clients += attached;
        harnesses.push(
            json!({"id":entry["id"],"label":entry["name"],"detected":entry["detected"],
            "installed":installed,"attached":attached}),
        );
    }
    let pending = store.pending_gateway_tools()?;
    let catalog_tools = overview["tools"].as_u64().unwrap_or_default();
    Ok(
        json!({"engine":"rust","harnesses":harnesses,"running":clients>0,"clients":clients,
        "verified":false,"job":{"stage":"idle"},"tool":null,"pending":pending,
        "catalog_tools":catalog_tools,"message":message,"codex_routes":crate::harness::routed_codex_names(db)?}),
    )
}

fn sample_profile(db: &Path) -> Result<PathBuf> {
    let cwd = db
        .parent()
        .ok_or(ReviewError("Choose a workspace directory."))?;
    let profile = cwd.join("driftguard-rust-sample.json");
    let expected = json!({"server_id":SAMPLE,"argv":[std::env::current_exe()?,"sample-server"],
        "cwd":cwd,"protocol_version":VERSION});
    if profile.exists() {
        if crate::discovery::Profile::parse_file(&profile)? != expected {
            return Err(ReviewError(
                "The Rust sample profile was changed. Set a trusted profile or restore the sample.",
            )
            .into());
        }
    } else {
        let mut file = tempfile::NamedTempFile::new_in(cwd)?;
        serde_json::to_writer(&mut file, &expected)?;
        file.as_file().sync_all()?;
        match file.persist_noclobber(&profile) {
            Ok(_) => {}
            Err(error) if error.error.kind() == io::ErrorKind::AlreadyExists => {
                if crate::discovery::Profile::parse_file(&profile)? != expected {
                    return Err(ReviewError("The Rust sample profile changed during setup.").into());
                }
            }
            Err(error) => return Err(error.into()),
        }
    }
    Ok(profile)
}

pub fn serve_sample() -> Result<()> {
    let mut input = io::stdin().lock();
    let mut output = io::stdout().lock();
    loop {
        let mut line = Vec::new();
        if (&mut input).take(65_537).read_until(b'\n', &mut line)? == 0 {
            return Ok(());
        }
        if line.len() > 65_536 || line.last() != Some(&b'\n') {
            return Err(ReviewError("Invalid sample MCP message.").into());
        }
        let request = crate::input::parse(&line)?;
        let Some(id) = request.get("id") else {
            continue;
        };
        let result = match request["method"].as_str() {
            Some("initialize")
                if request["params"]["protocolVersion"]
                    .as_str()
                    .is_some_and(|version| LEGACY.contains(&version)) =>
            {
                Some(json!({
                    "protocolVersion":request["params"]["protocolVersion"],"capabilities":{"tools":{}},
                    "serverInfo":{"name":SAMPLE,"version":env!("CARGO_PKG_VERSION")}
                }))
            }
            Some("tools/list") => Some(json!({"tools":[{
                "name":"read_sample","description":"Read the fixed DriftGuard integration sample.",
                "inputSchema":{"type":"object","additionalProperties":false},
                "annotations":{"readOnlyHint":true}
            }]})),
            Some("tools/call")
                if request["params"]["name"] == "read_sample"
                    && request["params"]["arguments"]
                        .as_object()
                        .is_some_and(|args| args.is_empty()) =>
            {
                Some(json!({"content":[{"type":"text","text":SAMPLE_TEXT}]}))
            }
            Some("ping") => Some(json!({})),
            _ => None,
        };
        let reply = match result {
            Some(result) => json!({"jsonrpc":"2.0","id":id,"result":result}),
            None => {
                json!({"jsonrpc":"2.0","id":id,"error":{"code":-32602,"message":"Unsupported sample request."}})
            }
        };
        serde_json::to_writer(&mut output, &reply)?;
        output.write_all(b"\n")?;
        output.flush()?;
    }
}
