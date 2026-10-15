use serde_json::Value;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::Manager;

const MAX_REQUEST: usize = 2_100_000;
const MAX_RESPONSE: u64 = 16 * 1024 * 1024;
const ACTIONS: &[&str] = &[
    "overview",
    "list_tools",
    "review",
    "history",
    "activity",
    "import_definitions",
    "approve",
    "deny",
    "quarantine",
];

#[derive(Clone)]
struct BridgeRuntime {
    python: Option<PathBuf>,
    db: PathBuf,
    lock: Arc<Mutex<()>>,
}

fn validate_request(request: &Value) -> Result<Vec<u8>, String> {
    let object = request.as_object().ok_or("Expected a structured request")?;
    let action = object
        .get("action")
        .and_then(Value::as_str)
        .ok_or("A bridge action is required")?;
    if !ACTIONS.contains(&action) {
        return Err("This desktop action is not available".into());
    }
    // Deny unexpected arguments at the native boundary, including executable/DB/path overrides.
    let allowed: &[&str] = match action {
        "overview" | "activity" => &["action"],
        "list_tools" => &["action", "server_id"],
        "review" | "history" => &["action", "server_id", "tool_name"],
        "import_definitions" => &["action", "server_id", "identity", "tools"],
        _ => &[
            "action",
            "server_id",
            "tool_name",
            "expected_sha256",
            "expected_revision",
        ],
    };
    if object.keys().any(|key| !allowed.contains(&key.as_str())) {
        return Err("Unexpected desktop request fields".into());
    }
    let bytes = serde_json::to_vec(request).map_err(|_| "Unable to encode request")?;
    if bytes.len() > MAX_REQUEST {
        return Err("Desktop request exceeds its size limit".into());
    }
    Ok(bytes)
}

fn bounded_read<R: Read>(reader: R, maximum: u64) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    reader
        .take(maximum + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "Unable to read local bridge output")?;
    if bytes.len() as u64 > maximum {
        return Err("Local bridge output exceeds its size limit".into());
    }
    Ok(bytes)
}

fn run_bridge(runtime: BridgeRuntime, bytes: Vec<u8>) -> Result<Value, String> {
    let _lock = runtime
        .lock
        .lock()
        .map_err(|_| "The local bridge is unavailable")?;
    let python = runtime.python.as_ref().ok_or(
        "Local engine unavailable. Set DRIFTGUARD_PYTHON to the absolute Python executable in a virtual environment with mcp-driftguard installed, then restart the desktop app.",
    )?;
    if !python.is_absolute() || !python.is_file() {
        return Err(
            "DRIFTGUARD_PYTHON must identify an existing absolute Python executable".into(),
        );
    }
    let mut command = Command::new(python);
    command
        .args(["-I", "-m", "driftguard.desktop_bridge", "--db"])
        .arg(&runtime.db)
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .spawn()
        .map_err(|_| "Unable to start the configured local Python engine")?;
    let stdout = child
        .stdout
        .take()
        .ok_or("Local bridge output unavailable")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Local bridge error stream unavailable")?;
    let output = thread::spawn(move || bounded_read(stdout, MAX_RESPONSE));
    // Drain stderr to avoid a pipe deadlock; never expose it in UI or logs.
    let errors = thread::spawn(move || bounded_read(stderr, 65_536));
    let input_result = child
        .stdin
        .take()
        .ok_or("Local bridge input unavailable")?
        .write_all(&bytes);
    if input_result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
        let _ = output.join();
        let _ = errors.join();
        return Err("Unable to deliver the local review request".into());
    }
    let started = Instant::now();
    let timed_out = loop {
        match child.try_wait() {
            Ok(Some(_)) => break false,
            Ok(None) if started.elapsed() < Duration::from_secs(20) => {
                thread::sleep(Duration::from_millis(20));
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                break true;
            }
        }
    };
    let result = output
        .join()
        .map_err(|_| "The local bridge output reader failed")?;
    let _ = errors.join();
    if timed_out {
        return Err(
            "The local engine timed out. No approval was assumed; refresh the workspace.".into(),
        );
    }
    let response: Value = serde_json::from_slice(&result?)
        .map_err(|_| "The local engine returned an invalid response; no decision was assumed")?;
    if !response.get("ok").is_some_and(Value::is_boolean) {
        return Err("The local engine returned an unexpected response".into());
    }
    Ok(response)
}

#[tauri::command]
async fn driftguard_request(
    window: tauri::WebviewWindow,
    runtime: tauri::State<'_, BridgeRuntime>,
    request: Value,
) -> Result<Value, String> {
    if window.label() != "main" {
        return Err("This window cannot access the review engine".into());
    }
    let bytes = validate_request(&request)?;
    let owned = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || run_bridge(owned, bytes))
        .await
        .map_err(|_| "The local review worker is unavailable".to_string())?
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let directory = app.path().app_data_dir()?;
            std::fs::create_dir_all(&directory)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))?;
            }
            app.manage(BridgeRuntime {
                python: std::env::var_os("DRIFTGUARD_PYTHON").map(PathBuf::from),
                db: directory.join("guard.sqlite3"),
                lock: Arc::new(Mutex::new(())),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![driftguard_request])
        .run(tauri::generate_context!())
        .expect("Unable to start DriftGuard desktop");
}

#[cfg(test)]
mod tests {
    use super::validate_request;
    use serde_json::json;

    #[test]
    fn rejects_unknown_actions_and_host_overrides() {
        assert!(validate_request(&json!({"action": "shell", "command": "whoami"})).is_err());
        assert!(validate_request(&json!({"action": "overview", "db": "/tmp/other.db"})).is_err());
        assert!(validate_request(&json!({"action": "overview", "python": "/tmp/python"})).is_err());
        assert!(validate_request(&json!({"action": "overview"})).is_ok());
    }
}
