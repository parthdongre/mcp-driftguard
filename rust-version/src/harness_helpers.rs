use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use chrono::Utc;
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use toml_edit::DocumentMut;

use crate::harness::{home, read_text};
use crate::review::{ReviewError, ReviewStore};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
type Inventory = BTreeMap<String, Helper>;
const MAX_FILE: u64 = 1024 * 1024;
const MAX_ENTRIES: usize = 512;

#[derive(Clone, Deserialize, PartialEq, Serialize)]
struct Helper {
    harness: String,
    kind: String,
    name: String,
    location: String,
    sha256: String,
    enabled: Option<bool>,
}

#[derive(Clone, Copy)]
enum Source {
    Skills,
    Markdown,
    Instruction,
    CodexSettings,
    ClaudeSettings,
    Hooks,
}

struct Scope<'a> {
    harness: &'static str,
    kind: &'static str,
    location: &'a str,
    path: PathBuf,
    source: Source,
}

impl Scope<'_> {
    fn read(&self) -> Result<Inventory> {
        match self.source {
            Source::Skills | Source::Markdown => self.read_directory(),
            _ => self.read_file(),
        }
    }

    fn helper(
        &self,
        kind: &'static str,
        name: &str,
        location: String,
        text: &str,
        enabled: Option<bool>,
    ) -> Helper {
        Helper {
            harness: self.harness.to_owned(),
            kind: kind.to_owned(),
            name: name.to_owned(),
            location,
            sha256: format!("{:x}", Sha256::digest(text.as_bytes())),
            enabled,
        }
    }

    fn read_directory(&self) -> Result<Inventory> {
        let directory = match fs::symlink_metadata(&self.path) {
            Ok(meta) if meta.is_dir() => fs::read_dir(&self.path)?,
            Ok(_) => return Err(ReviewError("Expected a regular helper directory.").into()),
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Inventory::new()),
            Err(error) => return Err(error.into()),
        };
        let mut helpers = Inventory::new();
        for (index, entry) in directory.enumerate() {
            if index >= MAX_ENTRIES {
                return Err(ReviewError("The helper directory exceeds the scan limit.").into());
            }
            let entry = entry?;
            let file = entry.file_type()?;
            let name = entry.file_name();
            let Some(name) = name
                .to_str()
                .filter(|name| !name.chars().any(char::is_control))
            else {
                continue;
            };
            let (path, location) = match self.source {
                Source::Skills if file.is_dir() => (
                    entry.path().join("SKILL.md"),
                    format!("{}/{name}/SKILL.md", self.location),
                ),
                Source::Markdown if file.is_file() && name.ends_with(".md") => {
                    (entry.path(), format!("{}/{name}", self.location))
                }
                _ => continue,
            };
            if let Some(text) = read_text(&path, MAX_FILE)? {
                let label = if matches!(self.source, Source::Markdown) {
                    name.trim_end_matches(".md")
                } else {
                    name
                };
                helpers.insert(
                    name.to_owned(),
                    self.helper(self.kind, label, location, &text, None),
                );
            }
        }
        Ok(helpers)
    }

    fn read_file(&self) -> Result<Inventory> {
        let Some(text) = read_text(&self.path, MAX_FILE)? else {
            return Ok(Inventory::new());
        };
        let mut helpers = Inventory::new();
        let mut add = |kind: &'static str, name: &str, value: &str, enabled| {
            if !name.is_empty() && name.len() <= 256 && !name.chars().any(char::is_control) {
                helpers.insert(
                    format!("{kind}:{name}"),
                    self.helper(kind, name, self.location.to_owned(), value, enabled),
                );
            }
        };
        match self.source {
            Source::Instruction => add(
                self.kind,
                self.location.rsplit('/').next().unwrap_or(self.location),
                &text,
                None,
            ),
            Source::CodexSettings => {
                let document = text.trim_start_matches('\u{feff}').parse::<DocumentMut>()?;
                if let Some(plugins) = document.get("plugins") {
                    for (name, value) in plugins
                        .as_table_like()
                        .ok_or(ReviewError("Expected a plugin table."))?
                        .iter()
                    {
                        let enabled = value
                            .as_table_like()
                            .and_then(|entry| entry.get("enabled"))
                            .and_then(toml_edit::Item::as_bool);
                        add("plugin", name, &value.to_string(), enabled);
                    }
                }
                for key in ["sandbox_mode", "approval_policy", "sandbox_workspace_write"] {
                    if let Some(value) = document.get(key) {
                        add("permission", key, &value.to_string(), None);
                    }
                }
            }
            Source::ClaudeSettings | Source::Hooks => {
                let document = crate::input::parse(text.trim_start_matches('\u{feff}').as_bytes())?;
                if !document.is_object() {
                    return Err(ReviewError("Expected a settings object.").into());
                }
                for (field, kind) in [
                    ("hooks", "hook"),
                    ("enabledPlugins", "plugin"),
                    ("permissions", "permission"),
                ] {
                    if let Some(value) = document.get(field) {
                        for (name, value) in value
                            .as_object()
                            .ok_or(ReviewError("Expected a settings section."))?
                        {
                            let enabled = (kind == "plugin").then(|| value.as_bool()).flatten();
                            add(kind, name, &value.to_string(), enabled);
                        }
                    }
                }
            }
            _ => unreachable!(),
        }
        if helpers.len() > MAX_ENTRIES {
            return Err(ReviewError("The helper file exceeds the scan limit.").into());
        }
        Ok(helpers)
    }
}

pub fn scan(path: &Path) -> Result<Value> {
    let (home, isolated) = home()?;
    let base = |variable: &str, default: &str| {
        (!isolated)
            .then(|| std::env::var_os(variable))
            .flatten()
            .map(PathBuf::from)
            .filter(|path| path.is_absolute())
            .unwrap_or_else(|| home.join(default))
    };
    let codex = base("CODEX_HOME", ".codex");
    let claude = base("CLAUDE_CONFIG_DIR", ".claude");
    let scopes = [
        (
            "Codex",
            "skill",
            "~/.agents/skills",
            home.join(".agents/skills"),
            Source::Skills,
        ),
        (
            "Codex",
            "skill",
            "$CODEX_HOME/skills",
            codex.join("skills"),
            Source::Skills,
        ),
        (
            "Codex",
            "instruction",
            "$CODEX_HOME/AGENTS.md",
            codex.join("AGENTS.md"),
            Source::Instruction,
        ),
        (
            "Codex",
            "instruction",
            "$CODEX_HOME/AGENTS.override.md",
            codex.join("AGENTS.override.md"),
            Source::Instruction,
        ),
        (
            "Codex",
            "settings",
            "$CODEX_HOME/config.toml",
            codex.join("config.toml"),
            Source::CodexSettings,
        ),
        (
            "Codex",
            "hook",
            "$CODEX_HOME/hooks.json",
            codex.join("hooks.json"),
            Source::Hooks,
        ),
        (
            "Claude Code",
            "skill",
            "$CLAUDE_CONFIG_DIR/skills",
            claude.join("skills"),
            Source::Skills,
        ),
        (
            "Claude Code",
            "subagent",
            "$CLAUDE_CONFIG_DIR/agents",
            claude.join("agents"),
            Source::Markdown,
        ),
        (
            "Claude Code",
            "command",
            "$CLAUDE_CONFIG_DIR/commands",
            claude.join("commands"),
            Source::Markdown,
        ),
        (
            "Claude Code",
            "instruction",
            "$CLAUDE_CONFIG_DIR/CLAUDE.md",
            claude.join("CLAUDE.md"),
            Source::Instruction,
        ),
        (
            "Claude Code",
            "settings",
            "$CLAUDE_CONFIG_DIR/settings.json",
            claude.join("settings.json"),
            Source::ClaudeSettings,
        ),
    ]
    .map(|(harness, kind, location, path, source)| Scope {
        harness,
        kind,
        location,
        path,
        source,
    });

    let mut store = ReviewStore::open(path)?;
    let tx = store.helper_transaction()?;
    let mut issues = Vec::new();
    let mut helpers = Vec::new();
    let mut new_changes = 0;
    let now = Utc::now().to_rfc3339();
    for scope in scopes {
        let saved: Option<String> = tx
            .query_row(
                "SELECT entries FROM helper_inventory WHERE scope=?1",
                [scope.location],
                |row| row.get(0),
            )
            .optional()?;
        let previous: Inventory = saved
            .as_ref()
            .map(|value| serde_json::from_str(value))
            .transpose()?
            .unwrap_or_default();
        let current = match scope.read() {
            Ok(current) => current,
            Err(_) => {
                issues.push(scope.location);
                helpers.extend(previous.into_values());
                continue;
            }
        };
        if saved.is_some() {
            for (key, helper) in &current {
                let change = match previous.get(key) {
                    None => "added",
                    Some(old) if old != helper => "modified",
                    Some(_) => continue,
                };
                new_changes += tx.execute(
                    "INSERT INTO helper_changes(observed_at,change,helper) VALUES (?1,?2,?3)",
                    params![now, change, serde_json::to_string(helper)?],
                )?;
            }
            for (key, helper) in &previous {
                if !current.contains_key(key) {
                    new_changes += tx.execute("INSERT INTO helper_changes(observed_at,change,helper) VALUES (?1,'removed',?2)",
                        params![now, serde_json::to_string(helper)?])?;
                }
            }
        }
        if saved.is_none() || previous != current {
            tx.execute(
                "INSERT OR REPLACE INTO helper_inventory VALUES (?1,?2)",
                params![scope.location, serde_json::to_string(&current)?],
            )?;
        }
        helpers.extend(current.into_values());
    }
    let changes = {
        let mut query = tx.prepare(
            "SELECT id,observed_at,change,helper FROM helper_changes ORDER BY id DESC LIMIT 100",
        )?;
        let rows = query.query_map([], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
            ))
        })?;
        rows.map(|row| {
            let (id, at, change, helper) = row?;
            let mut helper: Value = serde_json::from_str(&helper)?;
            helper["id"] = json!(id);
            helper["observed_at"] = json!(at);
            helper["change"] = json!(change);
            Ok(helper)
        })
        .collect::<Result<Vec<_>>>()?
    };
    tx.commit()?;
    Ok(json!({"helpers":helpers,"changes":changes,"issues":issues,"new_changes":new_changes}))
}
