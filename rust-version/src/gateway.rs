use std::collections::BTreeSet;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::sync::{mpsc, Notify};
use tokio::time::{self, Instant, MissedTickBehavior};

use crate::discovery::{Peer, Profile, LEGACY, MODERN};
use crate::http::HttpPeer;
use crate::review::{ReviewError, ReviewStore};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const MAX_LINE: u64 = 1_048_576;
const MAX_CATALOG: usize = 2_097_152;
const PROTOCOL: &str = "io.modelcontextprotocol/protocolVersion";
const CAPABILITIES: &str = "io.modelcontextprotocol/clientCapabilities";
const SERVER_INFO: &str = "io.modelcontextprotocol/serverInfo";
const CHANGED: &str = "notifications/tools/list_changed";

#[cfg(test)]
#[test]
fn recent_tool_use_shortens_the_catalog_check_interval() {
    use crate::review::MonitoringSettings;
    let defaults = MonitoringSettings::default();
    assert_eq!(defaults.catalog_interval(None), Duration::from_secs(300));
    assert_eq!(
        defaults.catalog_interval(Some(Duration::from_secs(119))),
        Duration::from_secs(15)
    );
    assert_eq!(
        defaults.catalog_interval(Some(Duration::from_secs(120))),
        Duration::from_secs(300)
    );
    let custom = MonitoringSettings {
        idle_seconds: 60,
        active_seconds: 5,
        active_window_seconds: 30,
        ..defaults
    };
    assert_eq!(
        custom.catalog_interval(Some(Duration::from_secs(29))),
        Duration::from_secs(5)
    );
    assert_eq!(
        custom.catalog_interval(Some(Duration::from_secs(30))),
        Duration::from_secs(60)
    );
}

fn client_info() -> Value {
    json!({"name":"driftguard-rust","version":env!("CARGO_PKG_VERSION")})
}

enum Transport {
    Stdio(Box<Peer>),
    Http(Box<HttpPeer>),
    CodexHosted(Box<crate::codex_hosted::Hosted>),
}

pub struct Upstream {
    peer: Transport,
    version: String,
}

impl Upstream {
    pub fn open(config: &Value) -> Result<Self> {
        Self::open_with_codex_home(config, None)
    }

    pub(crate) fn open_with_codex_home(
        config: &Value,
        codex_home: Option<&std::path::Path>,
    ) -> Result<Self> {
        let peer = if config["transport"] == "codex_hosted" {
            let home = config["codex_home"]
                .as_str()
                .map(std::path::Path::new)
                .ok_or(ReviewError("The hosted gateway profile has no Codex home."))?;
            Transport::CodexHosted(Box::new(crate::codex_hosted::Hosted::open(home)?))
        } else if config["transport"] == "http" {
            Transport::Http(Box::new(HttpPeer::open(config)?))
        } else {
            Transport::Stdio(Box::new(Peer::open(Profile::load(config, codex_home)?)?))
        };
        Ok(Self::from_transport(peer))
    }

    pub fn open_catalog_stdio(profile: Profile) -> Result<Self> {
        Ok(Self::from_transport(Transport::Stdio(Box::new(
            Peer::open(profile)?,
        ))))
    }

    fn from_transport(peer: Transport) -> Self {
        let version = match &peer {
            Transport::Stdio(peer) => peer.version(),
            Transport::Http(peer) => peer.version(),
            Transport::CodexHosted(_) => LEGACY[0],
        }
        .to_owned();
        Self { peer, version }
    }

    pub fn source(&self) -> &str {
        match &self.peer {
            Transport::Stdio(peer) => peer.source(),
            Transport::Http(peer) => peer.source(),
            Transport::CodexHosted(_) => crate::codex_hosted::SERVER,
        }
    }

    pub fn transport(&self) -> &'static str {
        match self.peer {
            Transport::Stdio(_) => "stdio",
            Transport::Http(_) => "http",
            Transport::CodexHosted(_) => "codex_hosted",
        }
    }

    pub fn identity(&self) -> &str {
        match &self.peer {
            Transport::Stdio(peer) => peer.identity(),
            Transport::Http(peer) => peer.identity(),
            Transport::CodexHosted(peer) => peer.identity(),
        }
    }

    pub fn verify(&self) -> Result<()> {
        match &self.peer {
            Transport::Stdio(peer) => peer.verify(),
            Transport::Http(peer) => peer.verify(),
            Transport::CodexHosted(peer) => peer.verify(),
        }
    }

    pub fn timeout(&self) -> Duration {
        match &self.peer {
            Transport::Stdio(peer) => peer.timeout(),
            Transport::Http(peer) => peer.timeout(),
            Transport::CodexHosted(peer) => peer.timeout(),
        }
    }

    fn change_signal(&self) -> Arc<Notify> {
        match &self.peer {
            Transport::Stdio(peer) => peer.changed(),
            Transport::Http(_) => Arc::new(Notify::new()),
            Transport::CodexHosted(peer) => peer.changed(),
        }
    }

    fn take_http_change(&mut self) -> bool {
        match &mut self.peer {
            Transport::Stdio(_) => false,
            Transport::Http(peer) => peer.take_changed(),
            Transport::CodexHosted(_) => false,
        }
    }

    fn contains_secret(&self, value: &Value) -> bool {
        match &self.peer {
            Transport::Stdio(peer) => peer.contains_secret(value),
            Transport::Http(peer) => peer.contains_secret(value),
            Transport::CodexHosted(peer) => peer.contains_secret(value),
        }
    }

    pub async fn initialize(&mut self) -> Result<()> {
        if let Transport::CodexHosted(peer) = &mut self.peer {
            return peer.initialize().await;
        }
        let result = if self.version == MODERN {
            let result = self.request("server/discover", json!({})).await?;
            if !result["supportedVersions"]
                .as_array()
                .is_some_and(|versions| versions.iter().any(|version| version == MODERN))
            {
                return Err(
                    ReviewError("The server did not support the configured MCP protocol.").into(),
                );
            }
            result
        } else {
            let result = self
                .request(
                    "initialize",
                    json!({"protocolVersion":self.version,
                "capabilities":{}, "clientInfo":client_info()}),
                )
                .await?;
            let version = result["protocolVersion"]
                .as_str()
                .filter(|version| LEGACY.contains(version))
                .ok_or(ReviewError(
                    "The server did not negotiate a supported MCP protocol.",
                ))?;
            self.version = version.to_owned();
            match &mut self.peer {
                Transport::Stdio(peer) => peer.notify("notifications/initialized").await?,
                Transport::Http(peer) => {
                    peer.set_version(version);
                    peer.notify("notifications/initialized").await?;
                }
                Transport::CodexHosted(_) => {
                    unreachable!("hosted initialization is handled separately")
                }
            }
            result
        };
        if !result["capabilities"]["tools"].is_object() {
            return Err(ReviewError("The upstream server does not advertise MCP tools.").into());
        }
        Ok(())
    }

    async fn request(&mut self, method: &str, mut params: Value) -> Result<Value> {
        if self.version == MODERN {
            params["_meta"] = json!({(PROTOCOL):MODERN, (CAPABILITIES):{},
                "io.modelcontextprotocol/clientInfo":client_info()});
        }
        let result = match &mut self.peer {
            Transport::Stdio(peer) => peer.request(method, params).await?,
            Transport::Http(peer) => peer.request(method, params).await?,
            Transport::CodexHosted(peer) if method == "tools/call" => {
                peer.call(
                    params["name"]
                        .as_str()
                        .ok_or(ReviewError("Expected a hosted tool name."))?,
                    &params["arguments"],
                )
                .await?
            }
            Transport::CodexHosted(_) => {
                return Err(ReviewError("Unsupported hosted gateway operation.").into())
            }
        };
        if self.version == MODERN && result["resultType"] != "complete" {
            return Err(ReviewError("Only complete MCP responses are supported.").into());
        }
        if result.get("_meta").is_some_and(|meta| !meta.is_object()) {
            return Err(ReviewError("Invalid MCP response metadata.").into());
        }
        Ok(result)
    }

    pub async fn catalog(&mut self) -> Result<Vec<Value>> {
        self.verify()?;
        let timeout = self.timeout();
        if let Transport::CodexHosted(peer) = &mut self.peer {
            return time::timeout(timeout, peer.catalog())
                .await
                .map_err(|_| ReviewError("Codex hosted catalog refresh timed out."))?;
        }
        time::timeout(timeout, self.list_pages())
            .await
            .map_err(|_| ReviewError("MCP catalog refresh timed out."))?
    }

    async fn list_pages(&mut self) -> Result<Vec<Value>> {
        let (max_bytes, max_tools, max_pages) = match &self.peer {
            Transport::Stdio(peer) => peer.catalog_limits(),
            Transport::Http(peer) => peer.catalog_limits(),
            Transport::CodexHosted(_) => unreachable!("hosted catalog has a separate path"),
        };
        let mut tools = Vec::new();
        let mut cursors = BTreeSet::new();
        let mut params = json!({});
        let mut bytes = 0;
        for _ in 0..max_pages.min(20) {
            let mut page = self.request("tools/list", params).await?;
            bytes += serde_json::to_vec(&page)?.len();
            let batch = page["tools"]
                .as_array_mut()
                .ok_or(ReviewError("Expected a tools array from the MCP server."))?;
            if bytes > max_bytes.min(MAX_CATALOG) || tools.len() + batch.len() > max_tools.min(500)
            {
                return Err(ReviewError("The MCP catalog exceeds the collection limit.").into());
            }
            if batch.iter().any(|tool| self.contains_secret(tool)) {
                return Err(
                    ReviewError("An MCP definition contains a configured credential.").into(),
                );
            }
            tools.append(batch);
            match page.get("nextCursor") {
                None | Some(Value::Null) => {
                    if let Transport::Http(peer) = &mut self.peer {
                        peer.set_catalog(&tools)?;
                    }
                    return Ok(tools);
                }
                Some(Value::String(cursor))
                    if !cursor.is_empty() && cursors.insert(cursor.clone()) =>
                {
                    params = json!({"cursor":cursor});
                }
                _ => return Err(ReviewError("Invalid or repeated MCP pagination cursor.").into()),
            }
        }
        Err(ReviewError("The MCP catalog exceeds the page limit.").into())
    }
}

struct Gateway {
    upstream: Upstream,
    store: ReviewStore,
    source: String,
    session: String,
    last_refresh: Instant,
    last_use: Option<Instant>,
    db: PathBuf,
    profile: PathBuf,
    client: Option<String>,
    config: Value,
    model: Option<crate::decision_model::DecisionModel>,
    model_artifact: Option<String>,
    private_values: BTreeSet<[u8; 32]>,
    codex_route: Option<String>,
    registered: bool,
}

fn private_fields(value: &Value, sensitive: bool, visit: &mut impl FnMut(&str)) {
    match value {
        Value::String(text) if sensitive && (12..=8192).contains(&text.len()) => visit(text),
        Value::Array(values) => values
            .iter()
            .for_each(|value| private_fields(value, sensitive, visit)),
        Value::Object(fields) => fields.iter().for_each(|(key, value)| {
            let key = key.to_ascii_lowercase();
            private_fields(
                value,
                sensitive
                    || matches!(
                        key.as_str(),
                        "password"
                            | "api_key"
                            | "apikey"
                            | "access_token"
                            | "refresh_token"
                            | "private_key"
                            | "client_secret"
                            | "authorization"
                    ),
                visit,
            );
        }),
        _ => {}
    }
}

fn fingerprint(session: &str, text: &str) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(session.as_bytes());
    hash.update(text.as_bytes());
    hash.finalize().into()
}

impl Gateway {
    fn check_binding(&self) -> Result<Option<std::fs::File>> {
        let guard = if self.registered {
            None
        } else if let Some(name) = &self.codex_route {
            let (lock, config) = crate::harness::lock_codex_route(&self.db, name)?;
            if config != self.config {
                return Err(ReviewError("The Codex MCP route changed. Open a new session.").into());
            }
            Some(lock)
        } else {
            self.client
                .as_deref()
                .map(|client| {
                    let (lock, path) = crate::harness::lock_connection(&self.db, client)?;
                    if path != self.profile {
                        return Err(ReviewError(
                            "The managed MCP profile changed. Reconnect and review.",
                        )
                        .into());
                    }
                    Ok::<_, Box<dyn std::error::Error>>(lock)
                })
                .transpose()?
        };
        self.verify_profile()?;
        Ok(guard)
    }

    fn verify_profile(&self) -> Result<()> {
        let changed = if self.registered {
            crate::servers::profile(&self.db, self.upstream.source())? != self.config
        } else {
            self.codex_route.is_none() && Profile::parse_file(&self.profile)? != self.config
        };
        if changed {
            return Err(ReviewError("The MCP profile changed. Reconnect and review.").into());
        }
        if self.store.model_artifact()? != self.model_artifact {
            return Err(ReviewError("The decision model changed. Reconnect the gateway.").into());
        }
        Ok(())
    }

    async fn refresh(&mut self, start: bool) -> Result<Vec<Value>> {
        let result: Result<Vec<Value>> = async {
            let tools = self.upstream.catalog().await?;
            self.upstream.verify()?;
            Ok(tools)
        }
        .await;
        let tools = result.inspect_err(|_| {
            let _ = self.store.catalog_check_failed(&self.source);
        })?;
        self.store.observe_gateway(
            &self.source,
            self.upstream.identity(),
            &tools,
            &self.session,
            start,
            self.model.as_ref().zip(self.model_artifact.as_deref()),
        )?;
        self.last_refresh = Instant::now();
        Ok(tools)
    }

    fn approved(&self) -> Result<Vec<Value>> {
        Ok(self
            .store
            .gateway_tools(&self.source, &self.session)?
            .into_iter()
            .filter(callable)
            .collect())
    }

    async fn call(
        &mut self,
        name: &str,
        arguments: &Value,
        tools: &[Value],
    ) -> Result<std::result::Result<Value, &'static str>> {
        let Some(tool) = tools.iter().find(|tool| tool["name"] == name) else {
            self.store.record_preflight_denial(
                &self.source,
                &self.session,
                "(unavailable tool)",
                "tool_unavailable",
            )?;
            return Ok(Err("tool_unavailable"));
        };
        if !callable(tool) || !crate::contracts::valid(&tool["inputSchema"], arguments) {
            self.store.record_preflight_denial(
                &self.source,
                &self.session,
                name,
                "input_contract",
            )?;
            return Ok(Err("input_contract"));
        }
        if self.upstream.contains_secret(arguments)
            || crate::contracts::contains_private_key(&serde_json::to_string(arguments)?)
        {
            self.store.record_preflight_denial(
                &self.source,
                &self.session,
                name,
                "credential_in_request",
            )?;
            return Ok(Err("credential_in_request"));
        }
        let mut reused = false;
        if !self.private_values.is_empty() {
            private_fields(arguments, true, &mut |text| {
                reused |= self
                    .private_values
                    .contains(&fingerprint(&self.session, text));
            });
        }
        if reused {
            self.store.record_preflight_denial(
                &self.source,
                &self.session,
                name,
                "sensitive_value_reuse",
            )?;
            return Ok(Err("sensitive_value_reuse"));
        }
        self.upstream.verify()?;
        let permit = match self.store.authorize(
            &self.source,
            &self.session,
            name,
            tool,
            self.model_artifact.as_deref(),
        ) {
            Ok(permit) => permit,
            Err(error) => {
                if let Some(reason) = error.downcast_ref::<ReviewError>() {
                    return Ok(Err(reason.0));
                }
                return Err(error);
            }
        };
        let result = self
            .upstream
            .request("tools/call", json!({"name":name,"arguments":arguments}))
            .await
            .and_then(|result| {
                let joined = Value::String(
                    result["content"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|item| item["text"].as_str())
                        .collect(),
                );
                if self.upstream.contains_secret(&result) || self.upstream.contains_secret(&joined)
                {
                    return Err(ReviewError("The tool returned a configured credential.").into());
                }
                crate::contracts::check_result(result, tool.get("outputSchema"))
            });
        match result {
            Ok(value) => {
                let tool_error = value["isError"] == true;
                permit.finish_with_reason(
                    !tool_error,
                    tool_error.then_some("upstream_reported_error"),
                )?;
                if let Some(structured) = value.get("structuredContent").filter(|_| !tool_error) {
                    private_fields(structured, false, &mut |text| {
                        if self.private_values.len() < 1024 {
                            self.private_values.insert(fingerprint(&self.session, text));
                        }
                    });
                }
                Ok(Ok(value))
            }
            Err(_) => {
                permit.finish_with_reason(false, Some("upstream_or_output_failure"))?;
                Ok(Err("upstream_or_output_failure"))
            }
        }
    }
}

pub(crate) fn callable(tool: &Value) -> bool {
    crate::contracts::supports(&tool["inputSchema"])
        && tool.get("outputSchema").is_none_or(|output| {
            output.get("type").is_none_or(|kind| kind == "object")
                && crate::contracts::supports(output)
        })
}

#[derive(Default)]
struct Downstream {
    initialized: bool,
    ready: bool,
    seen: BTreeSet<String>,
}

impl Downstream {
    async fn handle(&mut self, gateway: &mut Gateway, message: Value) -> Result<Option<Value>> {
        let id = &message["id"];
        let Some(method) = message["method"].as_str() else {
            return Ok(Some(error(id, -32600, "Invalid MCP request.")));
        };
        if message["jsonrpc"] != "2.0"
            || message.get("error").is_some()
            || message.get("result").is_some()
        {
            return Ok(Some(error(id, -32600, "Invalid MCP request.")));
        }
        if message.get("id").is_none() {
            if method == "notifications/initialized" && self.initialized {
                self.ready = true;
            }
            return Ok(None);
        }
        if !(id.as_str().is_some_and(|id| id.len() <= 128) || id.as_i64().is_some())
            || self.seen.len() >= 100_000
            || !self.seen.insert(id.to_string())
        {
            return Ok(Some(error(
                &Value::Null,
                -32600,
                "Invalid or repeated MCP request ID.",
            )));
        }
        let empty = json!({});
        let params = message.get("params").unwrap_or(&empty);
        let Some(fields) = params.as_object() else {
            return Ok(Some(error(id, -32602, "Expected object parameters.")));
        };
        let metadata = params.get("_meta");
        if metadata.is_some_and(|value| !value.is_object()) {
            return Ok(Some(error(id, -32602, "Invalid request metadata.")));
        }
        let modern = metadata.is_some_and(|meta| meta.get(PROTOCOL).is_some());
        if modern
            && (params["_meta"][PROTOCOL] != MODERN || !params["_meta"][CAPABILITIES].is_object())
        {
            return Ok(Some(error(
                id,
                -32602,
                "Unsupported MCP version or missing client capabilities.",
            )));
        }
        if method != "initialize" && !modern && !self.ready {
            return Ok(Some(error(id, -32600, "Initialize the MCP session first.")));
        }
        let mut result = match method {
            "initialize"
                if !modern
                    && !self.initialized
                    && params["protocolVersion"]
                        .as_str()
                        .is_some_and(|version| LEGACY.contains(&version)) =>
            {
                self.initialized = true;
                json!({"protocolVersion":params["protocolVersion"],"capabilities":{"tools":{"listChanged":true}},
                    "serverInfo":client_info()})
            }
            "server/discover" if modern => {
                json!({"supportedVersions":[MODERN, LEGACY[0], LEGACY[1], LEGACY[2]],
                "capabilities":{"tools":{}},"ttlMs":0,"cacheScope":"private"})
            }
            "ping" => json!({}),
            "tools/list" if fields.keys().all(|key| key == "_meta") => {
                let _binding = gateway.check_binding()?;
                gateway.refresh(false).await?;
                let mut result = json!({"tools":gateway.approved()?});
                if modern {
                    result["ttlMs"] = json!(0);
                    result["cacheScope"] = json!("private");
                }
                result
            }
            "tools/call"
                if fields
                    .keys()
                    .all(|key| matches!(key.as_str(), "name" | "arguments" | "_meta")) =>
            {
                let Some(name) = params["name"]
                    .as_str()
                    .filter(|name| !name.is_empty() && name.len() <= 128)
                else {
                    return Ok(Some(error(id, -32602, "Expected a tool name.")));
                };
                let arguments = params.get("arguments").unwrap_or(&empty);
                if !arguments.is_object() {
                    return Ok(Some(error(
                        id,
                        -32602,
                        "Expected tool arguments as an object.",
                    )));
                }
                let _binding = gateway.check_binding()?;
                let tools = gateway.refresh(false).await?;
                gateway.last_use = Some(Instant::now());
                gateway.verify_profile()?;
                match gateway.call(name, arguments, &tools).await? {
                    Ok(result) => result,
                    Err(reason) => {
                        let mut reply = error(
                            id,
                            -32602,
                            "DriftGuard restricted the call or could not deliver its result.",
                        );
                        reply["error"]["data"] = json!({"reason":reason});
                        return Ok(Some(reply));
                    }
                }
            }
            "initialize" | "tools/list" | "tools/call" => {
                return Ok(Some(error(id, -32602, "Invalid MCP parameters.")))
            }
            _ => {
                return Ok(Some(error(
                    id,
                    -32601,
                    "Method is outside the tools-only gateway.",
                )))
            }
        };
        if modern {
            result["resultType"] = json!("complete");
            result["_meta"] = json!({(SERVER_INFO):client_info()});
        }
        Ok(Some(json!({"jsonrpc":"2.0","id":id,"result":result})))
    }
}

fn error(id: &Value, code: i64, message: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"error":{"code":code,"message":message}})
}

fn emit(message: &Value) -> Result<()> {
    let mut encoded = serde_json::to_vec(message)?;
    if encoded.len() as u64 >= MAX_LINE {
        encoded = serde_json::to_vec(&error(
            &message["id"],
            -32603,
            "MCP response exceeds the size limit.",
        ))?;
    }
    let mut stdout = io::stdout().lock();
    stdout.write_all(&encoded)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}

async fn serve_connected(gateway: &mut Gateway) -> Result<()> {
    let (send, mut messages) = mpsc::channel(8);
    // A dedicated stdin thread lets the async runtime exit on upstream failure
    // even when the coding client is waiting for more output.
    std::thread::spawn(move || {
        let mut stdin = io::stdin().lock();
        loop {
            use std::io::Read;
            let mut line = Vec::new();
            if !matches!((&mut stdin).take(MAX_LINE + 1).read_until(b'\n', &mut line),
                Ok(bytes) if bytes > 0 && bytes as u64 <= MAX_LINE)
                || line.last() != Some(&b'\n')
            {
                break;
            }
            if send.blocking_send(line).is_err() {
                break;
            }
        }
    });
    let signal = gateway.upstream.change_signal();
    let mut tick = time::interval(Duration::from_secs(2));
    tick.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut downstream = Downstream::default();
    let mut published = gateway.approved()?;
    let mut pending_refresh = false;
    loop {
        tokio::select! {
            line = messages.recv() => {
                let Some(line) = line else { return Ok(()); };
                match crate::input::parse(&line) {
                    Ok(message) => {
                        let id = message["id"].clone();
                        match downstream.handle(gateway, message).await {
                            Ok(Some(reply)) => emit(&reply)?,
                            Ok(None) => {},
                            Err(error_value) => {
                                if !id.is_null() {
                                    emit(&error(&id,-32603,"Gateway verification or upstream transport failed."))?;
                                }
                                return Err(error_value);
                            }
                        }
                    }
                    Err(_) => emit(&error(&Value::Null,-32700,"Invalid MCP JSON."))?,
                }
            }
            _ = signal.notified() => { pending_refresh = true; }
            _ = tick.tick() => {
                let _binding = gateway.check_binding()?;
                gateway.store.heartbeat(&gateway.source, &gateway.session)?;
                pending_refresh |= gateway.upstream.take_http_change();
                let elapsed = gateway.last_refresh.elapsed();
                let settings = gateway.store.monitoring_settings()?;
                if elapsed >= settings.catalog_interval(gateway.last_use.map(|at| at.elapsed()))
                    || (pending_refresh && elapsed >= Duration::from_secs(1)) {
                    pending_refresh = false;
                    gateway.refresh(false).await?;
                }
                let approved = gateway.approved()?;
                if approved != published {
                    published = approved;
                    if downstream.ready {
                        emit(&json!({"jsonrpc":"2.0","method":CHANGED}))?;
                    }
                }
            }
        }
    }
}

pub async fn serve(db: PathBuf, profile: PathBuf, client: Option<String>) -> Result<()> {
    let profile = profile.canonicalize()?;
    let _initial_binding = client
        .as_deref()
        .map(|client| {
            let (guard, installed_profile) = crate::harness::lock_connection(&db, client)?;
            if installed_profile != profile {
                return Err(
                    ReviewError("The managed MCP profile changed. Reconnect and review.").into(),
                );
            }
            Ok::<_, Box<dyn std::error::Error>>(guard)
        })
        .transpose()?;
    let config = Profile::parse_file(&profile)?;
    run_gateway(db, profile, client, config, None, _initial_binding, false).await
}

pub async fn serve_codex_route(db: PathBuf, name: String) -> Result<()> {
    let (lock, config) = crate::harness::lock_codex_route(&db, &name)?;
    run_gateway(
        db,
        PathBuf::new(),
        Some("codex".into()),
        config,
        Some(name),
        Some(lock),
        false,
    )
    .await
}

pub async fn serve_registered(db: PathBuf, name: String, harness: Option<String>) -> Result<()> {
    let config = crate::servers::profile(&db, &name)?;
    let result = run_gateway(
        db.clone(),
        PathBuf::new(),
        harness.clone(),
        config.clone(),
        None,
        None,
        true,
    )
    .await;
    if let Err(error) = &result {
        crate::servers::failure(&db, &config, error.as_ref())?;
        ReviewStore::open(&db)?.catalog_check_failed(&format!(
            "gateway:{}:{name}",
            harness.as_deref().unwrap_or("direct")
        ))?;
    }
    result
}

async fn run_gateway(
    db: PathBuf,
    profile: PathBuf,
    client: Option<String>,
    config: Value,
    codex_route: Option<String>,
    initial_binding: Option<std::fs::File>,
    registered: bool,
) -> Result<()> {
    let store = ReviewStore::open(&db)?;
    store.expire_sentinel_history()?;
    let model_artifact = store.model_artifact()?;
    let model = model_artifact
        .as_ref()
        .map(|artifact| crate::decision_model::DecisionModel::parse(artifact.as_bytes()))
        .transpose()?;
    let codex_home = if registered || client.as_deref() == Some("codex") {
        Some(crate::harness::codex_home()?)
    } else {
        None
    };
    let mut upstream = Upstream::open_with_codex_home(&config, codex_home.as_deref())?;
    upstream.initialize().await?;
    let source = format!(
        "gateway:{}:{}",
        client.as_deref().unwrap_or("direct"),
        upstream.source()
    );
    let mut gateway = Gateway {
        upstream,
        store,
        source,
        session: uuid::Uuid::new_v4().to_string(),
        last_refresh: Instant::now(),
        last_use: None,
        db,
        profile,
        client,
        config,
        model,
        model_artifact,
        private_values: BTreeSet::new(),
        codex_route,
        registered,
    };
    gateway.refresh(true).await?;
    if registered {
        crate::servers::state(&gateway.db, &gateway.config, "catalog_ready")?;
    }
    drop(initial_binding);
    let result = serve_connected(&mut gateway).await;
    let cleanup = gateway
        .store
        .disconnect_gateway(&gateway.source, &gateway.session);
    result.and(cleanup)
}
