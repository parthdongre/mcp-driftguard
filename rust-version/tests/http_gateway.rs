use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};

const ENGINE: &str = env!("CARGO_BIN_EXE_driftguard-rust");
const LEGACY: &str = "2025-11-25";
const MODERN: &str = "2026-07-28";

#[test]
fn http_gateway_applies_exact_approval_and_modern_routing() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    listener.set_nonblocking(true).unwrap();
    let calls = Arc::new(AtomicUsize::new(0));
    let revision = Arc::new(AtomicUsize::new(1));
    let fixture = fixture(listener, Arc::clone(&calls), Arc::clone(&revision));
    let directory = tempfile::tempdir().unwrap();
    let db = directory.path().join("review.sqlite");
    let profile = directory.path().join("remote.json");
    std::fs::write(
        &profile,
        json!({
            "server_id":"http-fixture","transport":"http","url":format!("http://{address}/mcp"),
            "allow_insecure_loopback":true,"protocol_version":MODERN,"timeout_seconds":5
        })
        .to_string(),
    )
    .unwrap();

    let mut gateway = GatewayChild(
        Command::new(ENGINE)
            .arg("--db")
            .arg(&db)
            .arg("serve")
            .arg(&profile)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap(),
    );
    let mut replies = BufReader::new(gateway.0.stdout.take().unwrap());
    let input = gateway.0.stdin.as_mut().unwrap();
    assert_eq!(
        rpc(
            input,
            &mut replies,
            1,
            "initialize",
            json!({"protocolVersion":LEGACY})
        )["result"]["protocolVersion"],
        LEGACY
    );
    writeln!(
        input,
        "{}",
        json!({"jsonrpc":"2.0","method":"notifications/initialized"})
    )
    .unwrap();
    assert_eq!(
        rpc(input, &mut replies, 2, "tools/list", json!({}))["result"]["tools"],
        json!([])
    );

    let target = json!({"name":"read_record","arguments":{"region":"東京"}});
    assert!(rpc(input, &mut replies, 3, "tools/call", target.clone())
        .get("error")
        .is_some());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let selector = json!({"action":"review","server_id":"gateway:direct:http-fixture","tool_name":"read_record"});
    let review = bridge(&db, &selector);
    assert_eq!(review["status"], "pending");
    bridge(
        &db,
        &json!({"action":"approve","server_id":selector["server_id"],
        "tool_name":selector["tool_name"],"expected_sha256":review["sha256"],
        "expected_revision":review["revision"]}),
    );
    let listed = rpc(input, &mut replies, 4, "tools/list", json!({}));
    assert_eq!(listed["result"]["tools"][0]["name"], "read_record");
    let response = rpc(input, &mut replies, 5, "tools/call", target.clone());
    assert_eq!(response["result"]["content"][0]["text"], "read sample");
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    revision.store(2, Ordering::SeqCst);
    assert!(rpc(input, &mut replies, 6, "tools/call", target)
        .get("error")
        .is_some());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let review = bridge(&db, &selector);
    assert_eq!(review["status"], "pending");
    assert_eq!(review["description"], "Read a selected record.");
    assert_eq!(
        bridge(&db, &json!({"action":"definition_alerts"}))["unread"],
        1
    );
    drop(gateway.0.stdin.take());
    assert!(gateway.0.wait().unwrap().success());
    fixture.join().unwrap();
}

struct GatewayChild(Child);

impl Drop for GatewayChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn rpc(
    input: &mut impl Write,
    output: &mut impl BufRead,
    id: u64,
    method: &str,
    params: Value,
) -> Value {
    writeln!(
        input,
        "{}",
        json!({"jsonrpc":"2.0","id":id,"method":method,"params":params})
    )
    .unwrap();
    loop {
        let mut line = String::new();
        assert!(output.read_line(&mut line).unwrap() > 0);
        let message: Value = serde_json::from_str(&line).unwrap();
        if message["id"] == id {
            return message;
        }
        assert_eq!(message["method"], "notifications/tools/list_changed");
    }
}

fn bridge(db: &Path, request: &Value) -> Value {
    let mut child = Command::new(ENGINE)
        .arg("--db")
        .arg(db)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(request.to_string().as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    let response: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert!(output.status.success(), "{response}");
    response["data"].clone()
}

fn fixture(
    listener: TcpListener,
    calls: Arc<AtomicUsize>,
    revision: Arc<AtomicUsize>,
) -> thread::JoinHandle<()> {
    thread::spawn(move || {
        let deadline = std::time::Instant::now() + Duration::from_secs(12);
        let mut checked_revision_two = false;
        while !checked_revision_two {
            let mut socket = match listener.accept() {
                Ok((socket, _)) => {
                    // Accepted sockets inherit the listener's nonblocking
                    // mode on macOS. Read the request with a blocking timeout.
                    socket.set_nonblocking(false).unwrap();
                    socket
                }
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                    assert!(std::time::Instant::now() < deadline);
                    thread::sleep(Duration::from_millis(2));
                    continue;
                }
                Err(error) => panic!("{error}"),
            };
            let (message, headers) = read_post(&mut socket);
            let method = message["method"].as_str().unwrap();
            assert_eq!(headers["mcp-protocol-version"], MODERN);
            assert_eq!(headers["mcp-method"], method);
            let mut result = match method {
                "server/discover" => {
                    json!({"supportedVersions":[MODERN],"capabilities":{"tools":{}}})
                }
                "tools/list" => {
                    let description = if revision.load(Ordering::SeqCst) == 1 {
                        "Read a record."
                    } else {
                        checked_revision_two = true;
                        "Read a selected record."
                    };
                    json!({"tools":[{"name":"read_record","description":description,
                        "inputSchema":{"type":"object","properties":{"region":{"type":"string",
                            "x-mcp-header":"Region"}},"required":["region"]}}]})
                }
                "tools/call" => {
                    assert_eq!(headers["mcp-name"], "read_record");
                    assert_eq!(headers["mcp-param-region"], "=?base64?5p2x5Lqs?=");
                    assert_eq!(message["params"]["arguments"]["region"], "東京");
                    calls.fetch_add(1, Ordering::SeqCst);
                    json!({"content":[{"type":"text","text":"read sample"}],"isError":false})
                }
                _ => panic!("Unexpected method {method}"),
            };
            result["resultType"] = json!("complete");
            let body = json!({"jsonrpc":"2.0","id":message["id"],"result":result}).to_string();
            write!(socket, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}", body.len()).unwrap();
        }
    })
}

fn read_post(socket: &mut TcpStream) -> (Value, BTreeMap<String, String>) {
    socket
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let mut reader = BufReader::new(socket);
    let mut line = String::new();
    reader.read_line(&mut line).unwrap();
    assert!(line.starts_with("POST /mcp "));
    let mut headers = BTreeMap::new();
    loop {
        line.clear();
        assert!(reader.read_line(&mut line).unwrap() > 0);
        if line == "\r\n" {
            break;
        }
        let (key, value) = line.split_once(':').unwrap();
        headers.insert(key.to_ascii_lowercase(), value.trim().to_owned());
    }
    let mut bytes = vec![0; headers["content-length"].parse::<usize>().unwrap()];
    reader.read_exact(&mut bytes).unwrap();
    (serde_json::from_slice(&bytes).unwrap(), headers)
}
