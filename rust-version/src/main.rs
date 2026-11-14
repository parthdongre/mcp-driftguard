mod catalog;
mod codex_catalog;
mod codex_hosted;
mod contracts;
mod credentials;
mod decision_model;
mod discovery;
mod gateway;
mod gateway_only;
mod harness;
mod harness_catalog;
mod harness_helpers;
mod http;
mod input;
mod review;
mod servers;
mod workspace;

use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use serde_json::{json, Value};

const MAX_REQUEST: usize = 2_100_000;

fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    if args.next().as_deref() != Some("--db".as_ref()) {
        return Err("Expected --db PATH".into());
    }
    let path = PathBuf::from(args.next().ok_or("Expected a database path")?);
    if let Some(action) = args.next() {
        if action == "harness" {
            return harness::run(&absolute(&path)?, args);
        }
        if action == "model" {
            let store = review::ReviewStore::open(&path)?;
            match args
                .next()
                .and_then(|arg| arg.into_string().ok())
                .as_deref()
            {
                Some("set") => {
                    let artifact = PathBuf::from(
                        args.next()
                            .ok_or(review::ReviewError("Choose a model file."))?,
                    );
                    if args.next().is_some() || !artifact.is_file() {
                        return Err(review::ReviewError("Choose one regular model file.").into());
                    }
                    let mut json = String::new();
                    std::fs::File::open(artifact)?
                        .take(16_385)
                        .read_to_string(&mut json)?;
                    store.set_model_artifact(Some(&json))?;
                    return Ok(json!({"enabled":true}));
                }
                Some("clear") if args.next().is_none() => {
                    store.set_model_artifact(None)?;
                    return Ok(json!({"enabled":false}));
                }
                _ => {
                    return Err(review::ReviewError("Choose model set PATH or model clear.").into())
                }
            }
        }
        if action != "scan-stdio" && action != "scan" {
            return Err(review::ReviewError("Unexpected command-line arguments.").into());
        }
        let profile = PathBuf::from(args.next().ok_or("Expected a profile path")?);
        if args.next().is_some() {
            return Err("Unexpected command-line arguments".into());
        }
        return scan_stdio(&path, &profile);
    }
    let mut input = Vec::new();
    io::stdin()
        .take((MAX_REQUEST + 1) as u64)
        .read_to_end(&mut input)?;
    if input.is_empty() || input.len() > MAX_REQUEST {
        return Err("Invalid request size".into());
    }
    let request = input::parse(&input)?;
    bridge(&path, &request)
}

fn bridge(path: &Path, request: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let action = request["action"].as_str().unwrap_or_default();
    match action {
        "launch_gateway_only_codex" => {
            return gateway_only::launch(&absolute(path)?, request["open_terminal"] == true)
        }
        "register_codex_hosted" => return servers::register_codex_hosted(&absolute(path)?),
        "gateway_servers" => return servers::list(&absolute(path)?),
        "save_gateway_server" => return servers::save(&absolute(path)?, request),
        "remove_gateway_server" => {
            return servers::remove(&absolute(path)?, servers::name(&request["server_id"])?)
        }
        "link_gateway_server_codex" | "link_gateway_server" => {
            let name = servers::name(&request["server_id"])?;
            let db = absolute(path)?;
            servers::profile(&db, name)?;
            let harness = if action == "link_gateway_server_codex" {
                "codex"
            } else {
                request["harness"]
                    .as_str()
                    .ok_or(review::ReviewError("Choose a coding harness."))?
            };
            harness::link_registered_server(&db, name, harness, true)?;
            return servers::list(&db);
        }
        "check_gateway_server" => {
            return servers::check(&absolute(path)?, servers::name(&request["server_id"])?)
        }
        "codex_mcp_sign_in" => {
            return harness::codex_mcp_sign_in(servers::name(&request["server_id"])?)
        }
        _ => {}
    }
    if action == "sync_harness_catalogs" {
        return harness_catalog::sync(&absolute(path)?);
    }
    if action == "harness_helpers" {
        return harness_helpers::scan(path);
    }
    if matches!(action, "route_codex_mcps" | "restore_codex_mcps") {
        let verb = if action == "route_codex_mcps" {
            "route"
        } else {
            "restore"
        };
        return harness::run(path, [verb.into(), "codex".into()].into_iter());
    }
    if matches!(action, "live_connect" | "live_disconnect" | "live_status") {
        return workspace::live(&absolute(path)?, request);
    }
    if matches!(action, "store_http_credential" | "remove_http_credential") {
        let server = request["server_id"]
            .as_str()
            .filter(|server| {
                !server.is_empty()
                    && server.len() <= 128
                    && server
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
            })
            .ok_or(review::ReviewError("Expected a valid server_id."))?;
        let url = request["url"]
            .as_str()
            .ok_or(review::ReviewError("Choose an HTTPS endpoint."))?;
        http::validate_endpoint(url)?;
        let secret = if action == "store_http_credential" {
            Some(
                request["secret"]
                    .as_str()
                    .ok_or(review::ReviewError("Enter a bearer credential."))?,
            )
        } else {
            None
        };
        credentials::write(server, url, secret)?;
        return Ok(json!({"stored":secret.is_some(),"available":true}));
    }
    if action == "runtime_info" {
        return Ok(
            json!({"engine_available":true,"engine":"rust","state_path":absolute(path)?,
            "gateway_argv":[std::env::current_exe()?, "--db", absolute(path)?, "serve"]}),
        );
    }
    review::ReviewStore::open(path)?.request(request)
}

fn scan_stdio(db: &Path, profile: &Path) -> Result<Value, Box<dyn std::error::Error>> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let (source, identity, tools) = runtime.block_on(discovery::scan(profile))?;
    review::ReviewStore::open(db)?.observe_catalog(source, &identity, &tools)
}

fn absolute(path: &Path) -> std::io::Result<PathBuf> {
    Ok(std::env::current_dir()?.join(path))
}

fn gateway_mode() -> Option<Result<(), Box<dyn std::error::Error>>> {
    let mut args = std::env::args_os().skip(1);
    if args.next()?.as_os_str() != "--db" {
        return None;
    }
    let db = PathBuf::from(args.next()?);
    if args.next()?.as_os_str() != "serve" {
        return None;
    }
    Some((|| {
        let profile = PathBuf::from(
            args.next()
                .ok_or(review::ReviewError("Choose an MCP profile."))?,
        );
        if profile.as_os_str() == "--registered" {
            let argument = args.next().and_then(|value| value.into_string().ok());
            let name = servers::name(&json!(argument))?.to_owned();
            let harness = match args.next() {
                None => None,
                Some(flag) if flag == "--harness" => Some(
                    args.next()
                        .and_then(|name| name.into_string().ok())
                        .filter(|name| harness::client_label(name).is_some())
                        .ok_or(review::ReviewError("Choose a supported harness."))?,
                ),
                _ => return Err(review::ReviewError("Unexpected gateway arguments.").into()),
            };
            if args.next().is_some() {
                return Err(review::ReviewError("Unexpected gateway arguments.").into());
            }
            return tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?
                .block_on(gateway::serve_registered(absolute(&db)?, name, harness));
        }
        if profile.as_os_str() == "--route" {
            let name = args
                .next()
                .and_then(|value| value.into_string().ok())
                .filter(|name| harness_catalog::configured_name(name))
                .ok_or(review::ReviewError("Choose a configured Codex MCP route."))?;
            if args.next().is_some() {
                return Err(review::ReviewError("Unexpected gateway arguments.").into());
            }
            return tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?
                .block_on(gateway::serve_codex_route(absolute(&db)?, name));
        }
        let client = match args.next() {
            None => None,
            Some(flag) if flag == "--client" => Some(
                args.next()
                    .and_then(|name| name.into_string().ok())
                    .ok_or(review::ReviewError("Choose a supported coding harness."))?,
            ),
            _ => return Err(review::ReviewError("Unexpected gateway arguments.").into()),
        };
        if args.next().is_some() {
            return Err(review::ReviewError("Unexpected gateway arguments.").into());
        }
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?
            .block_on(gateway::serve(absolute(&db)?, profile, client))
    })())
}

fn main() -> ExitCode {
    if std::env::args_os().nth(1).as_deref() == Some("sample-server".as_ref())
        && std::env::args_os().nth(2).is_none()
    {
        return if workspace::serve_sample().is_ok() {
            ExitCode::SUCCESS
        } else {
            ExitCode::FAILURE
        };
    }
    if let Some(result) = gateway_mode() {
        return match result {
            Ok(()) => ExitCode::SUCCESS,
            Err(error) => {
                let message = error
                    .downcast_ref::<review::ReviewError>()
                    .map_or("The MCP gateway could not continue.", |error| error.0);
                eprintln!("{message}");
                ExitCode::FAILURE
            }
        };
    }
    let response = match run() {
        Ok(data) => json!({"ok": true, "data": data}),
        Err(error) => json!({"ok": false, "error": {
            "code": "request_failed",
            "message": if let Some(error) = error.downcast_ref::<review::ReviewError>() {
                error.0
            } else {
                "The local request could not be completed."
            }
        }}),
    };
    let stdout = io::stdout();
    let mut output = stdout.lock();
    let written =
        serde_json::to_writer(&mut output, &response).is_ok() && output.write_all(b"\n").is_ok();
    if written && response["ok"] == true {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
