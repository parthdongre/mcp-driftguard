use serde_json::Value;
use std::path::PathBuf;
use std::process::{ExitStatus, Stdio};
use std::sync::Arc;
use std::time::Duration;
use tauri::Manager;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};
use tokio::process::{ChildStdin, Command};
use tokio::sync::Mutex;
use tokio::time::{timeout_at, Instant};

const MAX_REQUEST: usize = 2_100_000;
const MAX_RESPONSE: u64 = 16 * 1024 * 1024;
const MAX_STDERR: u64 = 65_536;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(20);
const TIMEOUT_ERROR: &str =
    "The local engine timed out. No decision was assumed; refresh the workspace before retrying.";
const ACTIONS: &[&str] = &[
    "store_http_credential",
    "remove_http_credential",
    "runtime_info",
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
    frozen: bool,
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
        "overview" | "activity" | "runtime_info" => &["action"],
        "list_tools" => &["action", "server_id"],
        "review" | "history" => &["action", "server_id", "tool_name"],
        "import_definitions" => &["action", "server_id", "identity", "tools"],
        "store_http_credential" => &["action", "server_id", "url", "secret"],
        "remove_http_credential" => &["action", "server_id", "url"],
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

async fn bounded_read<R: AsyncRead + Unpin>(reader: R, maximum: u64) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    reader
        .take(maximum + 1)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| "Unable to read local bridge output")?;
    if bytes.len() as u64 > maximum {
        return Err("Local bridge output exceeds its size limit".into());
    }
    Ok(bytes)
}

async fn discard_stderr<R: AsyncRead + Unpin>(reader: R, maximum: u64) -> Result<(), String> {
    // Count but never retain or expose diagnostic output from the child.
    let length = tokio::io::copy(&mut reader.take(maximum + 1), &mut tokio::io::sink())
        .await
        .map_err(|_| "Unable to read local bridge diagnostics")?;
    if length > maximum {
        return Err("Local bridge diagnostics exceed their size limit".into());
    }
    Ok(())
}

async fn write_request(mut stdin: ChildStdin, bytes: Vec<u8>) -> Result<(), String> {
    stdin
        .write_all(&bytes)
        .await
        .map_err(|_| "Unable to deliver the local review request")?;
    stdin
        .shutdown()
        .await
        .map_err(|_| "Unable to finish the local review request")?;
    // Dropping stdin supplies EOF to the one-request Python bridge.
    Ok(())
}

fn parse_response(bytes: &[u8], status: ExitStatus) -> Result<Value, String> {
    let response: Value = serde_json::from_slice(bytes)
        .map_err(|_| "The local engine returned an invalid response; no decision was assumed")?;
    let object = response
        .as_object()
        .ok_or("The local engine returned an unexpected response")?;
    match object.get("ok").and_then(Value::as_bool) {
        Some(true) if object.len() == 2 && object.contains_key("data") => {
            if !status.success() {
                return Err("The local engine exited unsuccessfully; refresh the workspace".into());
            }
        }
        Some(false) if object.len() == 2 => {
            if !status.success() && status.code() != Some(1) {
                return Err("The local engine exited unsuccessfully; refresh the workspace".into());
            }
            let error = object
                .get("error")
                .and_then(Value::as_object)
                .ok_or("The local engine returned an unexpected error response")?;
            if error.len() != 2
                || !error.get("code").is_some_and(Value::is_string)
                || !error.get("message").is_some_and(Value::is_string)
            {
                return Err("The local engine returned an unexpected error response".into());
            }
            // The fixed Python module deliberately exits 1 for safe error envelopes.
        }
        _ => return Err("The local engine returned an unexpected response".into()),
    }
    Ok(response)
}

/// Run a trusted command with one deadline for stdin, both output pipes, and exit.
///
/// Only `run_bridge_before` constructs production commands. Arbitrary commands are
/// used exclusively by the hostile-child tests below, never by renderer input.
/// Timeout drops I/O futures and requests direct-child termination, without
/// blocking writes, joins, or waits outside the request deadline. This is not a
/// hard real-time guarantee for OS filesystem/process calls or runtime scheduling.
/// Tokio implements Windows process-pipe I/O with blocking workers; an underlying
/// worker/handle can outlive cancellation if a descendant retains a pipe. There is
/// no guarantee about worker lifetime or native-runtime shutdown in that case.
/// Descendants are not killed or sandboxed; dropped children are reaped on a
/// best-effort basis. A timeout may follow a committed mutation, so callers must
/// refresh rather than automatically repeat the request.
async fn communicate(
    mut command: Command,
    bytes: Vec<u8>,
    deadline: Instant,
    max_response: u64,
    max_stderr: u64,
) -> Result<Value, String> {
    if Instant::now() >= deadline {
        return Err(TIMEOUT_ERROR.into());
    }
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = command
        .spawn()
        .map_err(|_| "Unable to start the configured local Python engine")?;
    let stdin = child.stdin.take().ok_or("Local bridge input unavailable")?;
    let stdout = child
        .stdout
        .take()
        .ok_or("Local bridge output unavailable")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("Local bridge error stream unavailable")?;
    // All awaited I/O and exit share this deadline. We never join a reader after
    // timeout, including when descendants retain handles after direct-child exit.
    let result = timeout_at(deadline, async {
        tokio::try_join!(
            write_request(stdin, bytes),
            bounded_read(stdout, max_response),
            discard_stderr(stderr, max_stderr),
            async {
                child
                    .wait()
                    .await
                    .map_err(|_| "Unable to observe local bridge exit".to_string())
            },
        )
    })
    .await;
    match result {
        Ok(Ok(((), output, (), status))) => parse_response(&output, status),
        Ok(Err(error)) => {
            let _ = child.start_kill();
            Err(error)
        }
        Err(_) => {
            let _ = child.start_kill();
            Err(TIMEOUT_ERROR.into())
        }
    }
}

async fn run_bridge_before(
    runtime: BridgeRuntime,
    bytes: Vec<u8>,
    deadline: Instant,
) -> Result<Value, String> {
    // Queueing behind another request consumes this request's deadline too.
    let _lock = timeout_at(deadline, runtime.lock.lock())
        .await
        .map_err(|_| TIMEOUT_ERROR)?;
    let python = runtime.python.as_ref().ok_or(
        "Local engine unavailable. Reinstall the packaged app. For debug builds, set DRIFTGUARD_PYTHON to a trusted absolute virtual-environment executable.",
    )?;
    if !python.is_absolute() || !python.is_file() {
        return Err("The local engine must be an existing absolute executable".into());
    }
    let mut command = Command::new(python);
    if runtime.frozen {
        command.args(["bridge", "--db"]);
    } else {
        command.args(["-I", "-m", "driftguard.desktop_bridge", "--db"]);
    }
    command
        .arg(&runtime.db)
        .env_remove("PYTHONPATH")
        .env_remove("PYTHONHOME");
    #[cfg(windows)]
    {
        command.creation_flags(0x08000000);
    }
    communicate(command, bytes, deadline, MAX_RESPONSE, MAX_STDERR).await
}

async fn run_bridge(runtime: BridgeRuntime, bytes: Vec<u8>) -> Result<Value, String> {
    run_bridge_before(runtime, bytes, Instant::now() + REQUEST_TIMEOUT).await
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
    if request["action"] == "runtime_info" {
        let executable = owned
            .python
            .as_ref()
            .map(|path| path.to_string_lossy().to_string());
        let argv = executable.map(|path| {
            if owned.frozen {
                vec![path, "gateway".to_string()]
            } else {
                vec![
                    path,
                    "-I".to_string(),
                    "-m".to_string(),
                    "driftguard.gateway_cli".to_string(),
                ]
            }
        });
        return Ok(serde_json::json!({
            "ok": true,
            "data": {
                "gateway_argv": argv,
                "state_path": owned.db,
                "packaged": owned.frozen,
                "engine_available": owned.python.as_ref().is_some_and(|path| path.is_file()),
            },
        }));
    }
    run_bridge(owned, bytes).await
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
            let engine_name = if cfg!(windows) {
                "driftguard-engine.exe"
            } else {
                "driftguard-engine"
            };
            let packaged = app.path().resource_dir()?.join("engine").join(engine_name);
            let (python, frozen) = if packaged.is_file() {
                (Some(packaged), true)
            } else if cfg!(debug_assertions) {
                (
                    std::env::var_os("DRIFTGUARD_PYTHON").map(PathBuf::from),
                    false,
                )
            } else {
                (None, false)
            };
            app.manage(BridgeRuntime {
                python,
                frozen,
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
    use super::{communicate, run_bridge, run_bridge_before, validate_request, BridgeRuntime};
    use super::{MAX_REQUEST, TIMEOUT_ERROR};
    use serde_json::{json, Value};
    use std::future::Future;
    use std::path::PathBuf;
    use std::sync::Arc;
    use std::time::{Duration, Instant as WallClock, SystemTime, UNIX_EPOCH};
    use tokio::process::Command;
    use tokio::sync::Mutex;
    use tokio::time::Instant;

    fn on_runtime<F: Future>(future: F) -> F::Output {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("Unable to create native bridge test runtime");
        let result = runtime.block_on(future);
        // A Windows pipe worker can outlive a descendant-held pipe. Do not let
        // test-runtime destruction introduce the unbounded wait under test.
        runtime.shutdown_timeout(Duration::from_millis(100));
        result
    }

    fn trusted_python() -> Option<PathBuf> {
        let Some(path) = std::env::var_os("DRIFTGUARD_TEST_PYTHON") else {
            eprintln!(
                "SKIP: DRIFTGUARD_TEST_PYTHON is absent; this test requires an installed trusted Python environment"
            );
            return None;
        };
        let path = PathBuf::from(path);
        assert!(
            path.is_absolute() && path.is_file(),
            "DRIFTGUARD_TEST_PYTHON must identify an existing absolute Python executable"
        );
        Some(path)
    }

    struct TestStore(PathBuf);

    impl TestStore {
        fn new() -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("Test system time is invalid")
                .as_nanos();
            let directory = std::env::temp_dir().join(format!(
                "driftguard native revisión 测试 {} {}",
                std::process::id(),
                nonce
            ));
            std::fs::create_dir_all(&directory)
                .expect("Unable to create isolated native test store");
            Self(directory)
        }

        fn runtime(&self, python: PathBuf) -> BridgeRuntime {
            BridgeRuntime {
                python: Some(python),
                frozen: false,
                db: self.0.join("review store.sqlite3"),
                lock: Arc::new(Mutex::new(())),
            }
        }
    }

    impl Drop for TestStore {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    async fn fixed_request(runtime: &BridgeRuntime, request: Value) -> Value {
        run_bridge(
            runtime.clone(),
            validate_request(&request).expect("The native test request must be allowlisted"),
        )
        .await
        .expect("The fixed -I module must execute successfully in DRIFTGUARD_TEST_PYTHON")
    }

    async fn python_child(
        python: &PathBuf,
        source: &str,
        input: Vec<u8>,
        timeout: Duration,
        max_stdout: u64,
        max_stderr: u64,
    ) -> Result<Value, String> {
        // Arbitrary Python source is a test fixture only. The renderer cannot reach
        // this constructor or alter run_bridge_before's fixed -I -m command.
        let mut command = Command::new(python);
        command.args(["-I", "-c", source]);
        communicate(
            command,
            input,
            Instant::now() + timeout,
            max_stdout,
            max_stderr,
        )
        .await
    }

    #[test]
    fn rejects_unknown_actions_and_host_overrides() {
        assert!(validate_request(&json!({"action": "shell", "command": "whoami"})).is_err());
        assert!(validate_request(&json!({"action": "overview", "db": "/tmp/other.db"})).is_err());
        assert!(validate_request(&json!({"action": "overview", "python": "/tmp/python"})).is_err());
        assert!(validate_request(&json!({"action": "approve", "command": "whoami"})).is_err());
        assert!(validate_request(&json!({"action": "overview", "args": []})).is_err());
        assert!(validate_request(&json!({"action": "overview"})).is_ok());
    }

    #[test]
    fn rejects_oversized_renderer_request() {
        let request = json!({
            "action": "import_definitions", "server_id": "fixture", "identity": "fixture",
            "tools": [{"name": "sample", "description": "x".repeat(MAX_REQUEST)}],
        });
        assert!(validate_request(&request)
            .unwrap_err()
            .contains("size limit"));
    }

    #[test]
    fn fixed_module_reviews_unicode_store_and_enforces_exact_revision() {
        let Some(python) = trusted_python() else {
            return;
        };
        let store = TestStore::new();
        let runtime = store.runtime(python);
        on_runtime(async {
            let overview = fixed_request(&runtime, json!({"action": "overview"})).await;
            assert_eq!(overview["ok"], true);
            assert_eq!(overview["data"]["tools"], 0);
            let imported = fixed_request(
                &runtime,
                json!({
                    "action": "import_definitions", "server_id": "native-fixture",
                    "identity": "native-test-identity-v1",
                    "tools": [{
                        "name": "search_repo", "description": "Read résumé notes — 测试 🌙",
                        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                        "annotations": {"readOnlyHint": true},
                    }],
                }),
            )
            .await;
            assert_eq!(imported["ok"], true);
            let tool = &imported["data"][0];
            assert_eq!(tool["server_id"], "import:native-fixture");
            assert_eq!(tool["status"], "pending");
            let review_request = json!({
                "action": "review", "server_id": "import:native-fixture", "tool_name": "search_repo",
            });
            let review = fixed_request(&runtime, review_request.clone()).await;
            assert_eq!(review["data"]["new_tool"]["name"], "search_repo");
            assert_eq!(
                review["data"]["new_tool"]["description"],
                "Read résumé notes — 测试 🌙"
            );
            assert!(review["data"]["old_tool"].is_null());
            let approve_request = json!({
                "action": "approve", "server_id": "import:native-fixture", "tool_name": "search_repo",
                "expected_sha256": tool["sha256"], "expected_revision": tool["revision"],
            });
            let approved = fixed_request(&runtime, approve_request.clone()).await;
            assert_eq!(approved["ok"], true);
            assert_eq!(approved["data"]["status"], "approved");
            assert!(
                approved["data"]["revision"]
                    .as_u64()
                    .expect("Approved revision is required")
                    > tool["revision"]
                        .as_u64()
                        .expect("Observed revision is required")
            );
            // Python's exit-1 structured rejection must survive the native boundary.
            let stale = fixed_request(&runtime, approve_request).await;
            assert_eq!(stale["ok"], false);
            assert_eq!(stale["error"]["code"], "review_rejected");
            let quarantined = fixed_request(
                &runtime,
                json!({
                    "action": "quarantine", "server_id": "import:native-fixture", "tool_name": "search_repo",
                    "expected_sha256": approved["data"]["sha256"], "expected_revision": approved["data"]["revision"],
                }),
            )
            .await;
            assert_eq!(quarantined["data"]["status"], "quarantined");
            let denied = fixed_request(
                &runtime,
                json!({
                    "action": "deny", "server_id": "import:native-fixture", "tool_name": "search_repo",
                    "expected_sha256": quarantined["data"]["sha256"], "expected_revision": quarantined["data"]["revision"],
                }),
            )
            .await;
            assert_eq!(denied["data"]["status"], "denied");
            let latched = fixed_request(
                &runtime,
                json!({
                    "action": "approve", "server_id": "import:native-fixture", "tool_name": "search_repo",
                    "expected_sha256": denied["data"]["sha256"], "expected_revision": denied["data"]["revision"],
                }),
            )
            .await;
            assert_eq!(latched["ok"], false);
            let persisted = fixed_request(&runtime, review_request).await;
            assert_eq!(persisted["data"]["status"], "denied");
            assert_eq!(persisted["data"]["revision"], denied["data"]["revision"]);
            let activity = fixed_request(&runtime, json!({"action": "activity"})).await;
            assert!(activity["data"]
                .as_array()
                .is_some_and(|events| !events.is_empty()));
        });
        assert!(runtime.db.is_file());
    }

    #[test]
    fn shared_deadline_includes_waiting_for_the_bridge_lock() {
        on_runtime(async {
            let lock = Arc::new(Mutex::new(()));
            let _guard = lock.lock().await;
            let runtime = BridgeRuntime {
                python: None,
                frozen: false,
                db: PathBuf::new(),
                lock: lock.clone(),
            };
            let started = WallClock::now();
            let error = run_bridge_before(
                runtime,
                Vec::new(),
                Instant::now() + Duration::from_millis(30),
            )
            .await
            .unwrap_err();
            assert_eq!(error, TIMEOUT_ERROR);
            assert!(started.elapsed() < Duration::from_secs(2));
        });
    }

    #[test]
    fn deadline_covers_a_child_that_never_reads_full_stdin_pipe() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let started = WallClock::now();
            let error = python_child(
                &python,
                "import time; time.sleep(30)",
                vec![b'x'; MAX_REQUEST],
                Duration::from_millis(500),
                4096,
                4096,
            )
            .await
            .unwrap_err();
            assert_eq!(error, TIMEOUT_ERROR);
            assert!(started.elapsed() < Duration::from_secs(5));
        });
    }

    #[test]
    fn deadline_includes_exit_after_complete_output() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let started = WallClock::now();
            let error = python_child(
                &python,
                "import sys,time; sys.stdin.buffer.read(); print('{\"ok\":true,\"data\":{}}',flush=True); time.sleep(30)",
                b"{}".to_vec(), Duration::from_millis(500), 4096, 4096,
            ).await.unwrap_err();
            assert_eq!(error, TIMEOUT_ERROR);
            assert!(started.elapsed() < Duration::from_secs(5));
        });
    }

    #[test]
    fn descendant_held_output_pipes_cannot_force_an_unbounded_join() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let started = WallClock::now();
            let error = python_child(
                &python,
                "import subprocess,sys; sys.stdin.buffer.read(); subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(2)'],stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr); print('{\"ok\":true,\"data\":{}}',flush=True)",
                b"{}".to_vec(), Duration::from_millis(500), 4096, 4096,
            ).await.unwrap_err();
            assert_eq!(error, TIMEOUT_ERROR);
            assert!(started.elapsed() < Duration::from_secs(5));
            // The short-lived descendant is deliberately not claimed to be killed.
        });
    }

    #[test]
    fn oversized_stdout_fails_before_a_child_finishes() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let started = WallClock::now();
            let error = python_child(
                &python,
                "import sys,time; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*4097); sys.stdout.flush(); time.sleep(30)",
                b"{}".to_vec(), Duration::from_secs(5), 4096, 4096,
            ).await.unwrap_err();
            assert_eq!(error, "Local bridge output exceeds its size limit");
            assert!(started.elapsed() < Duration::from_secs(5));
        });
    }

    #[test]
    fn oversized_stderr_fails_without_exposing_diagnostics() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let error = python_child(
                &python,
                "import sys,time; sys.stdin.buffer.read(); sys.stderr.write('SECRET_DIAGNOSTIC'*300); sys.stderr.flush(); time.sleep(30)",
                b"{}".to_vec(), Duration::from_secs(5), 4096, 4096,
            ).await.unwrap_err();
            assert_eq!(error, "Local bridge diagnostics exceed their size limit");
            assert!(!error.contains("SECRET_DIAGNOSTIC"));
        });
    }

    #[test]
    fn rejects_success_looking_output_from_nonzero_exit() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let error = python_child(
                &python,
                "import sys; sys.stdin.buffer.read(); print('{\"ok\":true,\"data\":{}}'); sys.exit(7)",
                b"{}".to_vec(), Duration::from_secs(5), 4096, 4096,
            ).await.unwrap_err();
            assert_eq!(
                error,
                "The local engine exited unsuccessfully; refresh the workspace"
            );
        });
    }

    #[test]
    fn accepts_only_well_formed_bridge_error_envelopes() {
        let Some(python) = trusted_python() else {
            return;
        };
        on_runtime(async {
            let response = python_child(
                &python,
                "import sys; sys.stdin.buffer.read(); print('{\"ok\":false,\"error\":{\"code\":\"invalid_request\",\"message\":\"Safe rejection\"}}'); sys.exit(1)",
                b"{}".to_vec(), Duration::from_secs(5), 4096, 4096,
            ).await.unwrap();
            assert_eq!(response["ok"], false);
            assert_eq!(response["error"]["message"], "Safe rejection");
            for output in [
                "not-json",
                "[]",
                "{\"ok\":true}",
                "{\"ok\":\"true\",\"data\":{}}",
                "{\"ok\":false,\"error\":\"invalid\"}",
                "{\"ok\":false,\"error\":{\"code\":\"bad\",\"message\":42}}",
                "{\"ok\":true,\"data\":{}}\n{\"ok\":true,\"data\":{}}",
            ] {
                let source = format!("import sys; sys.stdin.buffer.read(); print({output:?})");
                let error = python_child(
                    &python,
                    &source,
                    b"{}".to_vec(),
                    Duration::from_secs(5),
                    4096,
                    4096,
                )
                .await
                .unwrap_err();
                assert!(error.starts_with("The local engine returned an "));
                assert!(!error.contains(output));
            }
        });
    }
}
