use std::collections::BTreeMap;
use std::ops::Range;

use serde_json::{json, Map, Value};
use toml_edit::{Array, DocumentMut, Item, Table};

use super::{Client, Result, ENTRY};
use crate::review::ReviewError;

pub(super) struct Edit {
    pub(super) text: String,
    pub(super) sections: Vec<String>,
    pub(super) insertion: Option<String>,
}

fn parse_toml(text: &str) -> Result<DocumentMut> {
    text.strip_prefix('\u{feff}')
        .unwrap_or(text)
        .parse()
        .map_err(|_| ReviewError("Client TOML settings could not be parsed.").into())
}

fn toml_entry(document: &DocumentMut) -> Result<Option<&Item>> {
    let Some(servers) = document.get("mcp_servers") else {
        return Ok(None);
    };
    Ok(servers
        .as_table_like()
        .ok_or(ReviewError("The mcp_servers setting must be a table."))?
        .get(ENTRY))
}

fn toml_value(entry: &Item) -> Value {
    let Some(table) = entry.as_table_like() else {
        return Value::Null;
    };
    if table.len() != 2 {
        return Value::Null;
    }
    let Some(command) = table.get("command").and_then(Item::as_str) else {
        return Value::Null;
    };
    let Some(args) = table.get("args").and_then(Item::as_array) else {
        return Value::Null;
    };
    let Some(args) = args
        .iter()
        .map(toml_edit::Value::as_str)
        .collect::<Option<Vec<_>>>()
    else {
        return Value::Null;
    };
    json!({"command":command, "args":args})
}

pub(super) fn route_toml(
    text: &str,
    home: &std::path::Path,
    db: &std::path::Path,
) -> Result<(String, BTreeMap<String, Value>, Vec<String>)> {
    let mut document = parse_toml(text)?;
    let Some(servers) = document
        .get_mut("mcp_servers")
        .and_then(Item::as_table_like_mut)
    else {
        return Ok((text.to_owned(), BTreeMap::new(), Vec::new()));
    };
    let current = catalogs(Client::Codex, text)?;
    let mut profiles = BTreeMap::new();
    let mut skipped = Vec::new();
    let executable = std::env::current_exe()?;
    for (name, settings) in current {
        if !crate::harness_catalog::configured_name(&name)
            || name == "driftguard-filesystem"
            || settings["enabled"] == false
            || crate::harness_catalog::routed_entry(&settings)
        {
            continue;
        }
        let table = servers.get_mut(&name).and_then(Item::as_table_like_mut);
        let Some(table) = table.filter(|table| {
            table.iter().all(|(key, _)| {
                matches!(
                    key,
                    "command"
                        | "args"
                        | "cwd"
                        | "env"
                        | "env_vars"
                        | "url"
                        | "bearer_token_env_var"
                        | "enabled"
                        | "required"
                        | "startup_timeout_sec"
                        | "tool_timeout_sec"
                        | "enabled_tools"
                        | "disabled_tools"
                        | "scopes"
                        | "oauth_resource"
                )
            })
        }) else {
            skipped.push(name);
            continue;
        };
        // Remote OAuth and Codex-specific credentials stay with the original client.
        if table.contains_key("scopes")
            || table.contains_key("oauth_resource")
            || (table.contains_key("url") && !table.contains_key("bearer_token_env_var"))
        {
            skipped.push(name);
            continue;
        }
        let Ok(mut profile) = crate::harness_catalog::configured_profile(&settings, &name, home)
        else {
            skipped.push(name);
            continue;
        };
        if profile["transport"] != "http" && table.contains_key("env") {
            let Some(environment) = settings["env"].as_object() else {
                skipped.push(name);
                continue;
            };
            let mut names = profile["pass_env"].as_array().cloned().unwrap_or_default();
            for key in environment.keys() {
                if !names.iter().any(|value| value == key.as_str()) {
                    names.push(json!(key));
                }
            }
            profile["pass_env"] = json!(names);
        }
        for key in ["command", "args", "cwd", "url", "bearer_token_env_var"] {
            table.remove(key);
        }
        table.insert("command", toml_edit::value(super::path_text(&executable)?));
        let args: Array = ["--db", super::path_text(db)?, "serve", "--route", &name]
            .into_iter()
            .collect();
        table.insert("args", toml_edit::value(args));
        if let Some(variable) = settings["bearer_token_env_var"].as_str() {
            let mut variables = table
                .get("env_vars")
                .and_then(Item::as_array)
                .cloned()
                .unwrap_or_default();
            if !variables
                .iter()
                .any(|value| value.as_str() == Some(variable))
            {
                variables.push(variable);
            }
            table.insert("env_vars", toml_edit::value(variables));
        }
        profiles.insert(name, profile);
    }
    Ok((format!("{}{}", bom(text), document), profiles, skipped))
}

pub(super) fn restore_routes(
    current: &str,
    original: &str,
    installed: &str,
    names: impl Iterator<Item = String>,
) -> Result<String> {
    if current == installed {
        return Ok(original.to_string());
    }
    let mut document = parse_toml(current)?;
    let original = parse_toml(original)?;
    let installed = parse_toml(installed)?;
    let before = original["mcp_servers"].as_table_like().unwrap();
    let expected = installed["mcp_servers"].as_table_like().unwrap();
    let current_servers = document
        .get_mut("mcp_servers")
        .and_then(Item::as_table_like_mut)
        .ok_or(ReviewError(
            "Codex MCP settings no longer contain the routed entries.",
        ))?;
    for name in names {
        let entry = current_servers.get(&name);
        if !same_route_entry(entry, expected.get(&name)) {
            return Err(ReviewError("A routed Codex entry changed. Restore its managed settings before undoing routing.").into());
        }
        current_servers.insert(&name, before.get(&name).unwrap().clone());
    }
    Ok(format!("{}{}", bom(current), document))
}

pub(super) fn same_route_entry(current: Option<&Item>, expected: Option<&Item>) -> bool {
    fn fields(item: &Item) -> Option<BTreeMap<String, String>> {
        Some(
            item.as_table_like()?
                .iter()
                .map(|(key, value)| {
                    let mut value = value.clone();
                    if let Some(value) = value.as_value_mut() {
                        value.decor_mut().clear();
                    }
                    (key.to_owned(), value.to_string())
                })
                .collect(),
        )
    }
    current
        .and_then(fields)
        .zip(expected.and_then(fields))
        .is_some_and(|(a, b)| a == b)
}

pub(super) fn route_matches(current: &str, installed: &str, name: &str) -> Result<bool> {
    let current = parse_toml(current)?;
    let installed = parse_toml(installed)?;
    let entry = |doc: &DocumentMut| {
        doc.get("mcp_servers")
            .and_then(Item::as_table_like)
            .and_then(|table| table.get(name))
            .cloned()
    };
    Ok(same_route_entry(
        entry(&current).as_ref(),
        entry(&installed).as_ref(),
    ))
}

fn bom(text: &str) -> &str {
    if text.starts_with('\u{feff}') {
        "\u{feff}"
    } else {
        ""
    }
}

pub(super) fn link_registered_toml(
    text: &str,
    name: &str,
    entry: &Value,
    add: bool,
) -> Result<String> {
    let mut document = parse_toml(text)?;
    let servers = document
        .entry("mcp_servers")
        .or_insert_with(|| {
            let mut table = Table::new();
            table.set_implicit(true);
            Item::Table(table)
        })
        .as_table_like_mut()
        .ok_or(ReviewError("The mcp_servers setting must be a table."))?;
    if let Some(current) = servers.get(name) {
        if toml_value(current) != *entry {
            if !add {
                return Ok(text.to_owned());
            }
            return Err(ReviewError(
                "Codex already has a server with this name. Choose a different name.",
            )
            .into());
        }
        if add {
            return Ok(text.to_owned());
        }
        servers.remove(name);
    } else if add {
        let mut table = Table::new();
        table.insert(
            "command",
            toml_edit::value(entry["command"].as_str().unwrap()),
        );
        let args: Array = entry["args"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_str().unwrap())
            .collect();
        table.insert("args", toml_edit::value(args));
        servers.insert(name, Item::Table(table));
    } else {
        return Ok(text.to_owned());
    }
    Ok(format!("{}{}", bom(text), document))
}

fn install_toml(text: &str, entry: &Value) -> Result<Edit> {
    let mut document = parse_toml(text)?;
    if toml_entry(&document)?.is_some() {
        return Err(ReviewError("Client settings contain a conflicting DriftGuard entry.").into());
    }
    let servers = document.entry("mcp_servers").or_insert_with(|| {
        let mut table = Table::new();
        table.set_implicit(true);
        Item::Table(table)
    });
    let servers = servers
        .as_table_like_mut()
        .ok_or(ReviewError("The mcp_servers setting must be a table."))?;
    let mut table = Table::new();
    table.insert(
        "command",
        toml_edit::value(entry["command"].as_str().unwrap()),
    );
    let args: Array = entry["args"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| value.as_str().unwrap())
        .collect();
    table.insert("args", toml_edit::value(args));
    servers.insert(ENTRY, Item::Table(table));
    let text = format!("{}{}", bom(text), document);
    Ok(Edit {
        text,
        sections: vec![],
        insertion: None,
    })
}

// JSONC comments and trailing commas are replaced with spaces in a parallel
// string. All offsets then refer to the original text, including UTF-8 comments.
fn mask_jsonc(source: &str) -> Result<String> {
    let mut masked = source.as_bytes().to_vec();
    let bytes = source.as_bytes();
    let mut i = 0;
    let mut quoted = false;
    let mut commas = Vec::new();
    while i < bytes.len() {
        match bytes[i] {
            b'\\' if quoted => i += 1,
            b'"' => quoted = !quoted,
            b'/' if !quoted && bytes.get(i + 1) == Some(&b'/') => {
                while i < bytes.len() && !matches!(bytes[i], b'\n' | b'\r') {
                    masked[i] = b' ';
                    i += 1;
                }
                continue;
            }
            b'/' if !quoted && bytes.get(i + 1) == Some(&b'*') => {
                let start = i;
                i += 2;
                while i + 1 < bytes.len() && &bytes[i..i + 2] != b"*/" {
                    i += 1;
                }
                if i + 1 >= bytes.len() {
                    return Err(
                        ReviewError("Client settings contain an unfinished comment.").into(),
                    );
                }
                i += 2;
                for byte in &mut masked[start..i] {
                    if !matches!(*byte, b'\n' | b'\r') {
                        *byte = b' ';
                    }
                }
                continue;
            }
            b',' if !quoted => commas.push(i),
            _ => {}
        }
        i += 1;
    }
    for index in commas {
        let next = masked[index + 1..]
            .iter()
            .find(|byte| !byte.is_ascii_whitespace());
        if matches!(next, Some(b'}' | b']')) {
            masked[index] = b' ';
        }
    }
    Ok(String::from_utf8(masked)?)
}

fn parse_json(client: Client, text: &str) -> Result<(String, Value)> {
    let text = text.strip_prefix('\u{feff}').unwrap_or(text);
    let text = if matches!(client, Client::OpenCode | Client::VsCode) {
        mask_jsonc(text)?
    } else {
        text.to_owned()
    };
    let value = crate::input::parse(text.as_bytes())
        .map_err(|_| ReviewError("Client JSON settings could not be parsed."))?;
    if !value.is_object() {
        return Err(ReviewError("Client JSON settings must contain an object.").into());
    }
    Ok((text, value))
}

fn json_sections(client: Client, document: &Value) -> Vec<String> {
    let sections: &[&str] = match client {
        Client::OpenCode => {
            // Older OpenCode installations put server names directly in mcp.
            let flat = document["mcp"].as_object().is_some_and(|mcp| {
                !mcp.contains_key("servers")
                    && mcp.values().any(|value| {
                        matches!(value["type"].as_str(), Some("local" | "remote"))
                            || value.as_bool() == Some(false)
                    })
            });
            if flat {
                &["mcp"]
            } else {
                &["mcp", "servers"]
            }
        }
        Client::VsCode => &["servers"],
        _ => &["mcpServers"],
    };
    sections.iter().map(|name| (*name).to_owned()).collect()
}

pub(super) fn catalogs(client: Client, text: &str) -> Result<BTreeMap<String, Value>> {
    if client == Client::Codex {
        let document = parse_toml(text)?;
        let Some(servers) = document.get("mcp_servers") else {
            return Ok(BTreeMap::new());
        };
        let servers = servers
            .as_table_like()
            .ok_or(ReviewError("The mcp_servers setting must be a table."))?;
        return servers
            .iter()
            .map(|(name, item)| {
                let Some(table) = item.as_table_like() else {
                    return Ok((name.to_owned(), Value::Null));
                };
                let mut settings = Map::new();
                for key in ["command", "cwd", "url", "bearer_token_env_var"] {
                    if let Some(value) = table.get(key) {
                        settings.insert(key.to_owned(), json!(value.as_str()));
                    }
                }
                for key in ["args", "env_vars"] {
                    if let Some(value) = table.get(key) {
                        settings.insert(
                            key.to_owned(),
                            json!(value.as_array().and_then(|items| items
                                .iter()
                                .map(toml_edit::Value::as_str)
                                .collect::<Option<Vec<_>>>())),
                        );
                    }
                }
                if let Some(value) = table.get("enabled") {
                    settings.insert("enabled".into(), json!(value.as_bool()));
                }
                if let Some(value) = table.get("env") {
                    let environment = value.as_table_like().and_then(|env| {
                        env.iter()
                            .map(|(key, value)| Some((key.to_owned(), value.as_str()?.to_owned())))
                            .collect::<Option<BTreeMap<_, _>>>()
                    });
                    settings.insert("env".into(), json!(environment));
                }
                for key in ["http_headers", "env_http_headers"] {
                    if let Some(value) = table.get(key) {
                        settings.insert(
                            key.to_owned(),
                            json!(value
                                .as_table_like()
                                .is_none_or(|headers| !headers.is_empty())),
                        );
                    }
                }
                Ok((name.to_owned(), Value::Object(settings)))
            })
            .collect();
    }
    let (_, document) = parse_json(client, text)?;
    let mut section = &document;
    for name in json_sections(client, &document) {
        let Some(next) = section.get(name) else {
            return Ok(BTreeMap::new());
        };
        section = next;
    }
    let servers = section
        .as_object()
        .ok_or(ReviewError("Client MCP settings must contain an object."))?;
    Ok(servers
        .iter()
        .map(|(name, value)| (name.clone(), value.clone()))
        .collect())
}

fn json_get(value: &Value, sections: &[String], name: &str) -> Result<Option<Value>> {
    let mut current = value;
    for name in sections {
        let parent = current
            .as_object()
            .ok_or(ReviewError("Client MCP settings must contain an object."))?;
        match parent.get(name) {
            Some(value) => current = value,
            None => return Ok(None),
        }
    }
    let map = current
        .as_object()
        .ok_or(ReviewError("Client MCP settings must contain an object."))?;
    Ok(map.get(name).cloned())
}

#[derive(Clone)]
struct Member {
    key_start: usize,
    value: Range<usize>,
}

fn skip_space(text: &str, index: usize) -> usize {
    text.len() - text[index..].trim_start().len()
}

fn members(text: &str, start: usize) -> Result<BTreeMap<String, Member>> {
    if text.as_bytes().get(start) != Some(&b'{') {
        return Err(ReviewError("Client MCP settings must contain an object.").into());
    }
    let mut members = BTreeMap::new();
    let mut index = skip_space(text, start + 1);
    while text.as_bytes().get(index) != Some(&b'}') {
        let key_start = index;
        let mut parser = serde_json::Deserializer::from_str(&text[index..]).into_iter::<String>();
        let key = parser
            .next()
            .ok_or(ReviewError("Invalid client settings."))??;
        index = skip_space(text, index + parser.byte_offset());
        let value_start = skip_space(text, index + 1);
        let mut parser = serde_json::Deserializer::from_str(&text[value_start..])
            .into_iter::<&serde_json::value::RawValue>();
        parser
            .next()
            .ok_or(ReviewError("Invalid client settings."))??;
        let end = value_start + parser.byte_offset();
        members.insert(
            key,
            Member {
                key_start,
                value: value_start..end,
            },
        );
        index = skip_space(text, end);
        if text.as_bytes().get(index) == Some(&b',') {
            index = skip_space(text, index + 1);
        }
    }
    Ok(members)
}

fn install_json(client: Client, original: &str, entry: &Value, entry_name: &str) -> Result<Edit> {
    let prefix = bom(original);
    let source = &original[prefix.len()..];
    let source = if source.trim().is_empty() {
        "{}\n"
    } else {
        source
    };
    let (parsed, document) = parse_json(client, source)?;
    let sections = json_sections(client, &document);
    let path = sections
        .iter()
        .map(String::as_str)
        .chain([entry_name])
        .collect::<Vec<_>>();
    let mut start = skip_space(&parsed, 0);
    for (index, name) in path.iter().enumerate() {
        let children = members(&parsed, start)?;
        if let Some(member) = children.get(*name) {
            if index == path.len() - 1 {
                return Err(
                    ReviewError("Client settings contain a conflicting DriftGuard entry.").into(),
                );
            }
            start = member.value.start;
            continue;
        }
        let mut new = entry.clone();
        for nested in path[index + 1..].iter().rev() {
            new = Value::Object(Map::from_iter([(nested.to_string(), new)]));
        }
        let last = children.values().map(|member| member.value.end).max();
        let insertion = format!(
            "{}\n  {}: {}",
            if last.is_some() { "," } else { "" },
            serde_json::to_string(name)?,
            new
        );
        let offset = last.unwrap_or(start + 1);
        let text = format!(
            "{prefix}{}{insertion}{}",
            &source[..offset],
            &source[offset..]
        );
        parse_json(client, &text)?;
        return Ok(Edit {
            text,
            sections,
            insertion: Some(insertion),
        });
    }
    Err(ReviewError("Could not update client MCP settings.").into())
}

pub(super) fn install(client: Client, text: &str, entry: &Value) -> Result<Edit> {
    if client == Client::Codex {
        install_toml(text, entry)
    } else {
        install_json(client, text, entry, ENTRY)
    }
}

pub(super) fn get(client: Client, text: &str, sections: &[String]) -> Result<Option<Value>> {
    if client == Client::Codex {
        return Ok(toml_entry(&parse_toml(text)?)?.map(toml_value));
    }
    let (_, parsed) = parse_json(client, text)?;
    json_get(&parsed, sections, ENTRY)
}

pub(super) fn link_registered(
    client: Client,
    text: &str,
    name: &str,
    entry: &Value,
    add: bool,
) -> Result<String> {
    if client == Client::Codex {
        return link_registered_toml(text, name, entry, add);
    }
    let (_, parsed) = parse_json(client, if text.trim().is_empty() { "{}" } else { text })?;
    let sections = json_sections(client, &parsed);
    let existing = json_get(&parsed, &sections, name)?;
    match (add, existing) {
        (true, None) => Ok(install_json(client, text, entry, name)?.text),
        (true, Some(existing)) if existing != *entry => Err(ReviewError(
            "This harness already has a server with that name. Choose a different name.",
        )
        .into()),
        (false, Some(existing)) if existing == *entry => {
            remove_json(client, text, &sections, name, None)
        }
        _ => Ok(text.to_owned()),
    }
}

pub(super) fn remove(
    client: Client,
    text: &str,
    sections: &[String],
    expected: &Value,
    insertion: Option<&str>,
) -> Result<Option<String>> {
    let Some(current) = get(client, text, sections)? else {
        return Ok(None);
    };
    if current != *expected {
        return Err(ReviewError(
            "The managed DriftGuard entry was edited. Restore or remove it before disconnecting.",
        )
        .into());
    }
    if client == Client::Codex {
        let mut document = parse_toml(text)?;
        document["mcp_servers"]
            .as_table_like_mut()
            .unwrap()
            .remove(ENTRY);
        return Ok(Some(format!("{}{}", bom(text), document)));
    }
    Ok(Some(remove_json(client, text, sections, ENTRY, insertion)?))
}

fn remove_json(
    client: Client,
    text: &str,
    sections: &[String],
    entry_name: &str,
    insertion: Option<&str>,
) -> Result<String> {
    let prefix = bom(text);
    let source = &text[prefix.len()..];
    let (parsed, _) = parse_json(client, source)?;
    let mut start = skip_space(&parsed, 0);
    for name in sections {
        start = members(&parsed, start)?[name].value.start;
    }
    let member = &members(&parsed, start)?[entry_name];
    if let Some(insertion) = insertion {
        if let Some((at, _)) = source
            .match_indices(insertion)
            .find(|(at, _)| *at <= member.key_start && at + insertion.len() >= member.value.end)
        {
            let restored = format!(
                "{prefix}{}{}",
                &source[..at],
                &source[at + insertion.len()..]
            );
            if get(client, &restored, sections).is_ok_and(|entry| entry.is_none()) {
                return Ok(restored);
            }
        }
    }
    let after = skip_space(&parsed, member.value.end);
    let before = parsed[..member.key_start].trim_end().len();
    let restored = if source.as_bytes().get(after) == Some(&b',') {
        format!(
            "{prefix}{}{}{}",
            &source[..member.key_start],
            &source[member.value.end..after],
            &source[after + 1..]
        )
    } else if before > 0 && parsed.as_bytes()[before - 1] == b',' {
        format!(
            "{prefix}{}{}{}",
            &source[..before - 1],
            &source[before..member.key_start],
            &source[member.value.end..]
        )
    } else {
        format!(
            "{prefix}{}{}",
            &source[..member.key_start],
            &source[member.value.end..]
        )
    };
    parse_json(client, &restored)?;
    Ok(restored)
}
