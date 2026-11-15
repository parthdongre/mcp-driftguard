use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::io::{BufRead, BufReader, Read};
use std::net::{IpAddr, ToSocketAddrs};
use std::time::{Duration, Instant};

use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tokio::sync::oneshot;
use url::Url;

use crate::discovery::identity_kdf;
use crate::review::ReviewError;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const MODERN: &str = "2026-07-28";
const LEGACY: &str = "2025-11-25";
const MAX_LINE: usize = 1024 * 1024;
const MAX_SAFE_INTEGER: i64 = (1 << 53) - 1;
const FAILED: &str = "HTTP exchange failed. Reconnect and review the server.";
/// A complete JSON-RPC error for this request. The session is still usable.
const REJECTED: &str = "The MCP server rejected the request.";

#[derive(Clone)]
struct Connection {
    endpoint: Url,
    timeout: Duration,
    limit: usize,
    token: Option<String>,
}

pub struct HttpPeer {
    source: String,
    version: String,
    identity: String,
    credential: Credential,
    catalog_limits: (usize, usize, usize),
    connection: Connection,
    session: Option<String>,
    sequence: u64,
    changed: bool,
    closed: bool,
    routing: BTreeMap<String, Vec<Route>>,
}

enum Credential {
    None,
    Environment(String),
    Vault { source: String, endpoint: String },
}

impl Credential {
    fn read(&self) -> Result<Option<String>> {
        let value = match self {
            Self::None => return Ok(None),
            Self::Environment(name) => std::env::var(name).ok(),
            Self::Vault { source, endpoint } => crate::credentials::read(source, endpoint)?,
        }
        .ok_or(ReviewError(
            "The configured bearer credential is unavailable.",
        ))?;
        if !(8..=8192).contains(&value.len())
            || !value.bytes().all(|byte| (33..=126).contains(&byte))
        {
            return Err(ReviewError("The configured bearer credential is invalid.").into());
        }
        Ok(Some(value))
    }
}

impl HttpPeer {
    pub fn open(config: &Value) -> Result<Self> {
        let fields = config
            .as_object()
            .ok_or(ReviewError("Expected an HTTP profile object."))?;
        if fields.keys().any(|key| {
            !matches!(
                key.as_str(),
                "server_id"
                    | "transport"
                    | "url"
                    | "protocol_version"
                    | "auth_token_env"
                    | "use_os_vault"
                    | "allow_insecure_loopback"
                    | "timeout_seconds"
                    | "max_message_bytes"
                    | "max_catalog_bytes"
                    | "max_tools"
                    | "max_pages"
            )
        }) || config["transport"] != "http"
        {
            return Err(ReviewError("Invalid HTTP profile fields.").into());
        }
        let source = config["server_id"]
            .as_str()
            .filter(|id| {
                (1..=128).contains(&id.len())
                    && id
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
            })
            .ok_or(ReviewError("Expected a valid server_id."))?;
        let original_endpoint = config["url"]
            .as_str()
            .ok_or(ReviewError("Expected an HTTP endpoint."))?;
        let endpoint = endpoint(
            original_endpoint,
            bool_field(config, "allow_insecure_loopback")?,
        )?;
        let version = match config.get("protocol_version") {
            None => LEGACY,
            Some(value) => value
                .as_str()
                .filter(|version| matches!(*version, MODERN | LEGACY | "2025-06-18" | "2025-03-26"))
                .ok_or(ReviewError("Unsupported HTTP protocol version."))?,
        };
        let use_os_vault = bool_field(config, "use_os_vault")?;
        let token_env = match config.get("auth_token_env") {
            None | Some(Value::Null) => None,
            Some(value) => Some(
                value
                    .as_str()
                    .filter(|value| valid_env_name(value))
                    .ok_or(ReviewError("Invalid bearer environment variable name."))?
                    .to_owned(),
            ),
        };
        let credential = match (use_os_vault, token_env) {
            (true, Some(_)) => {
                return Err(ReviewError("Choose one source for the bearer credential.").into())
            }
            (true, None) => Credential::Vault {
                source: source.to_owned(),
                endpoint: original_endpoint.to_owned(),
            },
            (false, Some(name)) => Credential::Environment(name),
            (false, None) => Credential::None,
        };
        let token = credential.read()?;
        let timeout = match config.get("timeout_seconds") {
            None => Duration::from_secs(15),
            Some(value) => value
                .as_f64()
                .filter(|value| (0.05..=300.0).contains(value))
                .map(Duration::from_secs_f64)
                .ok_or(ReviewError("Invalid HTTP timeout."))?,
        };
        let limit = limit_field(config, "max_message_bytes", MAX_LINE, 1024, 16 * MAX_LINE)?;
        let catalog_bytes = limit_field(
            config,
            "max_catalog_bytes",
            (8 * MAX_LINE).max(limit),
            limit,
            64 * MAX_LINE,
        )?;
        let tools = limit_field(config, "max_tools", 1000, 1, 10_000)?;
        let pages = limit_field(config, "max_pages", 100, 1, 1000)?;
        let token_kdf = token
            .as_deref()
            .map(|token| identity_kdf(source, original_endpoint.as_bytes(), token));
        let binding =
            json!({"endpoint": original_endpoint, "protocol": version, "token_kdf": token_kdf});
        let identity = format!("{:x}", Sha256::digest(serde_json::to_vec(&binding)?));
        Ok(Self {
            source: source.to_owned(),
            version: version.to_owned(),
            identity,
            credential,
            catalog_limits: (catalog_bytes, tools, pages),
            connection: Connection {
                endpoint,
                timeout,
                limit,
                token,
            },
            session: None,
            sequence: 0,
            changed: false,
            closed: false,
            routing: BTreeMap::new(),
        })
    }

    pub fn source(&self) -> &str {
        &self.source
    }
    pub fn timeout(&self) -> Duration {
        self.connection.timeout
    }
    pub fn version(&self) -> &str {
        &self.version
    }
    pub fn identity(&self) -> &str {
        &self.identity
    }
    pub fn catalog_limits(&self) -> (usize, usize, usize) {
        self.catalog_limits
    }
    pub fn set_version(&mut self, version: &str) {
        self.version = version.to_owned();
    }
    pub fn take_changed(&mut self) -> bool {
        std::mem::take(&mut self.changed)
    }

    pub fn verify(&self) -> Result<()> {
        if self.closed || self.credential.read()? != self.connection.token {
            return Err(ReviewError(
                "HTTP connection authorization changed or expired. Reconnect.",
            )
            .into());
        }
        Ok(())
    }

    pub fn contains_secret(&self, value: &Value) -> bool {
        let secrets = [self.connection.token.as_deref(), self.session.as_deref()];
        contains_secret(value, &secrets)
    }

    pub fn set_catalog(&mut self, tools: &[Value]) -> Result<()> {
        if self.version == MODERN {
            self.routing.clear();
            let mut routes = BTreeMap::new();
            for tool in tools {
                let name = tool["name"]
                    .as_str()
                    .ok_or(ReviewError("Invalid tool name."))?;
                if routes
                    .insert(name.to_owned(), routing_paths(&tool["inputSchema"])?)
                    .is_some()
                {
                    return Err(ReviewError("Duplicate HTTP tool name.").into());
                }
            }
            self.routing = routes;
        }
        Ok(())
    }

    pub async fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or(ReviewError("HTTP request limit reached."))?;
        let id = self.sequence;
        let headers = self.routing_headers(method, &params)?;
        let message = json!({"jsonrpc":"2.0", "id":id, "method":method, "params":params});
        self.exchange(method, Some(id), &message, headers)
            .await?
            .ok_or_else(|| ReviewError(FAILED).into())
    }

    pub async fn notify(&mut self, method: &str) -> Result<()> {
        let message = json!({"jsonrpc":"2.0", "method":method});
        self.exchange(method, None, &message, Vec::new()).await?;
        Ok(())
    }

    fn routing_headers(&self, method: &str, params: &Value) -> Result<Vec<(String, String)>> {
        if self.version != MODERN {
            return Ok(Vec::new());
        }
        let mut headers = vec![("Mcp-Method".to_owned(), method.to_owned())];
        if method == "tools/call" {
            let name = params["name"]
                .as_str()
                .ok_or(ReviewError("Invalid HTTP tool name."))?;
            let routes = self
                .routing
                .get(name)
                .ok_or(ReviewError("HTTP routing requires a validated tool."))?;
            headers.push(("Mcp-Name".to_owned(), encode_header(name)?));
            for route in routes {
                if let Some(value) = route.value(&params["arguments"])? {
                    headers.push((
                        format!("Mcp-Param-{}", route.header),
                        encode_header(&value)?,
                    ));
                }
            }
        }
        if headers
            .iter()
            .map(|(key, value)| key.len() + value.len())
            .sum::<usize>()
            > 16_384
        {
            return Err(ReviewError("HTTP routing headers exceed their byte limit.").into());
        }
        Ok(headers)
    }

    async fn exchange(
        &mut self,
        method: &str,
        id: Option<u64>,
        message: &Value,
        headers: Vec<(String, String)>,
    ) -> Result<Option<Value>> {
        self.verify()?;
        let body = serde_json::to_vec(message)?;
        if body.len() > self.connection.limit {
            return Err(ReviewError("HTTP request exceeds the message size limit.").into());
        }
        let wire = Exchange {
            connection: self.connection.clone(),
            version: self.version.clone(),
            session: self.session.clone(),
            method: method.to_owned(),
            id,
            body,
            headers,
            deadline: Instant::now() + self.timeout(),
        };
        // An abandoned future cannot reuse a potentially in-flight session.
        self.closed = true;
        let (sender, receiver) = oneshot::channel();
        std::thread::Builder::new()
            .name("driftguard-http".into())
            .spawn(move || {
                if !sender.is_closed() {
                    let _ = sender.send(wire.send().map_err(|error| {
                        match error.downcast::<ReviewError>() {
                            Ok(error)
                                if matches!(
                                    error.0,
                                    "The HTTPS server requires authentication."
                                        | "The HTTPS server denied access."
                                        | REJECTED
                                ) =>
                            {
                                *error
                            }
                            _ => ReviewError(FAILED),
                        }
                    }));
                }
            })?;
        let response = tokio::time::timeout(self.timeout(), receiver)
            .await
            .map_err(|_| ReviewError("HTTP request timed out. Reconnect and review the server."))?
            .map_err(|_| ReviewError(FAILED))?;
        // A JSON-RPC error is a finished exchange, so it does not end the session.
        let response = response.inspect_err(|error| self.closed = error.0 != REJECTED)?;
        self.session = response.session;
        self.changed |= response.changed;
        self.closed = false;
        Ok(response.result)
    }
}

pub fn validate_endpoint(original: &str) -> Result<()> {
    endpoint(original, false).map(|_| ())
}

pub(crate) fn endpoint(original: &str, allow_loopback: bool) -> Result<Url> {
    const INVALID: ReviewError =
        ReviewError("Use an HTTPS endpoint without credentials, query or fragment.");
    if original.len() > 4096
        || original
            .bytes()
            .any(|byte| byte <= 32 || byte == 127 || byte == b'\\')
    {
        return Err(INVALID.into());
    }
    let url = Url::parse(original).map_err(|_| INVALID)?;
    let authority = original
        .split_once("://")
        .map(|(_, suffix)| suffix.split('/').next().unwrap_or_default())
        .filter(|authority| !authority.is_empty() && !authority.contains('@'))
        .ok_or(INVALID)?;
    if !url.username().is_empty()
        || url.password().is_some()
        || url.host().is_none()
        || url.port() == Some(0)
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(INVALID.into());
    }
    if url.scheme() == "https" {
        return Ok(url);
    }
    let host = if let Some(bracketed) = authority.strip_prefix('[') {
        bracketed.split_once(']').map(|(host, _)| host)
    } else {
        authority.split(':').next()
    };
    if url.scheme() == "http"
        && allow_loopback
        && host
            .and_then(|host| host.parse::<IpAddr>().ok())
            .is_some_and(|address| address.is_loopback())
    {
        return Ok(url);
    }
    Err(ReviewError("Plain HTTP requires explicit opt-in and a literal loopback address.").into())
}

fn bool_field(config: &Value, name: &str) -> Result<bool> {
    config
        .get(name)
        .map(|value| {
            value
                .as_bool()
                .ok_or(ReviewError("Invalid HTTP profile boolean.").into())
        })
        .transpose()
        .map(|value| value.unwrap_or(false))
}

fn limit_field(
    config: &Value,
    name: &str,
    default: usize,
    min: usize,
    max: usize,
) -> Result<usize> {
    match config.get(name) {
        None => Ok(default),
        Some(value) => value
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .filter(|value| (min..=max).contains(value))
            .ok_or_else(|| ReviewError("Invalid HTTP profile limit.").into()),
    }
}

fn valid_env_name(name: &str) -> bool {
    let mut bytes = name.bytes();
    bytes
        .next()
        .is_some_and(|byte| byte.is_ascii_alphabetic() || byte == b'_')
        && bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
}

fn contains_secret(value: &Value, secrets: &[Option<&str>]) -> bool {
    let matches = |text: &str| {
        secrets
            .iter()
            .flatten()
            .any(|secret| secret.len() >= 8 && text.contains(secret))
    };
    match value {
        Value::String(text) => matches(text),
        Value::Array(items) => items.iter().any(|value| contains_secret(value, secrets)),
        Value::Object(items) => items
            .iter()
            .any(|(key, value)| matches(key) || contains_secret(value, secrets)),
        _ => false,
    }
}

struct Exchange {
    connection: Connection,
    version: String,
    session: Option<String>,
    method: String,
    id: Option<u64>,
    body: Vec<u8>,
    headers: Vec<(String, String)>,
    deadline: Instant,
}

struct Received {
    result: Option<Value>,
    session: Option<String>,
    changed: bool,
}

impl Exchange {
    fn send(mut self) -> Result<Received> {
        let connection = &self.connection;
        let remaining = self.deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(ReviewError(FAILED).into());
        }
        // Each POST uses a fresh connection. ureq can retry only a pooled socket.
        let agent = ureq::AgentBuilder::new()
            .redirects(0)
            .try_proxy_from_env(false)
            .max_idle_connections(0)
            .timeout(remaining)
            .resolver(move |host: &str| {
                let addresses = host.to_socket_addrs()?;
                if Instant::now() >= self.deadline {
                    return Err(std::io::ErrorKind::TimedOut.into());
                }
                Ok(addresses.collect())
            })
            .build();
        let mut request = agent
            .post(connection.endpoint.as_str())
            .set("Content-Type", "application/json")
            .set("Accept", "application/json, text/event-stream")
            .set("MCP-Protocol-Version", &self.version)
            .set("Accept-Encoding", "identity")
            .set("Connection", "close");
        for (key, value) in &self.headers {
            request = request.set(key, value);
        }
        if let Some(token) = &connection.token {
            request = request.set("Authorization", &format!("Bearer {token}"));
        }
        if let Some(session) = &self.session {
            request = request.set("Mcp-Session-Id", session);
        }
        let response = match request.send_bytes(&self.body) {
            Err(ureq::Error::Status(401, _)) => {
                return Err(ReviewError("The HTTPS server requires authentication.").into())
            }
            Err(ureq::Error::Status(403, _)) => {
                return Err(ReviewError("The HTTPS server denied access.").into())
            }
            result => result?,
        };
        if let Some(session) = one_header(&response, "Mcp-Session-Id")? {
            if self.version == MODERN
                || !(1..=128).contains(&session.len())
                || !session.bytes().all(|byte| (33..=126).contains(&byte))
                || self
                    .session
                    .as_deref()
                    .is_some_and(|previous| previous != session)
                || (self.session.is_none() && self.method != "initialize")
            {
                return Err(ReviewError("HTTP session changed or is invalid.").into());
            }
            self.session = Some(session.to_owned());
        }
        let mut result = Received {
            result: None,
            session: self.session,
            changed: false,
        };
        match self.id {
            None if response.status() == 202 => (),
            Some(id) if response.status() == 200 => {
                let modern = self.version == MODERN;
                result.result = Some(read_result(
                    response,
                    id,
                    modern,
                    connection.limit,
                    &mut result.changed,
                )?);
            }
            _ => return Err(ReviewError(FAILED).into()),
        }
        Ok(result)
    }
}

fn one_header<'a>(response: &'a ureq::Response, name: &str) -> Result<Option<&'a str>> {
    let count = response
        .headers_names()
        .iter()
        .filter(|header| header.eq_ignore_ascii_case(name))
        .count();
    match (count, response.header(name)) {
        (0, None) => Ok(None),
        (1, Some(value)) => Ok(Some(value)),
        _ => Err(ReviewError("Duplicate or invalid HTTP response header.").into()),
    }
}

fn read_result(
    response: ureq::Response,
    id: u64,
    modern: bool,
    limit: usize,
    changed: &mut bool,
) -> Result<Value> {
    if one_header(&response, "Content-Encoding")?
        .is_some_and(|value| !value.eq_ignore_ascii_case("identity"))
        || one_header(&response, "Content-Length")?.is_some_and(|value| {
            !value.bytes().all(|byte| byte.is_ascii_digit())
                || value.parse::<usize>().map_or(true, |size| size > limit)
        })
    {
        return Err(ReviewError(
            "HTTP response has unsupported encoding or exceeds its byte limit.",
        )
        .into());
    }
    let media = one_header(&response, "Content-Type")?
        .unwrap_or_default()
        .split(';')
        .next()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    let mut reader = response.into_reader().take(limit as u64 + 1);
    match media.as_str() {
        "application/json" => {
            let mut bytes = Vec::new();
            reader.read_to_end(&mut bytes)?;
            if bytes.len() > limit {
                return Err(ReviewError("HTTP response exceeds its byte limit.").into());
            }
            accept(&bytes, id, modern, changed)?
                .ok_or_else(|| ReviewError("Expected HTTP RPC response.").into())
        }
        "text/event-stream" => {
            let mut reader = BufReader::new(reader);
            let mut line = Vec::new();
            let mut data = Vec::new();
            let mut total = 0;
            let mut events = 0;
            loop {
                line.clear();
                let size = reader.read_until(b'\n', &mut line)?;
                total += size;
                if total > limit {
                    return Err(ReviewError("HTTP event stream exceeds its byte limit.").into());
                }
                let field = line.strip_suffix(b"\n").unwrap_or(&line);
                let field = field.strip_suffix(b"\r").unwrap_or(field);
                if field.is_empty() {
                    if !data.iter().all(u8::is_ascii_whitespace) {
                        events += 1;
                        if events > 32 {
                            return Err(ReviewError("Too many HTTP event stream messages.").into());
                        }
                        if let Some(value) = accept(&data, id, modern, changed)? {
                            return Ok(value);
                        }
                    }
                    data.clear();
                } else if let Some(field) = field.strip_prefix(b"data:") {
                    let value = field.strip_prefix(b" ").unwrap_or(field);
                    data.extend_from_slice(value);
                    data.push(b'\n');
                }
                if size == 0 {
                    return Err(
                        ReviewError("HTTP event stream ended before the RPC response.").into(),
                    );
                }
            }
        }
        _ => Err(ReviewError("Unsupported HTTP response content type.").into()),
    }
}

fn accept(bytes: &[u8], id: u64, modern: bool, changed: &mut bool) -> Result<Option<Value>> {
    let mut message = crate::input::parse(bytes)?;
    if message["jsonrpc"] != "2.0" {
        return Err(ReviewError("Invalid HTTP RPC envelope.").into());
    }
    if let Some(method) = message.get("method") {
        if message.get("id").is_some()
            || message.get("error").is_some()
            || message.get("result").is_some()
            || !matches!(
                method.as_str(),
                Some(
                    "notifications/tools/list_changed"
                        | "notifications/progress"
                        | "notifications/message"
                )
            )
        {
            return Err(ReviewError("Unsupported HTTP server message.").into());
        }
        *changed |= method == "notifications/tools/list_changed";
        return Ok(None);
    }
    if message["id"].as_u64() == Some(id)
        && message.get("result").is_none()
        && message["error"]["code"].is_i64()
        && message["error"]["message"].is_string()
    {
        return Err(ReviewError(REJECTED).into());
    }
    if message["id"].as_u64() != Some(id)
        || message.get("error").is_some()
        || !message["result"].is_object()
        || (modern && message["result"]["resultType"] != "complete")
    {
        return Err(ReviewError("Invalid, rejected or incomplete HTTP RPC response.").into());
    }
    if let Some(metadata) = message["result"].get("_meta") {
        if !metadata.is_object()
            || metadata
                .get("io.modelcontextprotocol/serverInfo")
                .is_some_and(|info| !info["name"].is_string() || !info["version"].is_string())
        {
            return Err(ReviewError("Invalid HTTP RPC response metadata.").into());
        }
    }
    Ok(Some(message["result"].take()))
}

struct Route {
    path: Vec<String>,
    header: String,
    kind: RouteKind,
}

enum RouteKind {
    String,
    Boolean,
    Integer,
}

impl Route {
    fn value(&self, arguments: &Value) -> Result<Option<String>> {
        let mut value = arguments;
        for key in &self.path {
            let object = value
                .as_object()
                .ok_or(ReviewError("Invalid HTTP routing argument path."))?;
            let Some(next) = object.get(key) else {
                return Ok(None);
            };
            value = next;
        }
        if value.is_null() {
            return Ok(None);
        }
        match self.kind {
            RouteKind::String => value.as_str().map(str::to_owned),
            RouteKind::Boolean => value.as_bool().map(|value| value.to_string()),
            RouteKind::Integer => value
                .as_i64()
                .filter(|value| (-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(value))
                .map(|value| value.to_string()),
        }
        .map(Some)
        .ok_or_else(|| ReviewError("Invalid HTTP routing argument type.").into())
    }
}

fn routing_paths(schema: &Value) -> Result<Vec<Route>> {
    let mut stack = vec![(schema, Some(Vec::<String>::new()), false)];
    let mut headers = BTreeSet::new();
    let mut routes = Vec::new();
    let mut visited = 0;
    while let Some((node, path, is_property)) = stack.pop() {
        visited += 1;
        if visited > 10_000 {
            return Err(ReviewError("HTTP routing schema exceeds its complexity limit.").into());
        }
        let Some(node) = node.as_object() else {
            continue;
        };
        if let Some(annotation) = node.get("x-mcp-header") {
            const INVALID: ReviewError = ReviewError("Invalid HTTP routing annotation.");
            let header = annotation
                .as_str()
                .filter(|name| {
                    is_property
                        && (1..=128).contains(&name.len())
                        && name.bytes().all(|byte| {
                            byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte)
                        })
                })
                .ok_or(INVALID)?;
            let kind = match node.get("type").and_then(Value::as_str) {
                Some("string") => RouteKind::String,
                Some("boolean") => RouteKind::Boolean,
                Some("integer") => RouteKind::Integer,
                _ => return Err(INVALID.into()),
            };
            let route = Route {
                path: path.as_ref().cloned().ok_or(INVALID)?,
                header: header.to_owned(),
                kind,
            };
            if routes.len() >= 64 || !headers.insert(header.to_ascii_lowercase()) {
                return Err(INVALID.into());
            }
            routes.push(route);
        }
        for (keyword, child) in node {
            match keyword.as_str() {
                "properties" => {
                    if let Some(properties) = child.as_object() {
                        for (name, property) in properties {
                            let nested = path.as_ref().map(|path| {
                                let mut nested = path.clone();
                                nested.push(name.clone());
                                nested
                            });
                            stack.push((property, nested, true));
                        }
                    }
                }
                "patternProperties" | "$defs" | "definitions" | "dependentSchemas" => {
                    if let Some(children) = child.as_object() {
                        stack.extend(children.values().map(|value| (value, None, false)));
                    }
                }
                "allOf" | "anyOf" | "oneOf" | "prefixItems" => {
                    if let Some(children) = child.as_array() {
                        stack.extend(children.iter().map(|value| (value, None, false)));
                    }
                }
                "items"
                | "additionalProperties"
                | "unevaluatedProperties"
                | "propertyNames"
                | "contains"
                | "not"
                | "if"
                | "then"
                | "else"
                | "contentSchema"
                | "unevaluatedItems" => {
                    stack.push((child, None, false));
                }
                _ => (),
            }
        }
    }
    Ok(routes)
}

fn encode_header(value: &str) -> Result<String> {
    let plain = value == value.trim_matches([' ', '\t'])
        && value
            .bytes()
            .all(|byte| byte == b'\t' || (32..=126).contains(&byte))
        && !(value.starts_with("=?base64?") && value.ends_with("?="));
    let encoded = if plain {
        value.to_owned()
    } else {
        format!("=?base64?{}?=", STANDARD.encode(value))
    };
    if encoded.len() > 8192 {
        return Err(ReviewError("HTTP routing header exceeds its byte limit.").into());
    }
    Ok(encoded)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Write;
    use std::net::TcpListener;

    #[test]
    fn identity_binds_a_salted_token_kdf_not_a_bare_token_hash() {
        let name = "DRIFTGUARD_TEST_HTTP_IDENTITY_TOKEN";
        std::env::set_var(name, "hunter22");
        let url = "http://127.0.0.1:9/mcp";
        let open = |id: &str| {
            HttpPeer::open(&json!({
                "server_id": id, "transport": "http", "url": url,
                "allow_insecure_loopback": true, "auth_token_env": name
            }))
            .unwrap()
        };
        let peer = open("fixture");
        let binding = json!({"endpoint": url, "protocol": LEGACY,
            "token_kdf": identity_kdf("fixture", url.as_bytes(), "hunter22")});
        assert_eq!(
            peer.identity(),
            format!(
                "{:x}",
                Sha256::digest(serde_json::to_vec(&binding).unwrap())
            )
        );
        assert_ne!(open("other").identity(), peer.identity());
        std::env::remove_var(name);
    }

    #[test]
    fn requires_https_or_explicit_literal_loopback() {
        for url in [
            "http://localhost:8080/mcp",
            "http://2130706433/mcp",
            "http://127.1/mcp",
            "http://192.0.2.10/mcp",
            "https://user@example.test/mcp",
            "https://example.test/mcp?credential=value",
            "https://example.test/mcp#fragment",
        ] {
            assert!(
                HttpPeer::open(&json!({
                    "server_id": "fixture", "transport": "http", "url": url,
                    "allow_insecure_loopback": true
                }))
                .is_err(),
                "{url}"
            );
        }
        assert!(HttpPeer::open(&json!({
            "server_id": "fixture", "transport": "http", "url": "http://127.0.0.1/mcp"
        }))
        .is_err());
        assert!(HttpPeer::open(&json!({
            "server_id": "fixture", "transport": "http", "url": "http://127.0.0.1/mcp",
            "allow_insecure_loopback": true
        }))
        .is_ok());
    }

    #[test]
    fn routing_rejects_duplicate_headers_and_encodes_unicode() {
        let mut peer = HttpPeer::open(&json!({
            "server_id": "fixture", "transport": "http", "url": "https://example.test/mcp",
            "protocol_version": "2026-07-28"
        }))
        .unwrap();
        let duplicate = json!([{"name":"read", "inputSchema": {"properties":{
            "a":{"type":"string","x-mcp-header":"Region"},
            "b":{"type":"integer","x-mcp-header":"region"}
        }}}]);
        assert!(peer.set_catalog(duplicate.as_array().unwrap()).is_err());
        let valid = json!([{"name":"read", "inputSchema": {"properties":{
            "options":{"type":"object","properties":{"region":{"type":"string","x-mcp-header":"Region"}}}
        }}}]);
        peer.set_catalog(valid.as_array().unwrap()).unwrap();
        let headers = peer
            .routing_headers(
                "tools/call",
                &json!({
                    "name":"read", "arguments":{"options":{"region":"résumé\r\n"}}
                }),
            )
            .unwrap();
        assert!(headers.contains(&("Mcp-Name".into(), "read".into())));
        assert!(headers.contains(&(
            "Mcp-Param-Region".into(),
            "=?base64?csOpc3Vtw6kNCg==?=".into()
        )));
    }

    #[test]
    fn receives_sse_catalog_change_and_rejects_session_replacement() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let fixture = std::thread::spawn(move || {
            for exchange in 0..4 {
                let (mut socket, _) = listener.accept().unwrap();
                socket
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let (message, session) = {
                    let mut reader = BufReader::new(&mut socket);
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    assert!(line.starts_with("POST /mcp "));
                    let mut length = None;
                    let mut session = None;
                    loop {
                        line.clear();
                        reader.read_line(&mut line).unwrap();
                        if line == "\r\n" {
                            break;
                        }
                        let (key, value) = line.split_once(':').unwrap();
                        if key.eq_ignore_ascii_case("Content-Length") {
                            length = Some(value.trim().parse::<usize>().unwrap());
                        }
                        if key.eq_ignore_ascii_case("Mcp-Session-Id") {
                            session = Some(value.trim().to_owned());
                        }
                    }
                    let mut bytes = vec![0; length.unwrap()];
                    reader.read_exact(&mut bytes).unwrap();
                    (crate::input::parse(&bytes).unwrap(), session)
                };
                let rpc = json!({"jsonrpc":"2.0","id":message["id"],"result":{"tools":[]}});
                let (status, headers, body) = match exchange {
                    0 => {
                        assert!(session.is_none());
                        assert_eq!(message["method"], "initialize");
                        (
                            "200 OK",
                            "Content-Type: application/json\r\nMcp-Session-Id: fixture-session\r\n",
                            rpc.to_string(),
                        )
                    }
                    1 => {
                        assert_eq!(session.as_deref(), Some("fixture-session"));
                        assert_eq!(message["method"], "notifications/initialized");
                        ("202 Accepted", "", String::new())
                    }
                    2 => {
                        assert_eq!(session.as_deref(), Some("fixture-session"));
                        assert_eq!(message["method"], "tools/list");
                        let change =
                            json!({"jsonrpc":"2.0","method":"notifications/tools/list_changed"});
                        (
                            "200 OK",
                            "Content-Type: text/event-stream\r\n",
                            format!("id: first\r\ndata:\r\n\r\n:keepalive\r\ndata: {change}\r\n\r\ndata: {rpc}\r\n\r\n"),
                        )
                    }
                    _ => (
                        "200 OK",
                        "Content-Type: application/json\r\nMcp-Session-Id: different-session\r\n",
                        rpc.to_string(),
                    ),
                };
                write!(socket, "HTTP/1.1 {status}\r\n{headers}Connection: close\r\nContent-Length: {}\r\n\r\n{body}", body.len()).unwrap();
            }
        });
        let mut peer = HttpPeer::open(&json!({
            "server_id": "fixture", "transport": "http", "url": format!("http://{address}/mcp"),
            "allow_insecure_loopback": true, "timeout_seconds": 3
        }))
        .unwrap();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .unwrap();
        runtime.block_on(async {
            assert_eq!(peer.source(), "fixture");
            assert_eq!(peer.version(), LEGACY);
            assert_eq!(peer.identity().len(), 64);
            assert_eq!(peer.catalog_limits(), (8 * MAX_LINE, 1000, 100));
            peer.request("initialize", json!({})).await.unwrap();
            assert!(peer.contains_secret(&json!({"credential":"fixture-session"})));
            peer.set_version("2025-11-25");
            peer.notify("notifications/initialized").await.unwrap();
            assert_eq!(
                peer.request("tools/list", json!({})).await.unwrap()["tools"],
                json!([])
            );
            assert!(peer.take_changed());
            assert!(!peer.take_changed());
            assert!(peer.request("tools/list", json!({})).await.is_err());
            assert!(peer.verify().is_err());
        });
        fixture.join().unwrap();
    }

    fn read_fixture_request(socket: &mut std::net::TcpStream) -> Value {
        let mut reader = BufReader::new(socket);
        let mut line = String::new();
        let mut length = 0;
        reader.read_line(&mut line).unwrap();
        loop {
            line.clear();
            reader.read_line(&mut line).unwrap();
            if line == "\r\n" {
                break;
            }
            let (key, value) = line.split_once(':').unwrap();
            if key.eq_ignore_ascii_case("Content-Length") {
                length = value.trim().parse::<usize>().unwrap();
            }
        }
        let mut bytes = vec![0; length];
        reader.read_exact(&mut bytes).unwrap();
        crate::input::parse(&bytes).unwrap()
    }

    #[test]
    fn json_rpc_error_keeps_the_session_open() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let fixture = std::thread::spawn(move || {
            for exchange in 0..2 {
                let (mut socket, _) = listener.accept().unwrap();
                let message = read_fixture_request(&mut socket);
                let body = if exchange == 0 {
                    json!({"jsonrpc":"2.0","id":message["id"],
                        "error":{"code":-32602,"message":"Unknown argument"}})
                } else {
                    json!({"jsonrpc":"2.0","id":message["id"],"result":{"tools":[]}})
                }
                .to_string();
                write!(socket, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}", body.len()).unwrap();
            }
        });
        let mut peer = HttpPeer::open(&json!({
            "server_id": "fixture", "transport": "http", "url": format!("http://{address}/mcp"),
            "allow_insecure_loopback": true, "timeout_seconds": 3
        }))
        .unwrap();
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .unwrap();
        runtime.block_on(async {
            let error = peer
                .request("tools/call", json!({"name":"x","arguments":{}}))
                .await
                .unwrap_err();
            assert_eq!(error.to_string(), REJECTED);
            peer.verify().unwrap();
            assert_eq!(
                peer.request("tools/list", json!({})).await.unwrap()["tools"],
                json!([])
            );
        });
        fixture.join().unwrap();
    }
}
