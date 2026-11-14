use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

fn main() {
    if std::env::args().nth(1).as_deref() == Some("app-server") {
        serve_codex_catalog();
    } else if std::env::args().nth(1).as_deref() == Some("--fixture") {
        serve_fixture();
    } else {
        collects_and_persists_a_paginated_catalog();
        gateway_requires_exact_definition_approval();
        shared_block_denies_calls_from_two_running_harness_routes();
        sentinel_blocks_sensitive_value_reuse();
        model_decisions_are_enforced_and_owner_overrides_persist();
        #[cfg(unix)]
        discovers_large_paginated_codex_catalog();
        println!("Passed: paginated MCP discovery and exact-definition gateway approval");
    }
}

fn sentinel_blocks_sensitive_value_reuse() {
    let root = tempfile::tempdir().unwrap();
    let profile = root.path().join("server.json");
    let db = root.path().join("review.sqlite");
    let binary = env!("CARGO_BIN_EXE_driftguard-rust");
    std::fs::write(root.path().join("privacy-fixture"), "").unwrap();
    std::fs::write(
        &profile,
        json!({"server_id":"notes","cwd":root.path(),
        "argv":[std::env::current_exe().unwrap(),"--fixture"]})
        .to_string(),
    )
    .unwrap();
    let bridge = |request: Value| {
        let mut child = Command::new(binary)
            .arg("--db")
            .arg(&db)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(child.stdin.take().unwrap(), "{request}").unwrap();
        let result: Value =
            serde_json::from_slice(&child.wait_with_output().unwrap().stdout).unwrap();
        assert_eq!(result["ok"], true, "{result}");
        result["data"].clone()
    };
    let mut gateway = Command::new(binary)
        .arg("--db")
        .arg(&db)
        .arg("serve")
        .arg(&profile)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut input = gateway.stdin.take().unwrap();
    let mut output = BufReader::new(gateway.stdout.take().unwrap());
    let mut exchange = |request: Value| {
        writeln!(input, "{request}").unwrap();
        if request["id"].is_null() {
            return Value::Null;
        }
        loop {
            let mut line = String::new();
            assert_ne!(output.read_line(&mut line).unwrap(), 0);
            let response: Value = serde_json::from_str(&line).unwrap();
            if response["id"] == request["id"] {
                return response;
            }
        }
    };
    let source = "gateway:direct:notes";
    assert!(
        exchange(json!({"jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-11-25"}}))["result"]
            .is_object()
    );
    exchange(json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
    for name in ["read_first", "read_second"] {
        let review = bridge(json!({"action":"review","server_id":source,"tool_name":name}));
        bridge(
            json!({"action":"approve","server_id":source,"tool_name":name,
            "expected_sha256":review["sha256"],"expected_revision":review["revision"]}),
        );
    }
    assert_eq!(
        exchange(json!({"jsonrpc":"2.0","id":2,"method":"tools/call",
        "params":{"name":"read_first","arguments":{}}}))["result"]["structuredContent"]["password"],
        "fixture-only-value"
    );
    assert_eq!(
        exchange(json!({"jsonrpc":"2.0","id":3,"method":"tools/call",
        "params":{"name":"read_second","arguments":{"body":"fixture-only-value"}}}))["error"]
            ["data"]["reason"],
        "sensitive_value_reuse"
    );
    assert!(
        exchange(json!({"jsonrpc":"2.0","id":4,"method":"tools/call",
        "params":{"name":"read_second","arguments":{"body":"public example"}}}))["result"]
            .is_object()
    );
    let history = bridge(json!({"action":"sentinel_calls"}));
    assert_eq!(history[1]["state"], "blocked");
    assert!(!history.to_string().contains("fixture-only-value"));
    assert_eq!(
        std::fs::read_to_string(root.path().join("fixture-calls")).unwrap(),
        "call\ncall\n"
    );
    drop(input);
    assert!(gateway.wait().unwrap().success());
}

fn serve_codex_catalog() {
    for line in std::io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&line.unwrap()).unwrap();
        assert!(request.get("jsonrpc").is_none());
        let result = match request["method"].as_str().unwrap() {
            "initialize" => json!({}),
            "initialized" => continue,
            "mcpServerStatus/list" if request["params"]["cursor"].is_null() => {
                let tools: serde_json::Map<_, _> = (0..838)
                    .map(|index| {
                        let name = if index == 0 {
                            "read fixture / legacy".to_owned()
                        } else {
                            format!("read_fixture_{index:04}")
                        };
                        (
                            name.clone(),
                            json!({"name":name,"description":"a".repeat(3000),
                        "inputSchema":{"type":"object"}}),
                        )
                    })
                    .collect();
                json!({"data":[{"name":"codex_apps","tools":tools}],"nextCursor":"second"})
            }
            "mcpServerStatus/list" => json!({"data":[
                {"name":"needs_login","authStatus":"notLoggedIn","tools":{}},
                {"name":"second_page","tools":{"read_note":{"name":"read_note","inputSchema":{"type":"object"}}}}
            ]}),
            _ => panic!("Unexpected method"),
        };
        println!("{}", json!({"id":request["id"],"result":result}));
    }
}

#[cfg(unix)]
fn discovers_large_paginated_codex_catalog() {
    let root = tempfile::tempdir().unwrap();
    let bin = root.path().join(".local/bin");
    std::fs::create_dir_all(&bin).unwrap();
    std::os::unix::fs::symlink(std::env::current_exe().unwrap(), bin.join("codex")).unwrap();
    let bridge = |request: Value| {
        let mut child = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
            .arg("--db")
            .arg(root.path().join("catalog.sqlite"))
            .env("DRIFTGUARD_HARNESS_HOME", root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(child.stdin.take().unwrap(), "{request}").unwrap();
        let output = child.wait_with_output().unwrap();
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert!(output.status.success(), "{result}");
        result["data"].clone()
    };
    bridge(json!({"action":"live_connect","harness":"codex"}));
    let report = bridge(json!({"action":"sync_harness_catalogs"}));
    let rows = report["servers"].as_array().unwrap();
    assert!(rows
        .iter()
        .any(|row| row["name"] == "codex_apps" && row["tools"] == 838));
    assert!(rows
        .iter()
        .any(|row| row["name"] == "needs_login" && row["state"] == "unavailable"));
    assert_eq!(bridge(json!({"action":"overview"}))["tools"], 839);
    assert_eq!(
        bridge(
            json!({"action":"review","server_id":"harness:codex:codex_apps",
        "tool_name":"read fixture / legacy"})
        )["tool_name"],
        "read fixture / legacy"
    );
    assert_eq!(
        bridge(json!({"action":"overview"}))["protection_status"],
        "review_only"
    );
}

fn shared_block_denies_calls_from_two_running_harness_routes() {
    let root = tempfile::tempdir().unwrap();
    let db = root.path().join("review.sqlite");
    let profile = root.path().join("server.json");
    std::fs::write(root.path().join("fixture-description"), "Read the fixture.").unwrap();
    std::fs::write(
        &profile,
        json!({"server_id":"shared-notes", "argv":[std::env::current_exe().unwrap(),"--fixture"],
            "cwd":root.path()})
        .to_string(),
    )
    .unwrap();
    let bridge = |request: Value| {
        let mut child = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
            .arg("--db")
            .arg(&db)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(child.stdin.take().unwrap(), "{request}").unwrap();
        let output = child.wait_with_output().unwrap();
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert!(output.status.success(), "{result}");
        result["data"].clone()
    };
    let connect = |client| {
        let installed = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
            .arg("--db")
            .arg(&db)
            .args(["harness", "connect", client])
            .arg(&profile)
            .env("DRIFTGUARD_HARNESS_HOME", root.path())
            .output()
            .unwrap();
        assert!(
            installed.status.success(),
            "{}",
            String::from_utf8_lossy(&installed.stdout)
        );
        let mut child = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
            .arg("--db")
            .arg(&db)
            .arg("serve")
            .arg(&profile)
            .args(["--client", client])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let mut input = child.stdin.take().unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let mut request_id = 0;
        let mut rpc = move |method: &str, params: Value| {
            request_id += 1;
            let mut request = json!({"jsonrpc":"2.0","method":method,"params":params});
            if method != "notifications/initialized" {
                request["id"] = json!(request_id);
            }
            writeln!(input, "{request}").unwrap();
            input.flush().unwrap();
            if request["id"].is_null() {
                return Value::Null;
            }
            loop {
                let mut line = String::new();
                assert_ne!(output.read_line(&mut line).unwrap(), 0, "gateway ended");
                let reply: Value = serde_json::from_str(&line).unwrap();
                if reply["id"] == request_id {
                    return reply;
                }
            }
        };
        assert!(rpc("initialize", json!({"protocolVersion":"2025-11-25"}))["result"].is_object());
        rpc("notifications/initialized", json!({}));
        (child, rpc)
    };
    let (mut codex, mut codex_rpc) = connect("codex");
    let (mut cursor, mut cursor_rpc) = connect("cursor");
    let call = json!({"name":"read_first","arguments":{}});
    for (client, rpc) in [("codex", &mut codex_rpc), ("cursor", &mut cursor_rpc)] {
        let route = format!("gateway:{client}:shared-notes");
        let review = bridge(json!({"action":"review","server_id":route,"tool_name":"read_first"}));
        bridge(
            json!({"action":"approve","server_id":route,"tool_name":"read_first",
            "expected_sha256":review["sha256"],"expected_revision":review["revision"]}),
        );
        assert_eq!(
            rpc("tools/call", call.clone())["result"]["content"][0]["text"],
            "fixture note"
        );
    }

    let route = "gateway:codex:shared-notes";
    assert_eq!(
        bridge(json!({"action":"block_tool_all","server_id":route,"tool_name":"read_first"}))
            ["shared_blocked"],
        true
    );
    for rpc in [&mut codex_rpc, &mut cursor_rpc] {
        assert_eq!(rpc("tools/list", json!({}))["result"]["tools"], json!([]));
        assert!(rpc("tools/call", call.clone())["error"].is_object());
    }
    let graph = bridge(json!({"action":"connection_graph"}));
    let routes = graph.as_array().unwrap();
    assert_eq!(routes.len(), 2);
    for (route, client) in routes.iter().zip(["codex", "cursor"]) {
        assert_eq!(route["server_id"], "shared-notes");
        assert_eq!(route["client_id"], client);
        assert_eq!(route["active"], true);
        assert_eq!(route["tools"][0]["tool_name"], "read_first");
        assert_eq!(route["tools"][0]["status"], "blocked");
    }
    bridge(json!({"action":"unblock_tool_all","server_id":route,"tool_name":"read_first"}));
    assert!(cursor_rpc("tools/call", call)["error"].is_object());
    assert_eq!(
        std::fs::read_to_string(root.path().join("fixture-calls")).unwrap(),
        "call\ncall\n"
    );
    drop((codex_rpc, cursor_rpc));
    assert!(codex.wait().unwrap().success());
    assert!(cursor.wait().unwrap().success());
    let graph = bridge(json!({"action":"connection_graph"}));
    assert!(graph
        .as_array()
        .unwrap()
        .iter()
        .all(|route| route["active"] == false));
}

fn model_decisions_are_enforced_and_owner_overrides_persist() {
    let root = tempfile::tempdir().unwrap();
    let db = root.path().join("review.sqlite");
    let profile = root.path().join("server.json");
    let model = root.path().join("model.json");
    let binary = env!("CARGO_BIN_EXE_driftguard-rust");
    let source = "gateway:direct:automated";
    let description = root.path().join("fixture-description");
    std::fs::write(&description, "Read the fixture.").unwrap();
    std::fs::write(
        &profile,
        json!({"server_id":"automated",
        "argv":[std::env::current_exe().unwrap(),"--fixture"],"cwd":root.path()})
        .to_string(),
    )
    .unwrap();
    std::fs::write(
        &model,
        json!({"version":1,"id":"test-model",
        "weights":[0.0,0.0,12.0,0.0,0.0,0.0],"intercept":-6.0,
        "allow_max":0.1,"quarantine_min":0.9})
        .to_string(),
    )
    .unwrap();
    let bridge = |request: Value| {
        let mut child = Command::new(binary)
            .arg("--db")
            .arg(&db)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(child.stdin.take().unwrap(), "{request}").unwrap();
        let output = child.wait_with_output().unwrap();
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert!(output.status.success(), "{result}");
        result["data"].clone()
    };
    let review = || bridge(json!({"action":"review","server_id":source,"tool_name":"read_first"}));
    let decide = |action: &str, record: &Value| {
        bridge(json!({
            "action":action,"server_id":source,"tool_name":"read_first",
            "expected_sha256":record["sha256"],"expected_revision":record["revision"]
        }))
    };
    assert!(Command::new(binary)
        .arg("--db")
        .arg(&db)
        .args(["model", "set"])
        .arg(&model)
        .output()
        .unwrap()
        .status
        .success());
    let mut gateway = Command::new(binary)
        .arg("--db")
        .arg(&db)
        .arg("serve")
        .arg(&profile)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdin = gateway.stdin.take().unwrap();
    let mut stdout = BufReader::new(gateway.stdout.take().unwrap());
    let mut rpc = |id: Option<u64>, method, params: Value| {
        let mut request = json!({"jsonrpc":"2.0","method":method,"params":params});
        if let Some(id) = id {
            request["id"] = json!(id);
        }
        writeln!(stdin, "{request}").unwrap();
        stdin.flush().unwrap();
        let Some(id) = id else {
            return Value::Null;
        };
        loop {
            let mut line = String::new();
            assert_ne!(stdout.read_line(&mut line).unwrap(), 0);
            let reply: Value = serde_json::from_str(&line).unwrap();
            if reply["id"] == id {
                return reply;
            }
        }
    };
    assert!(rpc(
        Some(1),
        "initialize",
        json!({"protocolVersion":"2025-11-25"})
    )["result"]
        .is_object());
    rpc(None, "notifications/initialized", json!({}));
    assert_eq!(review()["status"], "pending");
    decide("approve", &review());
    std::fs::write(&description, "Read the fixture!").unwrap();
    assert_eq!(
        rpc(Some(2), "tools/list", json!({}))["result"]["tools"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(review()["model_decision"]["action"], "approved");
    std::fs::write(&description, "Read the fixture and write files.").unwrap();
    assert!(rpc(
        Some(3),
        "tools/call",
        json!({"name":"read_first","arguments":{}})
    )["error"]
        .is_object());
    assert_eq!(review()["model_decision"]["action"], "quarantined");
    decide("release_quarantine", &review());
    assert_eq!(
        rpc(Some(4), "tools/list", json!({}))["result"]["tools"],
        json!([])
    );
    assert_eq!(review()["status"], "pending");
    decide("approve", &review());
    assert!(rpc(
        Some(5),
        "tools/call",
        json!({"name":"read_first","arguments":{}})
    )["result"]
        .is_object());
    assert_eq!(
        std::fs::read_to_string(root.path().join("fixture-calls")).unwrap(),
        "call\n"
    );
    drop(stdin);
    assert!(gateway.wait().unwrap().success());
}

fn serve_fixture() {
    let mut output = std::io::stdout().lock();
    for line in BufReader::new(std::io::stdin().lock()).lines() {
        let request: Value = serde_json::from_str(&line.unwrap()).unwrap();
        let tool = |name| {
            let mut tool = json!({"name": name, "inputSchema": {"type": "object"},
                "description":std::fs::read_to_string("fixture-description").unwrap_or_default()});
            if name == "read_first" && std::path::Path::new("privacy-fixture").exists() {
                tool["outputSchema"] =
                    json!({"type":"object","properties":{"password":{"type":"string"}}});
            }
            tool
        };
        let result = match request["method"].as_str().unwrap() {
            "initialize" => json!({"protocolVersion": "2025-11-25",
                                   "capabilities": {"tools": {}}}),
            "notifications/initialized" => continue,
            "tools/list" if request["params"]["cursor"].is_null() => {
                json!({"tools": [tool("read_first")], "nextCursor": "second"})
            }
            "tools/list" => {
                assert_eq!(request["params"]["cursor"], "second");
                json!({"tools": [tool("read_second")]})
            }
            "tools/call" => {
                let privacy = std::path::Path::new("privacy-fixture").exists();
                if privacy || std::path::Path::new("fixture-description").exists() {
                    writeln!(
                        OpenOptions::new()
                            .create(true)
                            .append(true)
                            .open("fixture-calls")
                            .unwrap(),
                        "call"
                    )
                    .unwrap();
                }
                let mut result = json!({"content":[{"type":"text","text":"fixture note"}]});
                if privacy && request["params"]["name"] == "read_first" {
                    result["structuredContent"] = json!({"password":"fixture-only-value"});
                }
                result
            }
            _ => panic!("Unexpected tool operation"),
        };
        writeln!(
            output,
            "{}",
            json!({"jsonrpc": "2.0", "id": request["id"], "result": result})
        )
        .unwrap();
        output.flush().unwrap();
    }
}

struct TestDirectory(PathBuf);

impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn collects_and_persists_a_paginated_catalog() {
    let root = TestDirectory(std::env::temp_dir().join(format!(
        "driftguard-stdio-{}-{}",
        std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
    )));
    std::fs::create_dir(&root.0).unwrap();
    let db = root.0.join("review.sqlite");
    let profile = root.0.join("server.json");
    std::fs::write(
        &profile,
        json!({
            "server_id": "notes",
            "argv": [std::env::current_exe().unwrap(), "--fixture"],
            "cwd": root.0,
        })
        .to_string(),
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
        .arg("--db")
        .arg(&db)
        .arg("scan-stdio")
        .arg(&profile)
        .output()
        .unwrap();
    let response: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(output.status.success(), "{response}");
    let mut child = Command::new(env!("CARGO_BIN_EXE_driftguard-rust"))
        .arg("--db")
        .arg(&db)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(br#"{"action":"list_tools","server_id":"stdio:notes"}"#)
        .unwrap();
    let output = child.wait_with_output().unwrap();
    let response: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(output.status.success(), "{response}");
    assert_eq!(response["data"][0]["tool_name"], "read_first");
    assert_eq!(response["data"][1]["tool_name"], "read_second");
}

fn gateway_requires_exact_definition_approval() {
    let root = TestDirectory(std::env::temp_dir().join(format!(
        "driftguard-gateway-{}-{}", std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
    )));
    std::fs::create_dir(&root.0).unwrap();
    std::fs::write(root.0.join("fixture-description"), "Read the fixture.").unwrap();
    let db = root.0.join("review.sqlite");
    let profile = root.0.join("server.json");
    std::fs::write(
        &profile,
        json!({"server_id":"notes",
        "argv":[std::env::current_exe().unwrap(),"--fixture"],"cwd":root.0})
        .to_string(),
    )
    .unwrap();
    let binary = env!("CARGO_BIN_EXE_driftguard-rust");
    let bridge = |request: Value| {
        let mut child = Command::new(binary)
            .arg("--db")
            .arg(&db)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        write!(child.stdin.take().unwrap(), "{request}").unwrap();
        serde_json::from_slice::<Value>(&child.wait_with_output().unwrap().stdout).unwrap()
    };
    let mut stale_decision = None;
    for reconnect in [false, true] {
        let mut child = Command::new(binary)
            .arg("--db")
            .arg(&db)
            .arg("serve")
            .arg(&profile)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let mut stdin = child.stdin.take().unwrap();
        let mut stdout = BufReader::new(child.stdout.take().unwrap());
        let mut exchange = |request: Value| {
            writeln!(stdin, "{request}").unwrap();
            stdin.flush().unwrap();
            if request["id"].is_null() {
                return Value::Null;
            }
            loop {
                let mut line = String::new();
                assert_ne!(stdout.read_line(&mut line).unwrap(), 0, "gateway ended");
                let response: Value = serde_json::from_str(&line).unwrap();
                if response["id"] == request["id"] {
                    return response;
                }
            }
        };
        assert!(
            exchange(json!({"jsonrpc":"2.0","id":1,"method":"initialize",
            "params":{"protocolVersion":"2025-11-25"}}))["result"]
                .is_object()
        );
        exchange(json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
        assert_eq!(
            exchange(json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}))["result"]["tools"],
            json!([])
        );
        assert!(
            exchange(json!({"jsonrpc":"2.0","id":3,"method":"tools/call",
            "params":{"name":"read_first","arguments":{}}}))["error"]
                .is_object()
        );
        if !reconnect {
            let mut versions = Command::new(binary)
                .arg("--db")
                .arg(&db)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            versions
                .stdin
                .take()
                .unwrap()
                .write_all(br#"{"action":"list_tools"}"#)
                .unwrap();
            let records: Value =
                serde_json::from_slice(&versions.wait_with_output().unwrap().stdout).unwrap();
            let record = &records["data"][0];
            let decision = json!({"action":"approve",
                "server_id":record["server_id"],"tool_name":"read_first",
                "expected_sha256":record["sha256"],"expected_revision":record["revision"]});
            stale_decision = Some(decision.clone());
            let mut approval = Command::new(binary)
                .arg("--db")
                .arg(&db)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            write!(approval.stdin.take().unwrap(), "{}", decision).unwrap();
            assert!(approval.wait_with_output().unwrap().status.success());
            assert_eq!(
                exchange(json!({"jsonrpc":"2.0","id":4,"method":"tools/call",
                "params":{"name":"read_first","arguments":{}}}))["result"]["content"][0]["text"],
                "fixture note"
            );
            let source = record["server_id"].clone();
            assert_eq!(
                bridge(json!({"action":"block_tool","server_id":source,"tool_name":"read_first"}))
                    ["data"]["blocked"],
                true
            );
            assert_eq!(
                exchange(json!({"jsonrpc":"2.0","id":5,"method":"tools/list"}))["result"]["tools"],
                json!([])
            );
            assert!(
                exchange(json!({"jsonrpc":"2.0","id":6,"method":"tools/call",
                "params":{"name":"read_first","arguments":{}}}))["error"]
                    .is_object()
            );
            std::fs::write(
                root.0.join("fixture-description"),
                "Read the updated fixture.",
            )
            .unwrap();
            assert!(
                exchange(json!({"jsonrpc":"2.0","id":7,"method":"tools/call",
                "params":{"name":"read_first","arguments":{}}}))["error"]
                    .is_object()
            );
        } else {
            let source = "gateway:direct:notes";
            let blocked =
                bridge(json!({"action":"review","server_id":source,"tool_name":"read_first"}));
            assert_eq!(blocked["data"]["blocked"], true);
            assert_eq!(blocked["data"]["description"], "Read the updated fixture.");
            assert_eq!(
                bridge(
                    json!({"action":"approve","server_id":source,"tool_name":"read_first",
                "expected_sha256":blocked["data"]["sha256"],"expected_revision":blocked["data"]["revision"]})
                )["ok"],
                false
            );
            assert_eq!(
                bridge(
                    json!({"action":"unblock_tool","server_id":source,"tool_name":"read_first"})
                )["data"]["blocked"],
                false
            );
            assert_eq!(
                exchange(json!({"jsonrpc":"2.0","id":4,"method":"tools/list"}))["result"]["tools"],
                json!([])
            );
            let mut approval = Command::new(binary)
                .arg("--db")
                .arg(&db)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .spawn()
                .unwrap();
            write!(
                approval.stdin.take().unwrap(),
                "{}",
                stale_decision.as_ref().unwrap()
            )
            .unwrap();
            assert!(!approval.wait_with_output().unwrap().status.success());
        }
        drop(stdin);
        assert!(child.wait().unwrap().success());
    }
    assert_eq!(
        std::fs::read_to_string(root.0.join("fixture-calls")).unwrap(),
        "call\n"
    );
}
