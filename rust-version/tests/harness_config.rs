use std::fs;
use std::path::Path;
use std::process::{Command, Output};

use serde_json::Value;

fn harness(root: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
        .arg("--db")
        .arg(root.join("review.sqlite3"))
        .arg("harness")
        .args(args)
        .env("DRIFTGUARD_HARNESS_HOME", root)
        .output()
        .unwrap()
}

fn data(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stdout)
    );
    serde_json::from_slice::<Value>(&output.stdout).unwrap()["data"].clone()
}

#[test]
fn helper_inventory_persists_changes_without_exposing_contents() {
    use std::io::Write;
    use std::process::Stdio;
    let root = tempfile::tempdir().unwrap();
    let scan = || {
        let mut child = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
            .arg("--db")
            .arg(root.path().join("review.sqlite"))
            .env("DRIFTGUARD_HARNESS_HOME", root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(
            child.stdin.take().unwrap(),
            "{{\"action\":\"harness_helpers\"}}"
        )
        .unwrap();
        data(child.wait_with_output().unwrap())
    };
    let skill = root.path().join(".agents/skills/notes/SKILL.md");
    let hooks = root.path().join(".codex/hooks.json");
    let config = root.path().join(".codex/config.toml");
    let subagent = root.path().join(".claude/agents/reviewer.md");
    for path in [&skill, &hooks, &subagent] {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
    }
    fs::write(&skill, "Private test text").unwrap();
    fs::write(
        &hooks,
        r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"fixture-only"}]}]}}"#,
    )
    .unwrap();
    fs::write(&config, "[plugins.'notes@test']\nenabled = true\n").unwrap();
    fs::write(&subagent, "Read-only reviewer").unwrap();
    let initial = scan();
    assert_eq!(initial["helpers"].as_array().unwrap().len(), 4);
    assert_eq!(initial["changes"], serde_json::json!([]));
    assert_eq!(initial["new_changes"], 0);
    assert!(!initial.to_string().contains("Private test text"));
    assert!(!initial.to_string().contains("fixture-only"));

    fs::write(&skill, "Updated instructions").unwrap();
    fs::write(&config, "[plugins.'notes@test']\nenabled = false\n").unwrap();
    fs::remove_file(subagent).unwrap();
    let changed = scan();
    let changes = changed["changes"].as_array().unwrap();
    assert_eq!(changes.len(), 3);
    assert_eq!(changed["new_changes"], 3);
    assert!(changes
        .iter()
        .any(|item| item["kind"] == "skill" && item["change"] == "modified"));
    assert!(changes
        .iter()
        .any(|item| item["kind"] == "plugin" && item["change"] == "modified"));
    assert!(changes
        .iter()
        .any(|item| item["kind"] == "subagent" && item["change"] == "removed"));
    assert_eq!(scan()["changes"], changed["changes"]);
    fs::write(&config, "invalid [").unwrap();
    let incomplete = scan();
    assert!(!incomplete["issues"].as_array().unwrap().is_empty());
    assert_eq!(incomplete["changes"], changed["changes"]);
}

#[test]
fn configured_harness_catalogs_are_discovered_without_a_client_session() {
    let root = tempfile::tempdir().unwrap();
    let binary = env!("CARGO_BIN_EXE_driftguard-rust");
    let db = root.path().join("review.sqlite3");
    let bridge = |request: Value| {
        use std::io::Write;
        use std::process::Stdio;
        let mut process = Command::new(binary)
            .arg("--db")
            .arg(&db)
            .env("DRIFTGUARD_HARNESS_HOME", root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(process.stdin.take().unwrap(), "{request}").unwrap();
        data(process.wait_with_output().unwrap())
    };
    let config = root.path().join(".codex/config.toml");
    fs::create_dir_all(config.parent().unwrap()).unwrap();
    fs::write(&config, format!(
        "[mcp_servers.notes]\ncommand = {}\nargs = ['sample-server']\n\n[mcp_servers.disabled]\nenabled = false\ncommand = 'missing'\n\n[mcp_servers.broken]\ncommand = 'driftguard-missing-test-executable'\n",
        serde_json::to_string(binary).unwrap(),
    )).unwrap();
    bridge(serde_json::json!({"action":"live_connect","harness":"codex"}));
    let gemini = root.path().join(".gemini/settings.json");
    fs::create_dir_all(gemini.parent().unwrap()).unwrap();
    fs::write(
        &gemini,
        serde_json::json!({"mcpServers":{"reference":{
            "command":binary,"args":["sample-server"]
        }}})
        .to_string(),
    )
    .unwrap();
    bridge(serde_json::json!({"action":"live_connect","harness":"gemini"}));
    let original = fs::read(&config).unwrap();
    let original_gemini = fs::read(&gemini).unwrap();
    let report = bridge(serde_json::json!({"action":"sync_harness_catalogs"}));
    let servers = report["servers"].as_array().unwrap();
    assert_eq!(servers.len(), 3);
    assert!(servers
        .iter()
        .any(|row| row["name"] == "broken" && row["state"] == "unavailable"));
    assert!(servers
        .iter()
        .any(|row| row["name"] == "notes" && row["tools"] == 1));
    assert_eq!(fs::read(&config).unwrap(), original);
    assert_eq!(fs::read(&gemini).unwrap(), original_gemini);
    let graph = bridge(serde_json::json!({"action":"connection_graph"}));
    assert_eq!(graph[0]["source_id"], "harness:codex:notes");
    assert_eq!(graph[0]["client_label"], "Codex");
    assert_eq!(graph[0]["kind"], "review");
    assert_eq!(graph[0]["active"], false);
    assert_eq!(graph[0]["tools"][0]["tool_name"], "read_sample");
    assert_eq!(graph[1]["source_id"], "harness:gemini:reference");
    assert_eq!(graph[1]["client_label"], "Gemini CLI");
    assert_eq!(graph[1]["tools"][0]["tool_name"], "read_sample");
    assert_eq!(
        bridge(serde_json::json!({"action":"overview"}))["protection_status"],
        "review_only"
    );
}

#[test]
fn all_managed_configs_restore_original_bytes() {
    let root = tempfile::tempdir().unwrap();
    let profile = root.path().join("profile.json");
    fs::write(&profile, "{}").unwrap();
    let profile = profile.to_str().unwrap();
    let harnesses = data(harness(root.path(), &["list"]));
    let paths = harnesses.as_array().unwrap();
    assert_eq!(paths.len(), 7);
    for harness_info in paths {
        let id = harness_info["id"].as_str().unwrap();
        let path = Path::new(harness_info["config_path"].as_str().unwrap());
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let original = match id {
            "codex" => "# comment\nmodel = 'example'\n",
            "opencode" | "vscode" => "{\n // comment\n \"existing\": true,\n}\n",
            _ => "{ \"existing\": true }\n",
        };
        fs::write(path, original).unwrap();
        data(harness(root.path(), &["connect", id, profile]));
        let installed = fs::read_to_string(path).unwrap();
        assert!(installed.contains("driftguard-rust"));
        assert!(installed.contains("--client"));
        data(harness(root.path(), &["connect", id, profile]));
        assert_eq!(fs::read_to_string(path).unwrap(), installed);
        data(harness(root.path(), &["disconnect", id]));
        assert_eq!(fs::read_to_string(path).unwrap(), original);
    }
}

#[test]
fn disconnect_keeps_new_comments_and_user_entries() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join(".config/opencode/opencode.jsonc");
    fs::create_dir_all(config.parent().unwrap()).unwrap();
    let profile = root.path().join("profile.json");
    fs::write(&profile, "{}").unwrap();
    let original = "{\n \"mcp\": {\"servers\": {\"existing\": {\"type\": \"local\", \"command\": [\"original\"]}}}\n}\n";
    fs::write(&config, original).unwrap();
    data(harness(
        root.path(),
        &["connect", "opencode", profile.to_str().unwrap()],
    ));
    let edited = fs::read_to_string(&config)
        .unwrap()
        .replace("\"original\"", "\"new command\"")
        .replace("{\n", "{\n // user comment\n");
    fs::write(&config, edited).unwrap();
    data(harness(root.path(), &["disconnect", "opencode"]));
    let cleaned = fs::read_to_string(config).unwrap();
    assert!(cleaned.contains("\"new command\""));
    assert!(cleaned.contains("// user comment"));
    assert!(!cleaned.contains("driftguard-rust"));
}

#[test]
fn codex_preserves_inline_settings_and_user_changes() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join(".codex/config.toml");
    fs::create_dir_all(config.parent().unwrap()).unwrap();
    let profile = root.path().join("profile.json");
    fs::write(&profile, "{}").unwrap();
    fs::write(
        &config,
        "mcp_servers = { old = {command = 'original', args = []} } # keep this\n",
    )
    .unwrap();
    data(harness(
        root.path(),
        &["connect", "codex", profile.to_str().unwrap()],
    ));
    let edited = fs::read_to_string(&config)
        .unwrap()
        .replace("'original'", "'new command'")
        + "# new comment\n";
    fs::write(&config, edited).unwrap();
    data(harness(root.path(), &["disconnect", "codex"]));
    let cleaned = fs::read_to_string(config).unwrap();
    assert!(cleaned.contains("'new command'"));
    assert!(cleaned.contains("# keep this"));
    assert!(cleaned.contains("# new comment"));
    assert!(!cleaned.contains("driftguard-rust"));
}

#[test]
fn profile_change_requires_reconnect_and_disconnect_preserves_an_edited_entry() {
    let root = tempfile::tempdir().unwrap();
    let profile = root.path().join("profile.json");
    fs::write(&profile, "{}").unwrap();
    let codex = data(harness(
        root.path(),
        &["connect", "codex", profile.to_str().unwrap()],
    ));
    let config = Path::new(codex["config_path"].as_str().unwrap());
    fs::write(&profile, "{\"other\": true}").unwrap();
    let available = data(harness(root.path(), &["list"]));
    assert_eq!(available[0]["connected"], false);
    assert!(!harness(
        root.path(),
        &["connect", "codex", profile.to_str().unwrap()]
    )
    .status
    .success());

    let edited = fs::read_to_string(config)
        .unwrap()
        .replace("--client", "--changed");
    fs::write(config, &edited).unwrap();
    let disconnected = harness(root.path(), &["disconnect", "codex"]);
    assert!(!disconnected.status.success());
    assert_eq!(fs::read_to_string(config).unwrap(), edited);
    fs::remove_file(config).unwrap();
    data(harness(root.path(), &["disconnect", "codex"]));
}

#[test]
fn routes_supported_codex_entries_and_restores_original_bytes() {
    let root = tempfile::tempdir().unwrap();
    let config = root.path().join(".codex/config.toml");
    fs::create_dir(config.parent().unwrap()).unwrap();
    let original = r#"# user settings
[mcp_servers.notes]
command = "/usr/bin/true"
args = ["example"]
[mcp_servers.remote]
url = "https://example.com/mcp"
bearer_token_env_var = "EXAMPLE_TOKEN"
[mcp_servers.oauth]
url = "https://example.org/mcp"
[mcp_servers.disabled]
command = "/usr/bin/true"
enabled = false
"#;
    fs::write(&config, original).unwrap();
    let result = data(harness(root.path(), &["route", "codex"]));
    assert_eq!(result["routed"], serde_json::json!(["notes", "remote"]));
    let edited = fs::read_to_string(&config).unwrap();
    assert!(edited.contains("--route"));
    assert!(edited.contains("https://example.org/mcp"));
    assert!(edited.contains("enabled = false"));
    data(harness(root.path(), &["restore", "codex"]));
    assert_eq!(fs::read_to_string(config).unwrap(), original);
}

#[test]
fn standalone_gateway_registers_a_route_before_any_harness_connects() {
    use std::io::Write;
    use std::process::Stdio;
    let root = tempfile::tempdir().unwrap();
    let db = root.path().join("review.sqlite");
    let request = |payload: Value| {
        let mut process = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
            .args(["--db", db.to_str().unwrap()])
            .env("DRIFTGUARD_HARNESS_HOME", root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(process.stdin.take().unwrap(), "{payload}").unwrap();
        serde_json::from_slice::<Value>(&process.wait_with_output().unwrap().stdout).unwrap()
    };
    assert_eq!(
        request(
            serde_json::json!({"action":"save_gateway_server","server_id":"example",
        "transport":"http","url":"https://example.com/mcp"})
        )["ok"],
        true
    );
    let launch = request(serde_json::json!({"action":"launch_gateway_only_codex"}));
    assert_eq!(launch["data"]["opened"], false);
    assert_eq!(launch["data"]["skipped"][0]["server_id"], "example");
    assert!(launch["data"].get("command").is_none());
    let graph = request(serde_json::json!({"action":"connection_graph"}));
    assert_eq!(graph["data"][0]["server_id"], "example");
    assert_eq!(graph["data"][0]["connection_state"], "configured");
    assert_eq!(graph["data"][0]["active"], false);
    assert_eq!(
        request(
            serde_json::json!({"action":"save_gateway_server","server_id":"example",
        "transport":"http","url":"http://example.com/mcp"})
        )["ok"],
        false
    );
    let rpc = |action, name| request(serde_json::json!({"action":action,"server_id":name}));
    assert_eq!(rpc("link_gateway_server_codex", "example")["ok"], true);
    for harness in [
        "claude",
        "cursor",
        "antigravity",
        "gemini",
        "opencode",
        "vscode",
    ] {
        assert_eq!(
            request(
                serde_json::json!({"action":"link_gateway_server","server_id":"example","harness":harness})
            )["ok"],
            true,
            "{harness}"
        );
    }
    let settings = root.path().join(".codex/config.toml");
    assert!(fs::read_to_string(&settings)
        .unwrap()
        .contains("--registered"));

    let engine = env!("CARGO_BIN_EXE_driftguard-rust");
    // Manual review is the default; this flow opts in to approving declared read-only tools.
    assert_eq!(
        request(serde_json::json!({"action":"set_approval_mode","mode":"read_only"}))["ok"],
        true
    );
    assert_eq!(
        request(
            serde_json::json!({"action":"save_gateway_server","server_id":"sample",
        "transport":"stdio","argv":[engine,"sample-server"],"pass_env":[],
        "cwd":root.path()})
        )["ok"],
        true
    );
    assert_eq!(
        rpc("check_gateway_server", "sample")["data"][1]["state"],
        "catalog_ready"
    );
    assert_eq!(
        request(serde_json::json!({"action":"connection_graph"}))["data"][0]["tools"][0]
            ["tool_name"],
        "read_sample"
    );

    let mut gateway = Command::new(engine)
        .args([
            "--db",
            db.to_str().unwrap(),
            "serve",
            "--registered",
            "sample",
            "--harness",
            "cursor",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut input = gateway.stdin.take().unwrap();
    let mut output = std::io::BufReader::new(gateway.stdout.take().unwrap());
    use std::io::BufRead;
    let mut rpc_gateway = |message: Value| {
        writeln!(input, "{message}").unwrap();
        let mut line = String::new();
        if message["id"].is_null() {
            return Value::Null;
        }
        loop {
            line.clear();
            assert_ne!(output.read_line(&mut line).unwrap(), 0);
            let reply: Value = serde_json::from_str(&line).unwrap();
            if reply["id"] == message["id"] {
                return reply;
            }
        }
    };
    assert!(rpc_gateway(
        serde_json::json!({"jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-11-25"}})
    )["result"]
        .is_object());
    rpc_gateway(serde_json::json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
    let result = rpc_gateway(
        serde_json::json!({"jsonrpc":"2.0","id":2,"method":"tools/call",
        "params":{"name":"read_sample","arguments":{}}}),
    );
    assert_eq!(
        result["result"]["content"][0]["text"],
        "DriftGuard live integration check\n"
    );
    drop(input);
    assert!(gateway.wait().unwrap().success());
    let activity = request(serde_json::json!({"action":"sentinel_calls"}));
    assert_eq!(activity["data"][0]["source"], "gateway:cursor:sample");
    assert_eq!(rpc("remove_gateway_server", "example")["ok"], true);
    assert!(!fs::read_to_string(settings)
        .unwrap()
        .contains("--registered"));
}
