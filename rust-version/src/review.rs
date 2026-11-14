use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::path::Path;
use std::time::Duration;

use crate::decision_model::DecisionModel;
use chrono::Utc;
use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

type Result<T> = std::result::Result<T, Box<dyn Error>>;

#[derive(Debug)]
pub struct ReviewError(pub &'static str);

impl fmt::Display for ReviewError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.0)
    }
}

impl Error for ReviewError {}

pub struct ReviewStore(Connection);
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MonitoringSettings {
    pub idle_seconds: u64,
    pub active_seconds: u64,
    pub active_window_seconds: u64,
    pub discovery_seconds: u64,
    pub discovery_enabled: bool,
}

impl Default for MonitoringSettings {
    fn default() -> Self {
        Self {
            idle_seconds: 300,
            active_seconds: 15,
            active_window_seconds: 120,
            discovery_seconds: 300,
            discovery_enabled: true,
        }
    }
}

impl MonitoringSettings {
    fn validate(&self) -> Result<()> {
        if !(5..=300).contains(&self.active_seconds)
            || !(15..=3600).contains(&self.idle_seconds)
            || self.active_seconds > self.idle_seconds
            || !(self.active_seconds..=3600).contains(&self.active_window_seconds)
            || !(60..=3600).contains(&self.discovery_seconds)
        {
            return Err(ReviewError("Monitoring intervals are out of range.").into());
        }
        Ok(())
    }

    pub fn catalog_interval(&self, since_use: Option<Duration>) -> Duration {
        if since_use
            .is_some_and(|elapsed| elapsed < Duration::from_secs(self.active_window_seconds))
        {
            Duration::from_secs(self.active_seconds)
        } else {
            Duration::from_secs(self.idle_seconds)
        }
    }
}

#[derive(Clone, Copy, Default, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum ApprovalMode {
    Manual,
    #[default]
    ReadOnly,
    AllFirstSeen,
}

impl ApprovalMode {
    fn allows(self, definition: &Value) -> bool {
        if !crate::gateway::callable(definition) {
            return false;
        }
        match self {
            Self::Manual => false,
            Self::AllFirstSeen => true,
            Self::ReadOnly => {
                let annotations = &definition["annotations"];
                let sensitive = ["credentials", "payment", "process"];
                let labels = crate::catalog::labels(definition);
                let operations = ["authenticate", "execute", "delete", "transmit", "write"];
                annotations["readOnlyHint"] == true
                    && annotations["destructiveHint"] != true
                    && !sensitive.iter().any(|kind| {
                        labels["resources"]
                            .as_array()
                            .is_some_and(|labels| labels.iter().any(|label| label == kind))
                    })
                    && ["name", "title", "description"].iter().all(|field| {
                        let detected = crate::catalog::decision_operations(
                            definition[field].as_str().unwrap_or_default(),
                        );
                        !operations.iter().any(|op| detected.contains(op))
                    })
            }
        }
    }
}

const MAX_REVIEW_TOOL_NAME: usize = 512;
pub struct Invocation<'a> {
    connection: &'a mut Connection,
    source: &'a str,
    name: &'a str,
    id: i64,
}

impl Invocation<'_> {
    #[cfg(test)]
    pub fn finish(self, ok: bool) -> Result<()> {
        self.finish_with_reason(
            ok,
            if ok {
                None
            } else {
                Some("upstream_or_output_failure")
            },
        )
    }

    pub fn finish_with_reason(self, ok: bool, reason: Option<&str>) -> Result<()> {
        let kind = if ok { "call_completed" } else { "call_failed" };
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        tx.execute(
            "UPDATE sentinel_calls SET state=?2,ended_at=?3,reason=?4 WHERE id=?1",
            params![
                self.id,
                if ok { "completed" } else { "failed" },
                timestamp(),
                reason
            ],
        )?;
        event(
            &tx,
            kind,
            self.source,
            Some(self.name),
            json!({"call_id":self.id,"reason":reason}),
        )?;
        tx.commit()?;
        Ok(())
    }
}

fn record_denial(
    tx: &Transaction<'_>,
    source: &str,
    session: &str,
    name: &str,
    digest: Option<&str>,
    reason: &str,
) -> Result<i64> {
    let now = timestamp();
    tx.execute(
        "INSERT INTO sentinel_calls(source,session,tool,sha256,started_at,ended_at,state,reason)
        VALUES (?1,?2,?3,?4,?5,?5,'blocked',?6)",
        params![source, session, name, digest, now, reason],
    )?;
    Ok(tx.last_insert_rowid())
}

const TOOL_COLUMNS: &str =
    "server_id, tool_name, sha256, definition, revision, status, observed_at";

fn timestamp() -> String {
    Utc::now().to_rfc3339()
}

fn fresh_heartbeat(timestamp: &str, now: chrono::DateTime<Utc>) -> bool {
    chrono::DateTime::parse_from_rfc3339(timestamp)
        .is_ok_and(|at| (0..=20).contains(&(now - at.to_utc()).num_seconds()))
}

fn text<'a>(value: &'a Value, field: &str, limit: usize) -> Result<&'a str> {
    value[field]
        .as_str()
        .filter(|value| !value.trim().is_empty() && value.len() <= limit)
        .ok_or_else(|| ReviewError("A required text field is invalid.").into())
}

fn hash(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

const CODEX_APPS: &str = "harness:codex:codex_apps";

fn connector_group(name: &str, definition: &Value) -> Option<Value> {
    let (id, _) = name.split_once('.')?;
    if id.is_empty()
        || id.len() > 128
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-".contains(&byte))
    {
        return None;
    }
    let label = definition["_meta"]["connector_name"]
        .as_str()
        .map(str::trim)
        .filter(|label| {
            !label.is_empty() && label.len() <= 120 && !label.chars().any(char::is_control)
        });
    let fallback = id.replace(['_', '-'], " ");
    Some(json!({"id":id, "label":label.unwrap_or(&fallback)}))
}

fn tool_record(row: &rusqlite::Row<'_>, summary: bool) -> rusqlite::Result<Value> {
    let encoded: String = row.get(3)?;
    let definition = crate::input::parse(encoded.as_bytes()).map_err(|error| {
        rusqlite::Error::FromSqlConversionFailure(3, rusqlite::types::Type::Text, Box::new(error))
    })?;
    let source: String = row.get(0)?;
    let name: String = row.get(1)?;
    let mut record = json!({
        "server_id": source, "tool_name": name,
        "sha256": row.get::<_, String>(2)?, "revision": row.get::<_, i64>(4)?,
        "status": row.get::<_, String>(5)?, "observed_at": row.get::<_, String>(6)?,
        "description": definition["description"].as_str().unwrap_or_default(),
    });
    if source == CODEX_APPS || source.starts_with("gateway:") && source.ends_with(":codex-hosted") {
        if let Some(connection) = connector_group(&name, &definition) {
            record["connection"] = connection;
        }
    }
    if summary {
        record["catalog"] = crate::catalog::labels(&definition);
    } else {
        record["new_tool"] = definition.clone();
        record["definition"] = definition;
    }
    Ok(record)
}

fn event(
    tx: &Transaction<'_>,
    kind: &str,
    source: &str,
    tool: Option<&str>,
    detail: Value,
) -> Result<()> {
    tx.execute(
        "INSERT INTO events(kind, source, tool, timestamp, detail) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![kind, source, tool, timestamp(), detail.to_string()],
    )?;
    Ok(())
}

impl ReviewStore {
    pub(crate) fn helper_transaction(&mut self) -> rusqlite::Result<Transaction<'_>> {
        self.0
            .transaction_with_behavior(TransactionBehavior::Immediate)
    }

    pub fn open(path: &Path) -> Result<Self> {
        let existing = match std::fs::symlink_metadata(path) {
            Ok(meta) => Some(meta),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(error.into()),
        };
        if existing
            .as_ref()
            .is_some_and(|meta| !meta.file_type().is_file())
        {
            return Err(ReviewError("Choose a regular database file.").into());
        }
        if existing.is_none() {
            let mut options = std::fs::OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            match options.open(path) {
                Ok(_) => (),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => (),
                Err(error) => return Err(error.into()),
            }
        }
        let mut db = Connection::open(path)?;
        db.busy_timeout(Duration::from_secs(5))?;
        let existing_python: bool = db.query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='guard_tools')",
            [],
            |row| row.get(0),
        )?;
        if existing_python {
            return Err(ReviewError("Choose a separate database for the Rust port.").into());
        }
        db.execute_batch(include_str!("schema.sql"))?;
        const LEGACY_SESSIONS: &str =
            "SELECT pk=0 FROM pragma_table_info('gateway_sessions') WHERE name='session'";
        if db.query_row(LEGACY_SESSIONS, [], |row| row.get::<_, bool>(0))? {
            let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
            if tx.query_row(LEGACY_SESSIONS, [], |row| row.get::<_, bool>(0))? {
                tx.execute_batch(
                    "ALTER TABLE gateway_sessions RENAME TO gateway_sessions_legacy;
                     CREATE TABLE gateway_sessions(
                         source TEXT NOT NULL REFERENCES sources(server_id),
                         session TEXT NOT NULL, heartbeat TEXT NOT NULL,
                         PRIMARY KEY(source,session)
                     );
                     INSERT INTO gateway_sessions SELECT source,session,heartbeat FROM gateway_sessions_legacy;
                     DROP TABLE gateway_sessions_legacy;",
                )?;
            }
            tx.commit()?;
        }
        Ok(Self(db))
    }

    pub fn request(&mut self, request: &Value) -> Result<Value> {
        let action = text(request, "action", 64)?;
        match action {
            "sentinel_calls" => self.sentinel_calls(request),
            "sentinel_evidence" => {
                let id = request["call_id"]
                    .as_i64()
                    .filter(|id| *id > 0)
                    .ok_or(ReviewError("Choose a recorded Sentinel call."))?;
                let row: Option<(String, String, Option<String>, String)> = self
                    .0
                    .query_row(
                        "SELECT source,tool,sha256,started_at FROM sentinel_calls WHERE id=?1",
                        [id],
                        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
                    )
                    .optional()?;
                let (source, tool, digest, at) =
                    row.ok_or(ReviewError("This call record is no longer available."))?;
                let definition: Option<String> = self.0.query_row(
                    "SELECT definition FROM history WHERE server_id=?1 AND tool_name=?2 AND sha256=?3
                     ORDER BY revision DESC LIMIT 1", params![source,tool,digest], |row| row.get(0),
                ).optional()?;
                let changes = {
                    let mut stmt = self.0.prepare("SELECT id,kind,source,tool,timestamp,detail FROM events
                        WHERE source=?1 AND (tool=?2 OR tool IS NULL) AND timestamp<=?3
                        AND kind IN ('definition_changed','tool_approved','tool_auto_approved','tool_denied','tool_quarantined','tool_release_quarantine','tool_blocked','tool_unblocked','server_stopped','server_resumed')
                        ORDER BY id DESC LIMIT 15")?;
                    let rows = stmt
                        .query_map(params![source, tool, at], event_record)?
                        .collect::<rusqlite::Result<Vec<_>>>()?;
                    rows
                };
                let policy = self.0.query_row(
                    "SELECT EXISTS(SELECT 1 FROM gateway_routes r JOIN sentinel_stops x USING(server_id) WHERE r.route=?1),
                        EXISTS(SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=?1 AND b.tool_name=?2),
                        EXISTS(SELECT 1 FROM tools t
                            WHERE t.server_id=?1 AND t.tool_name=?2 AND t.sha256=?3
                            AND t.present=1 AND t.status='approved'
                            AND EXISTS(SELECT 1 FROM gateway_sessions g WHERE g.source=t.server_id
                                AND julianday(g.heartbeat)>julianday('now','-20 seconds'))
                            AND NOT EXISTS (SELECT 1 FROM quarantines q WHERE q.server_id=t.server_id
                                AND q.tool_name=t.tool_name AND q.sha256=t.sha256))",
                    params![source, tool, digest],
                    |row| Ok((row.get::<_, bool>(0)?, row.get::<_, bool>(1)?, row.get::<_, bool>(2)?)),
                )?;
                let preview = match policy {
                    (true, _, _) => "server_stopped",
                    (_, true, _) => "tool_blocked",
                    (_, _, true) => "version_eligible",
                    _ => "version_not_approved",
                };
                Ok(
                    json!({"definition":definition.map(|s| crate::input::parse(s.as_bytes())).transpose()?,"changes":changes,"current_policy":preview}),
                )
            }
            "sentinel_stop" | "sentinel_resume" => {
                self.sentinel_stop(request, action == "sentinel_stop")
            }
            "sentinel_clear" => {
                self.0.execute("DELETE FROM sentinel_calls WHERE ended_at IS NOT NULL OR NOT EXISTS(
                    SELECT 1 FROM gateway_sessions g WHERE g.source=sentinel_calls.source AND g.session=sentinel_calls.session
                    AND julianday(g.heartbeat)>julianday('now','-315 seconds'))", [])?;
                Ok(json!({"cleared":true}))
            }
            "overview" => self.overview(),
            "connection_graph" => self.connection_graph(),
            "list_tools" => self.list(request),
            "review" => self.review(
                text(request, "server_id", 1024)?,
                text(request, "tool_name", MAX_REVIEW_TOOL_NAME)?,
            ),
            "history" => self.history(
                text(request, "server_id", 1024)?,
                text(request, "tool_name", MAX_REVIEW_TOOL_NAME)?,
            ),
            "activity" => self.activity(None),
            "approval_mode" => Ok(serde_json::to_value(read_approval_mode(&self.0)?)?),
            "set_approval_mode" => {
                let mode: ApprovalMode = serde_json::from_value(request["mode"].clone())
                    .map_err(|_| ReviewError("Choose a supported approval mode."))?;
                let mode = serde_json::to_value(mode)?;
                self.0.execute(
                    "INSERT INTO approval_policy VALUES (1,?1)
                    ON CONFLICT(id) DO UPDATE SET mode=excluded.mode",
                    [mode.as_str()],
                )?;
                Ok(mode)
            }
            "monitoring_settings" => Ok(serde_json::to_value(self.monitoring_settings()?)?),
            "set_monitoring_settings" => {
                let settings: MonitoringSettings =
                    serde_json::from_value(request["settings"].clone())
                        .map_err(|_| ReviewError("Invalid MCP monitoring settings."))?;
                settings.validate()?;
                self.0.execute(
                    "INSERT INTO monitoring_settings VALUES (1,?1)
                     ON CONFLICT(id) DO UPDATE SET settings=excluded.settings",
                    [serde_json::to_string(&settings)?],
                )?;
                Ok(serde_json::to_value(settings)?)
            }
            "mcp_activity" => {
                let before = request["before_id"].as_i64().unwrap_or(i64::MAX);
                let include_checks = request["include_checks"].as_bool().unwrap_or(true);
                let mut query = self.0.prepare(
                    "SELECT id,kind,source,tool,timestamp,detail FROM events
                     WHERE id<?1 AND (?2 OR kind<>'catalog_observed') AND (
                        kind='catalog_check_failed' OR source LIKE 'gateway:%' OR source LIKE 'harness:%'
                        OR source LIKE 'import:%' OR source LIKE 'stdio:%' OR source LIKE 'http:%')
                     ORDER BY id DESC LIMIT 100",
                )?;
                let events = query
                    .query_map(params![before, include_checks], event_record)?
                    .collect::<rusqlite::Result<Vec<_>>>()?;
                Ok(json!(events))
            }
            "tool_activity" => self.activity(Some((
                text(request, "server_id", 1024)?,
                text(request, "tool_name", MAX_REVIEW_TOOL_NAME)?,
            ))),
            "definition_alerts" => self.alerts(None),
            "dismiss_definition_alerts" => self.alerts(Some(
                request["through_id"]
                    .as_i64()
                    .filter(|id| *id > 0)
                    .ok_or(ReviewError("A valid alert ID is required."))?,
            )),
            "import_definitions" => self.observe(request),
            "model_features" => {
                let pairs = request["pairs"]
                    .as_array()
                    .filter(|pairs| pairs.len() <= 256)
                    .ok_or(ReviewError("Expected up to 256 model feature pairs."))?;
                let rows = pairs
                    .iter()
                    .map(|pair| {
                        if !pair["old_tool"].is_object() || !pair["new_tool"].is_object() {
                            return Err(ReviewError("Each pair requires two tool definitions."));
                        }
                        Ok(crate::decision_model::features(
                            &pair["old_tool"],
                            &pair["new_tool"],
                        ))
                    })
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                Ok(json!(rows))
            }
            "block_tool" | "unblock_tool" | "block_tool_all" | "unblock_tool_all" => {
                self.set_block(request, action)
            }
            "approve" | "deny" | "quarantine" | "release_quarantine" => {
                self.decide(action, request)
            }
            _ => Err(ReviewError("This action has not been ported.").into()),
        }
    }

    pub(crate) fn connection(&self) -> &Connection {
        &self.0
    }

    pub(crate) fn observe_gateway_catalog(
        &mut self,
        source: &str,
        identity: &str,
        tools: &[Value],
    ) -> Result<Value> {
        self.ingest(source.to_owned(), identity, tools, None, None)
    }

    pub fn monitoring_settings(&self) -> Result<MonitoringSettings> {
        let stored: Option<String> = self
            .0
            .query_row(
                "SELECT settings FROM monitoring_settings WHERE id=1",
                [],
                |row| row.get(0),
            )
            .optional()?;
        let settings: MonitoringSettings = stored
            .map(|value| serde_json::from_str(&value))
            .transpose()?
            .unwrap_or_default();
        settings.validate()?;
        Ok(settings)
    }

    pub fn model_artifact(&self) -> Result<Option<String>> {
        read_model_artifact(&self.0)
    }

    pub fn set_model_artifact(&self, artifact: Option<&str>) -> Result<()> {
        if let Some(artifact) = artifact {
            DecisionModel::parse(artifact.as_bytes())?;
            self.0.execute(
                "INSERT OR REPLACE INTO decision_model VALUES(1,?1)",
                [artifact],
            )?;
        } else {
            self.0
                .execute("DELETE FROM decision_model WHERE id=1", [])?;
        }
        Ok(())
    }

    fn overview(&self) -> Result<Value> {
        let mut query = self
            .0
            .prepare("SELECT server_id FROM sources ORDER BY server_id")?;
        let sources = query
            .query_map([], |row| {
                let source = row.get::<_, String>(0)?;
                let display = source
                    .strip_prefix("harness:")
                    .and_then(|rest| rest.split_once(':'))
                    .and_then(|(client, name)| {
                        crate::harness::client_label(client)
                            .map(|label| format!("{name} · {label}"))
                    })
                    .unwrap_or_else(|| {
                        source
                            .strip_prefix("import:")
                            .or_else(|| source.strip_prefix("stdio:"))
                            .unwrap_or(&source)
                            .to_owned()
                    });
                Ok(json!({"server_id": source, "display_name": display}))
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let mut query = self.0.prepare(
            "SELECT status, COUNT(*) FROM tools t WHERE present=1
                AND NOT EXISTS(SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=t.server_id
                    AND b.tool_name=t.tool_name) GROUP BY status",
        )?;
        let counts = query
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, u64>(1)?))
            })?
            .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
        let mut health_query = self.0.prepare(
            "SELECT source, MAX(heartbeat),
                SUM(julianday(heartbeat)>julianday('now','-20 seconds'))
                FROM gateway_sessions GROUP BY source ORDER BY source",
        )?;
        let now = Utc::now();
        let health = health_query.query_map([], |row| {
            let timestamp: String = row.get(1)?;
            let active = fresh_heartbeat(&timestamp, now);
            Ok(json!({"server_id": row.get::<_, String>(0)?, "heartbeat_at": timestamp, "active": active,
                "sessions": row.get::<_, u64>(2)?}))
        })?.collect::<rusqlite::Result<Vec<_>>>()?;
        let active = health.iter().any(|item| item["active"] == true);
        let blocked: u64 = self.0.query_row(
            "SELECT COUNT(*) FROM tools t WHERE present=1 AND EXISTS(
                SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=t.server_id AND b.tool_name=t.tool_name)",
            [], |row| row.get(0),
        )?;
        Ok(
            json!({"protection_status":if active {"gateway_active"} else {"review_only"}, "servers":sources.len(),
            "server_list": sources, "tools":counts.values().sum::<u64>()+blocked,
            "pending":counts.get("pending").copied().unwrap_or(0),
            "approved":counts.get("approved").copied().unwrap_or(0),
            "quarantined":counts.get("quarantined").copied().unwrap_or(0),
            "scope":"Only clients routed through the Rust gateway use its approval decisions.", "gateway_health": health}),
        )
    }

    fn connection_graph(&self) -> Result<Value> {
        let mut query = self.0.prepare(
            "SELECT s.server_id, r.server_id,
                (SELECT MAX(g.heartbeat) FROM gateway_sessions g WHERE g.source=s.server_id),
                t.tool_name, t.status,
                EXISTS(SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=t.server_id AND b.tool_name=t.tool_name),
                (SELECT COUNT(*) FROM history h WHERE h.server_id=t.server_id AND h.tool_name=t.tool_name),
                CASE WHEN t.server_id=?1 OR r.server_id='codex-hosted' THEN t.definition END,
                EXISTS(SELECT 1 FROM sentinel_stops x WHERE x.server_id=r.server_id),
                (SELECT e.timestamp FROM events e WHERE e.source=s.server_id
                    AND e.kind='catalog_observed' ORDER BY e.id DESC LIMIT 1)
             FROM sources s
             LEFT JOIN gateway_routes r ON r.route=s.server_id
             LEFT JOIN tools t ON t.server_id=s.server_id AND t.present=1
             ORDER BY s.server_id, t.tool_name",
        )?;
        let mut rows = query.query([CODEX_APPS])?;
        let mut routes = Vec::<Value>::new();
        let now = Utc::now();
        while let Some(row) = rows.next()? {
            let source: String = row.get(0)?;
            if routes
                .last()
                .is_none_or(|route| route["source_id"] != source)
            {
                let server: Option<String> = row.get(1)?;
                let heartbeat: Option<String> = row.get(2)?;
                let gateway = server.is_some();
                let configured = source
                    .strip_prefix("harness:")
                    .and_then(|rest| rest.split_once(':'));
                let client = server
                    .as_ref()
                    .and_then(|_| {
                        source
                            .strip_prefix("gateway:")?
                            .split_once(':')
                            .map(|(client, _)| client)
                    })
                    .or_else(|| configured.map(|(client, _)| client));
                let label = client.and_then(crate::harness::client_label).or_else(|| {
                    client
                        .filter(|id| *id == "direct")
                        .map(|_| "Direct MCP client")
                });
                let server_id = server
                    .as_deref()
                    .or_else(|| configured.map(|(_, name)| name))
                    .unwrap_or_else(|| {
                        source
                            .strip_prefix("import:")
                            .or_else(|| source.strip_prefix("stdio:"))
                            .unwrap_or(&source)
                    });
                routes.push(json!({
                    "source_id":source, "server_id":server_id,
                    "kind":if gateway { "gateway" } else { "review" },
                    "client_id":client, "client_label":label,
                    "active":heartbeat.as_deref().is_some_and(|at| fresh_heartbeat(at, now)),
                    "stopped":row.get::<_,bool>(8)?,
                    "last_checked":row.get::<_,Option<String>>(9)?,
                    "tools":[],
                }));
            }
            if let Some(tool) = row.get::<_, Option<String>>(3)? {
                let status: String = row.get(4)?;
                let blocked: bool = row.get(5)?;
                let versions: u64 = row.get(6)?;
                let mut entry = json!({
                    "tool_name":tool, "status":if blocked { "blocked" } else { &status },
                    "version_count":versions,
                });
                if let Some(definition) = row.get::<_, Option<String>>(7)? {
                    if let Some(connection) =
                        connector_group(&tool, &crate::input::parse(definition.as_bytes())?)
                    {
                        entry["connection"] = connection;
                    }
                }
                routes.last_mut().unwrap()["tools"]
                    .as_array_mut()
                    .unwrap()
                    .push(entry);
            }
        }
        let mut registered = self
            .0
            .prepare("SELECT name,state FROM standalone_servers ORDER BY name")?;
        for row in registered.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })? {
            let (name, state) = row?;
            let source = format!("gateway:direct:{name}");
            if let Some(route) = routes.iter_mut().find(|route| route["source_id"] == source) {
                route["connection_state"] = json!(state);
            } else {
                routes.push(json!({"source_id":source,"server_id":name,"kind":"gateway",
                    "client_id":"direct","client_label":"Direct MCP client","active":false,
                    "connection_state":state,"tools":[]}));
            }
        }
        Ok(json!(routes))
    }

    fn list(&self, request: &Value) -> Result<Value> {
        let source = request["server_id"].as_str();
        let summary = request["summary"].as_bool().unwrap_or(false);
        let mut query = self.0.prepare(&format!(
            "SELECT {TOOL_COLUMNS}, EXISTS(SELECT 1 FROM blocked_tool_routes b
                WHERE b.server_id=t.server_id AND b.tool_name=t.tool_name)
             FROM tools t WHERE present=1 AND (?1 IS NULL OR server_id=?1)
             ORDER BY server_id, tool_name"
        ))?;
        let rows = query
            .query_map([source], |row| {
                let mut record = tool_record(row, summary)?;
                if row.get::<_, bool>(7)? {
                    record["blocked"] = json!(true);
                }
                Ok(record)
            })?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(json!(rows))
    }

    pub fn pending_gateway_tools(&self) -> Result<u64> {
        Ok(self.0.query_row(
            "SELECT COUNT(*) FROM tools t WHERE t.present=1 AND t.status='pending' AND
             NOT EXISTS(SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=t.server_id AND b.tool_name=t.tool_name) AND
             EXISTS(SELECT 1 FROM gateway_sessions s WHERE s.source=t.server_id
                 AND julianday(s.heartbeat) > julianday('now','-20 seconds'))",
            [],
            |row| row.get(0),
        )?)
    }

    fn review(&self, source: &str, name: &str) -> Result<Value> {
        let mut record = self
            .0
            .query_row(
                &format!("SELECT {TOOL_COLUMNS} FROM tools WHERE server_id=?1 AND tool_name=?2"),
                [source, name],
                |row| tool_record(row, false),
            )
            .optional()?
            .ok_or(ReviewError("Unknown observed tool."))?;
        let baseline: Option<String> = self
            .0
            .query_row(
                "SELECT definition FROM baselines WHERE server_id=?1 AND tool_name=?2",
                [source, name],
                |row| row.get(0),
            )
            .optional()?;
        let kind = if baseline.is_some() {
            "approved"
        } else {
            "observed"
        };
        let baseline = match baseline {
            Some(definition) => Some(definition),
            None => self.0.query_row(
                "SELECT definition FROM history WHERE server_id=?1 AND tool_name=?2 ORDER BY revision LIMIT 1",
                [source, name], |row| row.get(0),
            ).optional()?,
        };
        record["baseline_kind"] = json!(baseline.as_ref().map(|_| kind));
        record["old_tool"] = baseline
            .map(|text| crate::input::parse(text.as_bytes()))
            .transpose()?
            .unwrap_or(Value::Null);
        record["quarantine_active"] = json!(self.0.query_row(
            "SELECT EXISTS(SELECT 1 FROM quarantines WHERE server_id=?1 AND tool_name=?2 AND sha256=?3)",
            params![source, name, record["sha256"].as_str()], |row| row.get::<_, bool>(0))?);
        if source.starts_with("gateway:") {
            record["blocked"] = json!(is_blocked(&self.0, source, name)?);
            let (local, shared): (bool, bool) = self.0.query_row(
                "SELECT EXISTS(SELECT 1 FROM tool_blocks WHERE server_id=?1 AND tool_name=?2),
                        EXISTS(SELECT 1 FROM shared_tool_blocks b JOIN gateway_routes r USING(server_id)
                            WHERE r.route=?1 AND b.tool_name=?2)",
                params![source, name], |row| Ok((row.get(0)?, row.get(1)?)),
            )?;
            record["route_blocked"] = json!(local);
            record["shared_blocked"] = json!(shared);
            let evidence: Option<String> = self.0.query_row(
                "SELECT evidence FROM model_decisions WHERE server_id=?1 AND tool_name=?2 AND sha256=?3",
                params![source,name,record["sha256"].as_str()], |row| row.get(0),
            ).optional()?;
            if let Some(evidence) = evidence {
                record["model_decision"] = crate::input::parse(evidence.as_bytes())?;
            }
        }
        Ok(record)
    }

    fn set_block(&mut self, request: &Value, action: &str) -> Result<Value> {
        let source = text(request, "server_id", 1024)?;
        let name = text(request, "tool_name", 128)?;
        if !source.starts_with("gateway:") {
            return Err(ReviewError(
                "Blocking applies to tools discovered through the Rust gateway.",
            )
            .into());
        }
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let exists: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM tools WHERE server_id=?1 AND tool_name=?2)",
            params![source, name],
            |row| row.get(0),
        )?;
        if !exists {
            return Err(ReviewError("Unknown observed tool.").into());
        }
        let shared = action.ends_with("_all");
        let target: String = if shared {
            tx.query_row(
                "SELECT server_id FROM gateway_routes WHERE route=?1",
                [source],
                |row| row.get(0),
            )?
        } else {
            source.to_owned()
        };
        let sql = match action {
            "block_tool" => "INSERT OR IGNORE INTO tool_blocks VALUES(?1,?2)",
            "unblock_tool" => "DELETE FROM tool_blocks WHERE server_id=?1 AND tool_name=?2",
            "block_tool_all" => "INSERT OR IGNORE INTO shared_tool_blocks VALUES(?1,?2)",
            _ => "DELETE FROM shared_tool_blocks WHERE server_id=?1 AND tool_name=?2",
        };
        let changed = tx.execute(sql, params![target, name])?;
        if changed != 0 {
            tx.execute(
                "UPDATE tools SET revision=revision+1,
                 status=CASE WHEN status='approved' THEN 'pending' ELSE status END
                 WHERE tool_name=?2 AND ((?3=0 AND server_id=?1)
                    OR (?3=1 AND server_id IN (SELECT route FROM gateway_routes WHERE server_id=?1)))",
                params![target, name, shared],
            )?;
            let kind = if action.starts_with("block") {
                "tool_blocked"
            } else {
                "tool_unblocked"
            };
            event(
                &tx,
                kind,
                source,
                Some(name),
                json!({
                    "scope": if shared { "all_routes" } else { "route" }, "target":target,
                }),
            )?;
        }
        tx.commit()?;
        self.review(source, name)
    }

    fn history(&self, source: &str, name: &str) -> Result<Value> {
        let mut query = self.0.prepare(&format!(
            "SELECT {TOOL_COLUMNS} FROM history WHERE server_id=?1 AND tool_name=?2 ORDER BY revision"))?;
        let mut entries = query
            .query_map([source, name], |row| tool_record(row, false))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let review = self.review(source, name)?;
        let baseline = &review["old_tool"];
        let reference = if review["baseline_kind"] == "approved" {
            "approved_reference"
        } else {
            "observed_reference"
        };
        for entry in &mut entries {
            entry["raw_tool"] = entry["definition"].clone();
            entry["status"] = json!(if &entry["definition"] == baseline {
                reference
            } else {
                "observed"
            });
        }
        Ok(json!(entries))
    }

    fn observe(&mut self, request: &Value) -> Result<Value> {
        let id = text(request, "server_id", 200)?;
        let source = if id.starts_with("import:") {
            id.to_owned()
        } else {
            format!("import:{id}")
        };
        let identity = text(request, "identity", 512)?;
        let definitions = request["tools"]
            .as_array()
            .ok_or(ReviewError("Expected at most 500 tool definitions."))?;
        self.observe_catalog(source, identity, definitions)
    }

    pub fn observe_catalog(
        &mut self,
        source: String,
        identity: &str,
        definitions: &[Value],
    ) -> Result<Value> {
        self.ingest(source, identity, definitions, None, None)
    }

    pub fn observe_gateway(
        &mut self,
        source: &str,
        identity: &str,
        definitions: &[Value],
        session: &str,
        start: bool,
        model: Option<(&DecisionModel, &str)>,
    ) -> Result<Value> {
        self.ingest(
            source.to_owned(),
            identity,
            definitions,
            Some((session, start)),
            model,
        )
    }

    fn ingest(
        &mut self,
        source: String,
        identity: &str,
        definitions: &[Value],
        session: Option<(&str, bool)>,
        model: Option<(&DecisionModel, &str)>,
    ) -> Result<Value> {
        let host_review = source.starts_with("harness:codex:");
        let (max_tools, max_bytes, max_name) = if host_review {
            (5000, 8 * 1024 * 1024, MAX_REVIEW_TOOL_NAME)
        } else {
            (500, 2 * 1024 * 1024, 128)
        };
        if definitions.len() > max_tools {
            return Err(ReviewError("The tool catalog exceeds the definition limit.").into());
        }
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous_identity: Option<String> = tx
            .query_row(
                "SELECT identity FROM sources WHERE server_id=?1",
                [&source],
                |row| row.get(0),
            )
            .optional()?;
        if let Some((session, start)) = session {
            check_model_artifact(&tx, model.map(|(_, artifact)| artifact))?;
            let known = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM gateway_sessions WHERE source=?1 AND session=?2)",
                params![source, session],
                |row| row.get::<_, bool>(0),
            )?;
            if !start && (!known || previous_identity.as_deref() != Some(identity)) {
                return Err(ReviewError("Gateway session is no longer active.").into());
            }
        }
        if previous_identity
            .as_deref()
            .is_some_and(|previous| previous != identity)
        {
            tx.execute(
                "UPDATE tools SET status='revoked', revision=revision+1 WHERE server_id=?1",
                [&source],
            )?;
            tx.execute("DELETE FROM baselines WHERE server_id=?1", [&source])?;
            tx.execute("DELETE FROM gateway_sessions WHERE source=?1", [&source])?;
        }
        tx.execute(
            "INSERT INTO sources VALUES (?1, ?2)
             ON CONFLICT(server_id) DO UPDATE SET identity=excluded.identity",
            params![source, identity],
        )?;
        if previous_identity.is_none() && (source != CODEX_APPS || definitions.is_empty()) {
            let name = source.rsplit(':').next().unwrap_or(&source);
            event(&tx, "mcp_added", &source, None, json!({"name":name}))?;
        }
        if let Some((session, start)) = session {
            let now = timestamp();
            if start {
                tx.execute(
                    "DELETE FROM gateway_sessions WHERE source=?1
                     AND julianday(heartbeat) <= julianday(?2,'-315 seconds')",
                    params![source, now],
                )?;
                tx.execute(
                    "INSERT INTO gateway_sessions VALUES (?1,?2,?3)",
                    params![source, session, now],
                )?;
                event(&tx, "gateway_connected", &source, None, json!({}))?;
            } else {
                tx.execute(
                    "UPDATE gateway_sessions SET heartbeat=?3 WHERE source=?1 AND session=?2",
                    params![source, session, now],
                )?;
            }
        }
        let approval_mode = if session.is_some()
            && (!source.starts_with("gateway:direct:")
                || tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM standalone_servers WHERE name=?1)",
                    [source.strip_prefix("gateway:direct:").unwrap_or_default()],
                    |row| row.get::<_, bool>(0),
                )?) {
            read_approval_mode(&tx)?
        } else {
            ApprovalMode::Manual
        };
        tx.execute("UPDATE tools SET present=0 WHERE server_id=?1", [&source])?;
        let mut names = std::collections::BTreeSet::new();
        let mut total_bytes = 0;
        for definition in definitions {
            let name = text(definition, "name", max_name)?;
            let valid_name = if host_review {
                !name.chars().any(char::is_control)
            } else {
                name.bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
            };
            if !valid_name
                || !names.insert(name)
                || !definition["inputSchema"].is_object()
                || ["outputSchema", "annotations"].iter().any(|field| {
                    definition
                        .get(*field)
                        .is_some_and(|value| !value.is_object())
                })
                || definition
                    .get("description")
                    .is_some_and(|value| !value.is_string())
            {
                return Err(ReviewError("Invalid or duplicate tool definition.").into());
            }
            let encoded = serde_json::to_string(definition)?;
            total_bytes += encoded.len();
            if encoded.len() > 65536 || total_bytes > max_bytes {
                return Err(ReviewError("The tool catalog exceeds the storage limit.").into());
            }
            let digest = hash(&encoded);
            let previous: Option<(String, i64, String)> = tx
                .query_row(
                    "SELECT definition, revision, status FROM tools WHERE server_id=?1 AND tool_name=?2",
                    [&source, name],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .optional()?;
            let seen = timestamp();
            if previous.is_none() && source == CODEX_APPS {
                if let Some(connection) = connector_group(name, definition) {
                    let prefix = format!("{}.", connection["id"].as_str().unwrap_or_default());
                    let known: bool = tx.query_row(
                        "SELECT EXISTS(SELECT 1 FROM history WHERE server_id=?1
                         AND substr(tool_name,1,length(?2))=?2)",
                        params![source, prefix],
                        |row| row.get(0),
                    )?;
                    if !known {
                        event(
                            &tx,
                            "mcp_added",
                            &source,
                            None,
                            json!({"name":connection["label"],"connector":connection["id"]}),
                        )?;
                    }
                }
            }
            if let Some((client, server)) = source
                .strip_prefix("gateway:")
                .and_then(|route| route.split_once(':'))
                .filter(|(client, _)| *client != "direct")
                .filter(|_| previous.is_none())
            {
                let discovered = format!("harness:{client}:{server}");
                // Carry over exact-version restrictions recorded before the route was installed.
                let inherited = tx.execute(
                    "INSERT OR IGNORE INTO quarantines
                     SELECT ?1,tool_name,sha256 FROM quarantines
                     WHERE server_id=?2 AND tool_name=?3 AND sha256=?4",
                    params![source, discovered, name, digest],
                )?;
                if inherited > 0 {
                    tx.execute(
                        "UPDATE tools SET status='quarantined',revision=revision+1
                         WHERE server_id=?1 AND tool_name=?2 AND sha256=?3 AND status<>'quarantined'",
                        params![source, name, digest],
                    )?;
                    event(
                        &tx,
                        "tool_quarantined",
                        &source,
                        Some(name),
                        json!({"sha256":digest,"inherited_from":discovered}),
                    )?;
                }
            }
            if previous.is_none()
                && source.starts_with("gateway:")
                && source.ends_with(":codex-hosted")
            {
                let restriction: Option<String> = tx.query_row(
                    "SELECT CASE WHEN EXISTS (
                        SELECT 1 FROM quarantines q WHERE q.server_id=t.server_id AND q.tool_name=t.tool_name
                     ) THEN 'quarantined' ELSE t.status END
                     FROM tools t WHERE t.server_id=?1 AND t.tool_name=?2",
                    params![CODEX_APPS,name], |row| row.get(0),
                ).optional()?;
                if restriction.as_deref() == Some("quarantined") {
                    tx.execute(
                        "INSERT OR IGNORE INTO quarantines VALUES(?1,?2,?3)",
                        params![source, name, digest],
                    )?;
                } else if restriction.as_deref() == Some("denied") {
                    tx.execute(
                        "INSERT OR IGNORE INTO model_overrides VALUES(?1,?2,?3,'denied')",
                        params![source, name, digest],
                    )?;
                }
            }
            let initial_pending = previous.as_ref().is_none_or(|(prior, revision, status)| {
                prior == &encoded && *revision == 1 && status == "pending"
            });
            let auto = initial_pending && approval_mode.allows(definition)
                && !is_blocked(&tx, &source, name)?
                && !tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM model_overrides WHERE server_id=?1 AND tool_name=?2 AND sha256=?3
                        UNION ALL SELECT 1 FROM quarantines WHERE server_id=?1 AND tool_name=?2 AND sha256=?3)",
                    params![source, name, digest], |row| row.get::<_, bool>(0),
                )?;
            if auto {
                tx.execute(
                    "INSERT OR REPLACE INTO baselines VALUES (?1,?2,?3)",
                    params![source, name, encoded],
                )?;
                event(
                    &tx,
                    "tool_auto_approved",
                    &source,
                    Some(name),
                    json!({"sha256":digest,"mode":approval_mode}),
                )?;
            }
            let quarantined: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM quarantines WHERE server_id=?1 AND tool_name=?2 AND sha256=?3)",
                params![source, name, digest], |row| row.get(0))?;
            let denied: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM model_overrides
                    WHERE server_id=?1 AND tool_name=?2 AND sha256=?3 AND decision='denied')",
                params![source, name, digest],
                |row| row.get(0),
            )?;
            if previous
                .as_ref()
                .is_some_and(|(definition, _, _)| definition == &encoded)
            {
                // Reappearance after revocation keeps exact-hash quarantine and denial latches.
                let reobserved = if quarantined {
                    "quarantined"
                } else if denied {
                    "denied"
                } else {
                    "pending"
                };
                tx.execute(
                    "UPDATE tools SET present=1, observed_at=?3,
                           status=CASE WHEN ?4 THEN 'approved' WHEN status='revoked' THEN ?5 ELSE status END,
                           revision=revision+?4 WHERE server_id=?1 AND tool_name=?2",
                    params![source, name, seen, auto, reobserved],
                )?;
                continue;
            }
            let revision = previous.as_ref().map_or(1, |(_, revision, _)| revision + 1);
            let status = if quarantined {
                "quarantined"
            } else if denied {
                "denied"
            } else if auto {
                "approved"
            } else if let Some((model, _)) = model {
                model_status(&tx, model, &source, name, &digest, definition)?
            } else {
                "pending"
            };
            tx.execute(
                "INSERT OR REPLACE INTO tools VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 1)",
                params![source, name, digest, encoded, revision, status, seen],
            )?;
            tx.execute(
                "INSERT INTO history VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![source, name, digest, encoded, revision, status, seen],
            )?;
            let kind = if previous.is_some() {
                "definition_changed"
            } else {
                "definition_observed"
            };
            let mut detail = json!({"sha256":digest, "status":status, "revision":revision});
            if let Some((old, _, _)) = previous {
                let previous = crate::input::parse(old.as_bytes())?;
                let fields = previous
                    .as_object()
                    .unwrap()
                    .keys()
                    .chain(definition.as_object().unwrap().keys())
                    .filter(|key| previous.get(key.as_str()) != definition.get(key.as_str()))
                    .collect::<std::collections::BTreeSet<_>>();
                detail["changed_fields"] = json!(fields.into_iter().take(32).collect::<Vec<_>>());
            }
            event(&tx, kind, &source, Some(name), detail)?;
        }
        let mut removed = tx.prepare(
            "UPDATE tools SET status='revoked', revision=revision+1
             WHERE server_id=?1 AND present=0 AND status<>'revoked' RETURNING tool_name",
        )?;
        let names = removed
            .query_map([&source], |row| row.get::<_, String>(0))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        drop(removed);
        for name in names {
            event(&tx, "tool_removed", &source, Some(&name), json!({}))?;
        }
        event(
            &tx,
            "catalog_observed",
            &source,
            None,
            json!({"tools":definitions.len()}),
        )?;
        tx.commit()?;
        self.list(&json!({"server_id": source}))
    }

    pub fn heartbeat(&self, source: &str, session: &str) -> Result<()> {
        if self.0.execute(
            "UPDATE gateway_sessions SET heartbeat=?3 WHERE source=?1 AND session=?2",
            params![source, session, timestamp()],
        )? != 1
        {
            return Err(ReviewError("Gateway session is no longer active.").into());
        }
        Ok(())
    }

    pub fn catalog_check_failed(&mut self, source: &str) -> Result<()> {
        self.record_mcp_event("catalog_check_failed", source)
    }

    pub(crate) fn record_mcp_event(&mut self, kind: &str, source: &str) -> Result<()> {
        let tx = self.0.transaction()?;
        event(&tx, kind, source, None, json!({}))?;
        tx.commit()?;
        Ok(())
    }

    pub fn disconnect_gateway(&mut self, source: &str, session: &str) -> Result<()> {
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        if tx.execute(
            "DELETE FROM gateway_sessions WHERE source=?1 AND session=?2",
            params![source, session],
        )? == 1
        {
            event(&tx, "gateway_disconnected", source, None, json!({}))?;
        }
        tx.commit()?;
        Ok(())
    }

    pub fn gateway_tools(&self, source: &str, session: &str) -> Result<Vec<Value>> {
        let mut stmt = self.0.prepare(
            "SELECT t.definition,t.sha256 FROM tools t JOIN gateway_sessions s ON s.source=t.server_id
             WHERE t.server_id=?1 AND s.session=?2 AND present=1 AND status='approved'
             AND NOT EXISTS(SELECT 1 FROM gateway_routes r JOIN sentinel_stops x USING(server_id) WHERE r.route=t.server_id)
             AND NOT EXISTS(SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=t.server_id
                 AND b.tool_name=t.tool_name)
             AND NOT EXISTS(SELECT 1 FROM quarantines q WHERE q.server_id=t.server_id
                 AND q.tool_name=t.tool_name AND q.sha256=t.sha256) ORDER BY tool_name"
        )?;
        let records = stmt.query_map(params![source, session], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        let mut tools = Vec::new();
        for record in records {
            let (definition, digest) = record?;
            if hash(&definition) != digest {
                return Err(ReviewError("Stored definition failed its integrity check.").into());
            }
            tools.push(crate::input::parse(definition.as_bytes())?);
        }
        Ok(tools)
    }

    pub fn authorize<'a>(
        &'a mut self,
        source: &'a str,
        session: &str,
        name: &'a str,
        definition: &Value,
        artifact: Option<&str>,
    ) -> Result<Invocation<'a>> {
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        check_model_artifact(&tx, artifact)?;
        let digest = hash(&serde_json::to_string(definition)?);
        let stopped: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM gateway_routes r JOIN sentinel_stops x USING(server_id) WHERE r.route=?1)",
            [source], |row| row.get(0),
        )?;
        let revision: Option<i64> = tx
            .query_row(
                "SELECT t.revision FROM tools t JOIN gateway_sessions s ON s.source=t.server_id
             WHERE t.server_id=?1 AND s.session=?2 AND t.tool_name=?3 AND t.sha256=?4
             AND t.status='approved' AND t.present=1
             AND NOT EXISTS(SELECT 1 FROM blocked_tool_routes b WHERE b.server_id=t.server_id
                 AND b.tool_name=t.tool_name)
             AND NOT EXISTS(SELECT 1 FROM quarantines q WHERE q.server_id=t.server_id
                 AND q.tool_name=t.tool_name AND q.sha256=t.sha256)",
                params![source, session, name, digest],
                |row| row.get::<_, i64>(0),
            )
            .optional()?;
        let Some(revision) = revision.filter(|_| !stopped) else {
            let reason = if stopped {
                "server_stopped"
            } else if is_blocked(&tx, source, name)? {
                "tool_blocked"
            } else {
                "version_not_approved"
            };
            let id = record_denial(&tx, source, session, name, Some(&digest), reason)?;
            event(
                &tx,
                "gateway_call_blocked",
                source,
                Some(name),
                json!({"call_id":id,"reason":reason}),
            )?;
            tx.commit()?;
            return Err(ReviewError(reason).into());
        };
        tx.execute("INSERT INTO sentinel_calls(source,session,tool,sha256,revision,started_at,state) VALUES (?1,?2,?3,?4,?5,?6,'active')",
            params![source, session, name, digest, revision, timestamp()])?;
        let id = tx.last_insert_rowid();
        event(
            &tx,
            "call_authorized",
            source,
            Some(name),
            json!({"sha256":digest,"revision":revision,"call_id":id}),
        )?;
        tx.commit()?;
        Ok(Invocation {
            connection: &mut self.0,
            source,
            name,
            id,
        })
    }

    pub fn record_preflight_denial(
        &mut self,
        source: &str,
        session: &str,
        name: &str,
        reason: &str,
    ) -> Result<()> {
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let id = record_denial(&tx, source, session, name, None, reason)?;
        event(
            &tx,
            "gateway_call_blocked",
            source,
            Some(name),
            json!({"call_id":id,"reason":reason}),
        )?;
        tx.commit()?;
        Ok(())
    }

    pub fn expire_sentinel_history(&self) -> Result<()> {
        self.0.execute(
            "DELETE FROM sentinel_calls WHERE started_at < ?1",
            [(Utc::now() - chrono::Duration::days(30)).to_rfc3339()],
        )?;
        Ok(())
    }

    fn sentinel_calls(&self, request: &Value) -> Result<Value> {
        let before = request["before_id"].as_i64().unwrap_or(i64::MAX);
        let mut query = self.0.prepare(
            "SELECT c.id,c.source,c.session,c.tool,c.sha256,c.revision,c.started_at,c.ended_at,
              CASE WHEN c.state='active' AND NOT EXISTS(SELECT 1 FROM gateway_sessions g
                WHERE g.source=c.source AND g.session=c.session AND julianday(g.heartbeat)>julianday('now','-315 seconds'))
                THEN 'unconfirmed' ELSE c.state END,c.reason,
              (SELECT p.id FROM sentinel_calls p WHERE p.source=c.source AND p.tool=c.tool
                AND p.id<c.id AND p.state='completed' ORDER BY p.id DESC LIMIT 1),
              (SELECT p.sha256 FROM sentinel_calls p WHERE p.source=c.source AND p.tool=c.tool
                AND p.id<c.id AND p.state='completed' ORDER BY p.id DESC LIMIT 1)
             FROM sentinel_calls c WHERE c.id<?1 ORDER BY c.id DESC LIMIT 200",
        )?;
        let rows = query.query_map([before], |row| Ok(json!({
            "id":row.get::<_,i64>(0)?, "source":row.get::<_,String>(1)?, "session":row.get::<_,String>(2)?,
            "tool":row.get::<_,String>(3)?, "sha256":row.get::<_,Option<String>>(4)?,
            "revision":row.get::<_,Option<i64>>(5)?, "started_at":row.get::<_,String>(6)?,
            "ended_at":row.get::<_,Option<String>>(7)?, "state":row.get::<_,String>(8)?,
            "reason":row.get::<_,Option<String>>(9)?, "previous_success":row.get::<_,Option<i64>>(10)?,
            "previous_sha256":row.get::<_,Option<String>>(11)?,
        })))?.collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(json!(rows))
    }

    fn sentinel_stop(&mut self, request: &Value, stop: bool) -> Result<Value> {
        let source = text(request, "server_id", 1024)?;
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let server: String = tx
            .query_row(
                "SELECT server_id FROM gateway_routes WHERE route=?1",
                [source],
                |row| row.get(0),
            )
            .optional()?
            .ok_or(ReviewError("Choose an observed managed gateway route."))?;
        let sql = if stop {
            "INSERT OR IGNORE INTO sentinel_stops VALUES (?1)"
        } else {
            "DELETE FROM sentinel_stops WHERE server_id=?1"
        };
        if tx.execute(sql, [&server])? != 0 {
            event(
                &tx,
                if stop {
                    "server_stopped"
                } else {
                    "server_resumed"
                },
                source,
                None,
                json!({"server_id":server}),
            )?;
        }
        tx.commit()?;
        Ok(json!({"stopped":stop}))
    }

    fn decide(&mut self, action: &str, request: &Value) -> Result<Value> {
        let source = text(request, "server_id", 1024)?;
        let name = text(request, "tool_name", MAX_REVIEW_TOOL_NAME)?;
        let expected = text(request, "expected_sha256", 64)?;
        let revision = request["expected_revision"]
            .as_i64()
            .filter(|value| *value > 0)
            .ok_or(ReviewError("An exact current review revision is required."))?;
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: Option<(String, String)> = tx
            .query_row(
                "SELECT definition, status FROM tools WHERE server_id=?1 AND tool_name=?2
             AND sha256=?3 AND revision=?4 AND present=1",
                params![source, name, expected, revision],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()?;
        let (definition, old_status) =
            current.ok_or(ReviewError("Review is stale. Reload the tool."))?;
        if action == "approve" && is_blocked(&tx, source, name)? {
            return Err(ReviewError("Unblock the tool before approving a version.").into());
        }
        let quarantined: bool = tx.query_row(
            "SELECT EXISTS(SELECT 1 FROM quarantines WHERE server_id=?1 AND tool_name=?2 AND sha256=?3)",
            params![source, name, expected], |row| row.get(0))?;
        let status = match action {
            "approve" if !quarantined && old_status != "quarantined" => {
                tx.execute(
                    "INSERT OR REPLACE INTO baselines VALUES (?1, ?2, ?3)",
                    params![source, name, definition],
                )?;
                "approved"
            }
            "approve" => return Err(ReviewError("Release quarantine before approval.").into()),
            "deny" => "denied",
            "quarantine" => {
                tx.execute(
                    "INSERT OR IGNORE INTO quarantines VALUES (?1, ?2, ?3)",
                    params![source, name, expected],
                )?;
                "quarantined"
            }
            "release_quarantine" if quarantined => {
                tx.execute(
                    "DELETE FROM quarantines WHERE server_id=?1 AND tool_name=?2 AND sha256=?3",
                    params![source, name, expected],
                )?;
                "pending"
            }
            _ => return Err(ReviewError("This definition is not quarantined.").into()),
        };
        tx.execute(
            "UPDATE tools SET status=?3, revision=revision+1 WHERE server_id=?1 AND tool_name=?2",
            params![source, name, status],
        )?;
        let kind = if action == "release_quarantine" {
            "tool_release_quarantine".into()
        } else {
            format!("tool_{status}")
        };
        if source.starts_with("gateway:") {
            let override_status = if action == "deny" {
                "denied"
            } else {
                "pending"
            };
            tx.execute(
                "INSERT OR REPLACE INTO model_overrides VALUES(?1,?2,?3,?4)",
                params![source, name, expected, override_status],
            )?;
        }
        event(&tx, &kind, source, Some(name), json!({"sha256": expected}))?;
        tx.commit()?;
        self.review(source, name)
    }

    fn activity(&self, tool: Option<(&str, &str)>) -> Result<Value> {
        const COLUMNS: &str = "SELECT id, kind, source, tool, timestamp, detail FROM events";
        let rows = if let Some((source, name)) = tool {
            self.0
                .prepare(&format!(
                    "{COLUMNS} WHERE source=?1 AND tool=?2 ORDER BY id DESC LIMIT 200"
                ))?
                .query_map(params![source, name], event_record)?
                .collect::<rusqlite::Result<Vec<_>>>()?
        } else {
            self.0
                .prepare(&format!("{COLUMNS} ORDER BY id DESC LIMIT 200"))?
                .query_map([], event_record)?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        Ok(json!(rows))
    }

    fn alerts(&mut self, through: Option<i64>) -> Result<Value> {
        let tx = self
            .0
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut cursor: i64 =
            tx.query_row("SELECT cursor FROM alerts WHERE id=1", [], |row| row.get(0))?;
        if let Some(through) = through {
            let exists: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM events WHERE id=?1 AND kind IN ('definition_changed','mcp_added'))",
                [through],
                |row| row.get(0),
            )?;
            if !exists {
                return Err(ReviewError("Unknown definition alert.").into());
            }
            cursor = cursor.max(through);
            tx.execute("UPDATE alerts SET cursor=?1 WHERE id=1", [cursor])?;
        }
        let unread: u64 = tx.query_row(
            "SELECT COUNT(*) FROM events WHERE kind='definition_changed' AND id>?1",
            [cursor],
            |row| row.get(0),
        )?;
        let latest = tx.query_row(
            "SELECT id, kind, source, tool, timestamp, detail FROM events WHERE kind='definition_changed'
             AND id>?1 ORDER BY id DESC LIMIT 1", [cursor], event_record).optional()?;
        let new_mcp = tx
            .query_row(
                "SELECT id,kind,source,tool,timestamp,detail FROM events WHERE kind='mcp_added'
             AND id>?1 ORDER BY id DESC LIMIT 1",
                [cursor],
                event_record,
            )
            .optional()?;
        let new_mcp_count: u64 = tx.query_row(
            "SELECT COUNT(*) FROM events WHERE kind='mcp_added' AND id>?1",
            [cursor],
            |row| row.get(0),
        )?;
        let catalog_revision: i64 = tx.query_row(
            "SELECT COALESCE(MAX(id),0) FROM events WHERE kind IN ('definition_observed','definition_changed','mcp_added')",
            [], |row| row.get(0),
        )?;
        tx.commit()?;
        Ok(
            json!({"unread":unread, "latest":latest, "catalog_revision":catalog_revision,
            "new_mcp":new_mcp,"new_mcp_count":new_mcp_count}),
        )
    }
}

fn is_blocked(db: &Connection, source: &str, name: &str) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM blocked_tool_routes WHERE server_id=?1 AND tool_name=?2)",
        params![source, name],
        |row| row.get(0),
    )?)
}

fn read_approval_mode(db: &Connection) -> Result<ApprovalMode> {
    let saved: Option<String> = db
        .query_row("SELECT mode FROM approval_policy WHERE id=1", [], |row| {
            row.get(0)
        })
        .optional()?;
    Ok(saved
        .map(|mode| serde_json::from_value(json!(mode)))
        .transpose()?
        .unwrap_or_default())
}

fn read_model_artifact(db: &Connection) -> Result<Option<String>> {
    Ok(db
        .query_row(
            "SELECT artifact FROM decision_model WHERE id=1",
            [],
            |row| row.get(0),
        )
        .optional()?)
}

fn check_model_artifact(db: &Connection, expected: Option<&str>) -> Result<()> {
    if read_model_artifact(db)?.as_deref() != expected {
        return Err(ReviewError("The decision model changed. Reconnect the gateway.").into());
    }
    Ok(())
}

fn model_status(
    tx: &Transaction<'_>,
    model: &DecisionModel,
    source: &str,
    name: &str,
    digest: &str,
    definition: &Value,
) -> Result<&'static str> {
    if is_blocked(tx, source, name)? {
        return Ok("pending");
    }
    let owner: Option<String> = tx.query_row(
        "SELECT decision FROM model_overrides WHERE server_id=?1 AND tool_name=?2 AND sha256=?3",
        params![source,name,digest], |row| row.get(0),
    ).optional()?;
    if let Some(owner) = owner {
        return Ok(if owner == "denied" {
            "denied"
        } else {
            "pending"
        });
    }
    let baseline: Option<String> = tx
        .query_row(
            "SELECT definition FROM baselines WHERE server_id=?1 AND tool_name=?2",
            params![source, name],
            |row| row.get(0),
        )
        .optional()?;
    let Some(baseline) = baseline else {
        return Ok("pending");
    };
    let baseline = crate::input::parse(baseline.as_bytes())?;
    let assessment = model.assess(&baseline, definition);
    let action = assessment.action;
    tx.execute(
        "INSERT OR REPLACE INTO model_decisions VALUES(?1,?2,?3,?4)",
        params![source, name, digest, assessment.evidence.to_string()],
    )?;
    if action == "quarantined" {
        tx.execute(
            "INSERT OR IGNORE INTO quarantines VALUES(?1,?2,?3)",
            params![source, name, digest],
        )?;
    }
    event(
        tx,
        "model_decision",
        source,
        Some(name),
        json!({"sha256":digest,"assessment":assessment.evidence}),
    )?;
    Ok(action)
}

fn event_record(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
    let detail: String = row.get(5)?;
    let parsed: Value = serde_json::from_str(&detail).map_err(|error| {
        rusqlite::Error::FromSqlConversionFailure(5, rusqlite::types::Type::Text, Box::new(error))
    })?;
    Ok(
        json!({"id":row.get::<_,i64>(0)?, "event":row.get::<_,String>(1)?,
        "server_id":row.get::<_,String>(2)?, "tool_name":row.get::<_,Option<String>>(3)?,
        "timestamp":row.get::<_,String>(4)?, "detail":parsed}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_definition_is_a_baseline_and_only_new_servers_are_announced() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&dir.path().join("review.sqlite"))?;
        let first = definition("Read a note.");
        store.request(&import(vec![first.clone()]))?;
        let review = store.review("import:notes", "read_note")?;
        assert_eq!(review["old_tool"], first);
        assert_eq!(review["baseline_kind"], "observed");
        assert_eq!(review["status"], "pending");
        let snapshot = store.request(&json!({"action":"definition_alerts"}))?;
        assert_eq!(snapshot["new_mcp"]["server_id"], "import:notes");
        store.request(
            &json!({"action":"dismiss_definition_alerts","through_id":snapshot["new_mcp"]["id"]}),
        )?;
        store.request(&import(vec![definition("Read one local note.")]))?;
        let alerts = store.request(&json!({"action":"definition_alerts"}))?;
        assert!(alerts["new_mcp"].is_null());
        assert!(alerts["catalog_revision"].as_i64() > snapshot["catalog_revision"].as_i64());
        assert_eq!(
            store.review("import:notes", "read_note")?["old_tool"],
            first
        );
        assert_eq!(
            store.history("import:notes", "read_note")?[0]["status"],
            "observed_reference"
        );
        Ok(())
    }

    #[test]
    fn sentinel_records_dispatch_and_applies_server_stop_to_future_routes() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("review.sqlite");
        let mut store = ReviewStore::open(&path)?;
        let source = "gateway:codex:notes";
        let tool = definition("Read a note.");
        store.observe_gateway(
            source,
            "fixture",
            std::slice::from_ref(&tool),
            "session-one",
            true,
            None,
        )?;
        let version = store.review(source, "read_note")?;
        store.request(
            &json!({"action":"approve","server_id":source,"tool_name":"read_note",
            "expected_sha256":version["sha256"],"expected_revision":version["revision"]}),
        )?;
        let permit = store.authorize(source, "session-one", "read_note", &tool, None)?;
        let mut other = ReviewStore::open(&path)?;
        assert_eq!(
            other.request(&json!({"action":"sentinel_calls"}))?[0]["state"],
            "active"
        );
        other.request(&json!({"action":"sentinel_stop","server_id":source}))?;
        permit.finish(true)?;
        let route = "gateway:cursor:notes";
        other.observe_gateway(
            route,
            "fixture",
            std::slice::from_ref(&tool),
            "session-two",
            true,
            None,
        )?;
        assert!(other.gateway_tools(route, "session-two")?.is_empty());
        assert!(other
            .authorize(route, "session-two", "read_note", &tool, None)
            .is_err());
        let events = other.request(&json!({"action":"sentinel_calls"}))?;
        assert_eq!(events[0]["reason"], "server_stopped");
        assert_eq!(events[1]["state"], "completed");
        assert_eq!(events[1]["sha256"], version["sha256"]);
        let activity = other.request(&json!({"action":"mcp_activity","include_checks":false}))?;
        let rows = activity.as_array().unwrap();
        assert_eq!(rows[0]["event"], "gateway_call_blocked");
        assert!(rows.iter().any(|row| row["event"] == "call_completed"));
        assert!(rows.iter().all(|row| row["event"] != "catalog_observed"));
        let older = other.request(&json!({"action":"mcp_activity","before_id":rows[0]["id"]}))?;
        assert!(older
            .as_array()
            .unwrap()
            .iter()
            .any(|row| row["event"] == "catalog_observed"));
        assert!(older
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["id"].as_i64() < rows[0]["id"].as_i64()));
        let graph = other.request(&json!({"action":"connection_graph"}))?;
        assert!(graph[0]["last_checked"].is_string());
        Ok(())
    }

    #[test]
    fn auto_approval_preserves_manual_decisions_and_rechecks_definition_drift() -> Result<()> {
        let folder = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&folder.path().join("review.sqlite"))?;
        let source = "gateway:codex:notes";
        let mut read = definition("Read a note.");
        read["annotations"] = json!({"readOnlyHint":true});
        let mut changed = read.clone();
        changed["description"] = json!("Read an updated note.");
        let write = json!({"name":"write_note","description":"Write a note.", "inputSchema":{"type":"object"}});
        store.observe_gateway(
            source,
            "binding",
            &[read.clone(), write.clone()],
            "one",
            true,
            None,
        )?;
        assert_eq!(store.gateway_tools(source, "one")?, vec![read.clone()]);
        let tool = store.review(source, "read_note")?;
        store.request(
            &json!({"action":"quarantine","server_id":source,"tool_name":"read_note",
            "expected_sha256":tool["sha256"],"expected_revision":tool["revision"]}),
        )?;
        store.request(&json!({"action":"set_approval_mode","mode":"all_first_seen"}))?;
        store.observe_gateway(
            source,
            "binding",
            &[read.clone(), write.clone()],
            "one",
            false,
            None,
        )?;
        assert_eq!(store.gateway_tools(source, "one")?, vec![write.clone()]);
        store.observe_gateway(
            source,
            "binding",
            &[changed, write.clone()],
            "one",
            false,
            None,
        )?;
        assert_eq!(store.gateway_tools(source, "one")?, vec![write]);
        Ok(())
    }

    #[test]
    fn existing_gateway_session_survives_schema_upgrade() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("legacy.sqlite");
        let db = Connection::open(&path)?;
        db.execute_batch(
            "CREATE TABLE sources(server_id TEXT PRIMARY KEY, identity TEXT NOT NULL);
             CREATE TABLE gateway_sessions(source TEXT PRIMARY KEY REFERENCES sources(server_id),
                 session TEXT NOT NULL, heartbeat TEXT NOT NULL);
             INSERT INTO sources VALUES ('gateway:codex:notes','binding');
             INSERT INTO gateway_sessions VALUES ('gateway:codex:notes','legacy','2000-01-01T00:00:00Z');",
        )?;
        drop(db);
        let store = ReviewStore::open(&path)?;
        store.heartbeat("gateway:codex:notes", "legacy")?;
        ReviewStore::open(&path)?.heartbeat("gateway:codex:notes", "legacy")?;
        Ok(())
    }

    #[test]
    fn gateway_approval_can_be_saved_offline_and_shared_by_concurrent_sessions() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&dir.path().join("review.sqlite"))?;
        let source = "gateway:codex:notes";
        let original = definition("Read a note.");
        let catalog = std::slice::from_ref(&original);
        store.observe_gateway(source, "binding", catalog, "first", true, None)?;
        store.disconnect_gateway(source, "first")?;
        let observed = store.review(source, "read_note")?;
        let approved = store.request(
            &json!({"action":"approve","server_id":source,"tool_name":"read_note",
            "expected_sha256":observed["sha256"],"expected_revision":observed["revision"]}),
        )?;
        assert_eq!(approved["status"], "approved");
        assert!(store.gateway_tools(source, "first")?.is_empty());
        store.observe_gateway(source, "binding", catalog, "second", true, None)?;
        store.observe_gateway(source, "binding", catalog, "third", true, None)?;
        store
            .authorize(source, "second", "read_note", &original, None)?
            .finish(true)?;
        store
            .authorize(source, "third", "read_note", &original, None)?
            .finish(true)?;
        let graph = store.connection_graph()?;
        assert_eq!(graph[0]["tools"].as_array().unwrap().len(), 1);
        let overview = store.overview()?;
        assert_eq!(overview["gateway_health"][0]["sessions"], 2);

        store.disconnect_gateway(source, "third")?;
        store.heartbeat(source, "second")?;
        assert_eq!(store.gateway_tools(source, "second")?.len(), 1);
        let changed = definition("Read a changed note.");
        store.observe_gateway(source, "binding", &[changed], "second", false, None)?;
        assert!(store.gateway_tools(source, "second")?.is_empty());
        store.observe_gateway(source, "other binding", catalog, "fourth", true, None)?;
        assert!(store.heartbeat(source, "second").is_err());
        assert!(store
            .observe_gateway(source, "binding", catalog, "second", false, None)
            .is_err());
        assert!(store.gateway_tools(source, "fourth")?.is_empty());
        Ok(())
    }

    #[test]
    fn monitoring_settings_are_validated_and_shared_with_gateways() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let path = dir.path().join("review.sqlite");
        let mut desktop = ReviewStore::open(&path)?;
        let gateway = ReviewStore::open(&path)?;
        assert_eq!(
            gateway.monitoring_settings()?,
            MonitoringSettings::default()
        );
        let settings = MonitoringSettings {
            active_seconds: 6,
            active_window_seconds: 60,
            idle_seconds: 30,
            discovery_enabled: false,
            ..MonitoringSettings::default()
        };
        desktop.request(&json!({"action":"set_monitoring_settings","settings":settings}))?;
        assert_eq!(gateway.monitoring_settings()?, settings);
        let invalid = MonitoringSettings {
            idle_seconds: 5,
            ..settings
        };
        assert!(desktop
            .request(&json!({"action":"set_monitoring_settings","settings":invalid}))
            .is_err());
        assert_eq!(gateway.monitoring_settings()?, settings);
        Ok(())
    }

    #[test]
    fn hosted_gateway_inherits_a_catalog_denial() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&directory.path().join("review.sqlite"))?;
        let tool = json!({"name":"alpaca.get_calendar","inputSchema":{"type":"object"}});
        let name = "alpaca.get_calendar";
        store.observe_catalog(
            CODEX_APPS.to_owned(),
            "catalog",
            std::slice::from_ref(&tool),
        )?;
        let review = store.review(CODEX_APPS, name)?;
        store.request(
            &json!({"action":"deny","server_id":CODEX_APPS,"tool_name":name,
            "expected_sha256":review["sha256"],"expected_revision":review["revision"]}),
        )?;
        let source = "gateway:codex:codex-hosted";
        store.request(&json!({"action":"set_approval_mode","mode":"all_first_seen"}))?;
        store.observe_gateway(
            source,
            "fixture",
            std::slice::from_ref(&tool),
            "test",
            true,
            None,
        )?;
        assert_eq!(store.review(source, name)?["status"], "denied");
        assert!(store.authorize(source, "test", name, &tool, None).is_err());
        Ok(())
    }

    #[test]
    fn codex_connector_groups_keep_original_review_identity() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("review.sqlite");
        let source = "harness:codex:codex_apps";
        let github = json!({"name":"github.read_issue","inputSchema":{"type":"object"},
            "_meta":{"connector_name":"GitHub","connector_id":"internal-github"}});
        let canva = json!({"name":"canva.read_design","inputSchema":{"type":"object"},
            "_meta":{"connector_name":"Canva","connector_id":"internal-canva"}});
        let mut store = ReviewStore::open(&path)?;
        store.observe_catalog(source.into(), "fixture", &[github, canva])?;
        drop(store);
        let mut store = ReviewStore::open(&path)?;
        let tools = store.request(&json!({"action":"list_tools","summary":true}))?;
        assert_eq!(
            tools[0]["connection"],
            json!({"id":"canva","label":"Canva"})
        );
        assert_eq!(
            tools[1]["connection"],
            json!({"id":"github","label":"GitHub"})
        );
        assert_eq!(tools[1]["server_id"], source);
        let graph = store.request(&json!({"action":"connection_graph"}))?;
        assert_eq!(graph[0]["tools"][1]["connection"], tools[1]["connection"]);
        let review = store.request(
            &json!({"action":"review","server_id":source,"tool_name":"github.read_issue"}),
        )?;
        assert_eq!(review["sha256"], tools[1]["sha256"]);
        assert_eq!(review["connection"], tools[1]["connection"]);
        Ok(())
    }

    #[test]
    fn connection_graph_uses_observed_routes_and_current_enforcement() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("review.sqlite");
        let mut store = ReviewStore::open(&path)?;
        assert_eq!(
            store.request(&json!({"action":"connection_graph"}))?,
            json!([])
        );
        let codex = "gateway:codex:notes";
        let cursor = "gateway:cursor:notes";
        let first = definition("Read a note.");
        let mut removed = first.clone();
        removed["name"] = json!("removed_note");
        store.observe_gateway(
            codex,
            "fixture",
            &[first.clone(), removed],
            "one",
            true,
            None,
        )?;
        store.observe_gateway(
            cursor,
            "fixture",
            std::slice::from_ref(&first),
            "two",
            true,
            None,
        )?;
        store.request(&import(vec![first]))?;
        store.observe_gateway(
            codex,
            "fixture",
            &[definition("Read one note.")],
            "one",
            false,
            None,
        )?;
        store.request(
            &json!({"action":"block_tool_all","server_id":codex,"tool_name":"read_note"}),
        )?;
        store.0.execute(
            "UPDATE gateway_sessions SET heartbeat='2000-01-01T00:00:00Z' WHERE source=?1",
            [cursor],
        )?;
        drop(store);
        let graph = ReviewStore::open(&path)?.request(&json!({"action":"connection_graph"}))?;
        assert_eq!(graph.as_array().unwrap().len(), 3);
        assert_eq!(graph[0]["source_id"], codex);
        assert_eq!(graph[0]["server_id"], "notes");
        assert_eq!(graph[0]["client_id"], "codex");
        assert_eq!(graph[0]["client_label"], "Codex");
        assert_eq!(graph[0]["active"], true);
        assert_eq!(graph[0]["tools"].as_array().unwrap().len(), 1);
        assert_eq!(graph[0]["tools"][0]["tool_name"], "read_note");
        assert_eq!(graph[0]["tools"][0]["status"], "blocked");
        assert_eq!(graph[0]["tools"][0]["version_count"], 2);
        assert_eq!(graph[1]["active"], false);
        assert_eq!(graph[1]["tools"][0]["status"], "blocked");
        assert_eq!(graph[2]["kind"], "review");
        assert!(graph[2]["client_id"].is_null());
        assert_eq!(graph[2]["tools"][0]["status"], "pending");
        assert!(graph[0]["tools"][0].get("definition").is_none());
        Ok(())
    }

    #[test]
    fn tool_activity_filters_before_the_global_limit() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&directory.path().join("review.sqlite"))?;
        let codex = "gateway:codex:notes";
        let cursor = "gateway:cursor:notes";
        let tx = store.0.transaction()?;
        event(&tx, "call_completed", codex, Some("read_note"), json!({}))?;
        for _ in 0..201 {
            event(&tx, "call_completed", cursor, Some("read_note"), json!({}))?;
        }
        tx.commit()?;
        assert!(store
            .request(&json!({"action":"activity"}))?
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["server_id"] == cursor));
        let scoped = store.request(
            &json!({"action":"tool_activity","server_id":codex,"tool_name":"read_note"}),
        )?;
        assert_eq!(scoped.as_array().unwrap().len(), 1);
        assert_eq!(scoped[0]["server_id"], codex);
        assert_eq!(scoped[0]["event"], "call_completed");
        Ok(())
    }

    #[test]
    fn shared_blocks_cover_other_harnesses_and_future_routes() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&directory.path().join("review.sqlite"))?;
        let tools = [definition("Read a note.")];
        let codex = "gateway:codex:notes";
        let cursor = "gateway:cursor:notes";
        let other = "gateway:codex:other";
        let future = "gateway:claude:notes";
        for route in [codex, cursor, other] {
            store.observe_gateway(route, "fixture", &tools, route, true, None)?;
            let row = store.review(route, "read_note")?;
            store.request(
                &json!({"action":"approve","server_id":route,"tool_name":"read_note",
                "expected_sha256":row["sha256"],"expected_revision":row["revision"]}),
            )?;
        }
        store
            .request(&json!({"action":"block_tool","server_id":cursor,"tool_name":"read_note"}))?;
        store.request(
            &json!({"action":"block_tool_all","server_id":codex,"tool_name":"read_note"}),
        )?;
        store.observe_gateway(future, "fixture", &tools, future, true, None)?;
        for route in [codex, cursor, future] {
            assert_eq!(store.review(route, "read_note")?["blocked"], true);
            assert!(store.gateway_tools(route, route)?.is_empty());
            assert!(store
                .authorize(route, route, "read_note", &tools[0], None)
                .is_err());
        }
        assert_eq!(store.gateway_tools(other, other)?.len(), 1);
        store.request(
            &json!({"action":"unblock_tool_all","server_id":future,"tool_name":"read_note"}),
        )?;
        assert_eq!(store.review(cursor, "read_note")?["blocked"], true);
        assert_eq!(store.review(codex, "read_note")?["blocked"], false);
        assert!(store.gateway_tools(codex, codex)?.is_empty());
        Ok(())
    }

    fn definition(description: &str) -> Value {
        json!({
            "name": "read_note",
            "description": description,
            "inputSchema": {"type": "object"}
        })
    }

    fn import(tools: Vec<Value>) -> Value {
        json!({"action": "import_definitions", "server_id": "notes",
               "identity": "fixture", "tools": tools})
    }

    fn decision(action: &str, version: &Value) -> Value {
        json!({"action": action, "server_id": "import:notes", "tool_name": "read_note",
               "expected_sha256": version["sha256"], "expected_revision": version["revision"]})
    }

    #[test]
    fn review_release_and_alert_cursor_survive_reopen() -> Result<()> {
        let path = std::env::temp_dir().join(format!(
            "driftguard-review-{}-{}.sqlite",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ));
        let result = (|| {
            let mut store = ReviewStore::open(&path)?;
            let initial = store.request(&import(vec![definition("Read a note.")]))?;
            let initial = &initial[0];
            let quarantine = store.request(&decision("quarantine", initial))?;
            assert!(store
                .request(&decision("release_quarantine", initial))
                .is_err());
            assert!(store.request(&decision("approve", &quarantine)).is_err());
            let release = store.request(&decision("release_quarantine", &quarantine))?;
            assert_eq!(release["status"], "pending");
            let approved = store.request(&decision("approve", &release))?;
            assert_eq!(approved["status"], "approved");

            store.request(&import(vec![definition("Read one note.")]))?;
            store.request(&import(vec![definition("Read one note.")]))?;
            let alerts = store.request(&json!({"action": "definition_alerts"}))?;
            assert_eq!(alerts["unread"], 1);
            assert_eq!(
                alerts["latest"]["detail"]["changed_fields"],
                json!(["description"])
            );
            store.request(&import(vec![definition("Read one local note.")]))?;
            drop(store);

            let mut store = ReviewStore::open(&path)?;
            let remaining = store.request(&json!({
                "action": "dismiss_definition_alerts", "through_id": alerts["latest"]["id"]
            }))?;
            assert_eq!(remaining["unread"], 1);
            let history = store.request(&json!({
                "action": "history", "server_id": "import:notes", "tool_name": "read_note"
            }))?;
            assert_eq!(history.as_array().unwrap().len(), 3);
            assert_eq!(history[0]["status"], "approved_reference");
            assert_eq!(history[2]["description"], "Read one local note.");
            Ok(())
        })();
        std::fs::remove_file(path)?;
        result
    }

    #[test]
    fn reappearing_revoked_tool_keeps_quarantine_and_denial_status() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let mut store = ReviewStore::open(&directory.path().join("review.sqlite"))?;
        let initial = store.request(&import(vec![definition("Read a note.")]))?;
        store.request(&decision("quarantine", &initial[0]))?;
        store.request(&import(vec![]))?;
        assert_eq!(
            store.review("import:notes", "read_note")?["status"],
            "revoked"
        );
        store.request(&import(vec![definition("Read a note.")]))?;
        assert_eq!(
            store.review("import:notes", "read_note")?["status"],
            "quarantined"
        );

        let source = "gateway:codex:notes";
        let tool = definition("Read a note.");
        store.observe_gateway(
            source,
            "fixture",
            std::slice::from_ref(&tool),
            "one",
            true,
            None,
        )?;
        let version = store.review(source, "read_note")?;
        store.request(
            &json!({"action":"deny","server_id":source,"tool_name":"read_note",
            "expected_sha256":version["sha256"],"expected_revision":version["revision"]}),
        )?;
        store.observe_gateway(source, "fixture", &[], "one", false, None)?;
        store.observe_gateway(
            source,
            "fixture",
            std::slice::from_ref(&tool),
            "one",
            false,
            None,
        )?;
        assert_eq!(store.review(source, "read_note")?["status"], "denied");
        Ok(())
    }

    #[cfg(unix)]
    #[test]
    fn open_rejects_non_regular_database_paths() -> Result<()> {
        let directory = tempfile::tempdir()?;
        let fifo = directory.path().join("fifo.sqlite");
        let encoded = std::ffi::CString::new(fifo.as_os_str().as_encoded_bytes())?;
        // The path is NUL terminated and valid for the duration of the call.
        assert_eq!(unsafe { libc::mkfifo(encoded.as_ptr(), 0o600) }, 0);
        assert!(ReviewStore::open(&fifo).is_err());
        assert!(ReviewStore::open(directory.path()).is_err());
        let target = directory.path().join("target.sqlite");
        ReviewStore::open(&target)?;
        let link = directory.path().join("link.sqlite");
        std::os::unix::fs::symlink(&target, &link)?;
        assert!(ReviewStore::open(&link).is_err());
        Ok(())
    }

    #[test]
    fn invalid_catalog_rolls_back_partial_observations() -> Result<()> {
        let connection = Connection::open_in_memory()?;
        connection.execute_batch(include_str!("schema.sql"))?;
        let mut store = ReviewStore(connection);
        store.request(&import(vec![definition("Read a note.")]))?;
        let changed = definition("Read one note.");
        assert!(store
            .request(&import(vec![changed.clone(), changed]))
            .is_err());
        let tools = store.request(&json!({"action": "list_tools", "summary": true}))?;
        assert_eq!(tools[0]["description"], "Read a note.");
        let alerts = store.request(&json!({"action": "definition_alerts"}))?;
        assert_eq!(alerts["unread"], 0);
        Ok(())
    }
}
