use std::error::Error;
use std::path::{Path, PathBuf};

use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};

use crate::review::{ReviewError, ReviewStore};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const AUTH_REQUIRED: &str = "The HTTPS server requires authentication.";

pub fn name(value: &Value) -> Result<&str> {
    value
        .as_str()
        .filter(|value| crate::harness_catalog::configured_name(value))
        .filter(|value| *value != "driftguard-filesystem")
        .ok_or_else(|| ReviewError("Choose a valid MCP server name.").into())
}

fn string(value: &Value) -> Option<&str> {
    value
        .as_str()
        .filter(|text| !text.is_empty() && text.len() <= 8192 && !text.contains('\0'))
}

pub fn profile(db: &Path, name: &str) -> Result<Value> {
    let store = ReviewStore::open(db)?;
    let raw: String = store
        .connection()
        .query_row(
            "SELECT profile FROM standalone_servers WHERE name=?1",
            [name],
            |row| row.get(0),
        )
        .optional()?
        .ok_or(ReviewError("This gateway server is not registered."))?;
    Ok(crate::input::parse(raw.as_bytes())?)
}

pub(crate) fn launcher(db: &Path, name: &str) -> Result<Value> {
    Ok(json!({"command":std::env::current_exe()?,
        "args":["--db",db.to_str().ok_or(ReviewError("Invalid database path."))?,"serve","--registered",name]}))
}

pub fn list(db: &Path) -> Result<Value> {
    let store = ReviewStore::open(db)?;
    let mut query = store
        .connection()
        .prepare("SELECT profile,state FROM standalone_servers ORDER BY name")?;
    let rows = query.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut servers = Vec::new();
    for row in rows {
        let (raw, state) = row?;
        let p = crate::input::parse(raw.as_bytes())?;
        let name = p["server_id"].as_str().unwrap_or_default();
        servers.push(
            json!({"server_id":name,"transport":p["transport"],"state":state,
            "url":p["url"],"use_os_vault":p["use_os_vault"] == true,
            "command":std::env::current_exe()?,
            "args":["--db",db.to_str().ok_or(ReviewError("Invalid database path."))?,
                "serve","--registered",name]}),
        );
    }
    Ok(json!(servers))
}

pub fn register_codex_hosted(db: &Path) -> Result<Value> {
    let codex_home = crate::harness::codex_home()?
        .canonicalize()
        .map_err(|_| ReviewError("Set up and sign in to Codex first."))?;
    let profile = json!({"server_id":crate::codex_hosted::SERVER,
        "transport":"codex_hosted","codex_home":codex_home});
    ReviewStore::open(db)?.connection().execute(
        "INSERT INTO standalone_servers VALUES (?1,?2,'configured')
         ON CONFLICT(name) DO UPDATE SET profile=excluded.profile,state='configured'
         WHERE standalone_servers.profile<>excluded.profile",
        params![crate::codex_hosted::SERVER, profile.to_string()],
    )?;
    check(db, crate::codex_hosted::SERVER)
}

pub fn save(db: &Path, request: &Value) -> Result<Value> {
    let name = name(&request["server_id"])?;
    if name == crate::codex_hosted::SERVER {
        return Err(ReviewError("Use Connect Codex hosted apps for this reserved route.").into());
    }
    let profile = match request["transport"].as_str() {
        Some("http") => {
            let endpoint =
                string(&request["url"]).ok_or(ReviewError("Enter an HTTPS MCP endpoint."))?;
            crate::http::validate_endpoint(endpoint)?;
            json!({"server_id":name,"transport":"http","url":endpoint,
                "use_os_vault":request["use_os_vault"] == true,"timeout_seconds":18})
        }
        Some("stdio") => {
            let argv = request["argv"]
                .as_array()
                .filter(|argv| {
                    !argv.is_empty()
                        && argv.len() <= 128
                        && argv.iter().all(|argument| string(argument).is_some())
                })
                .ok_or(ReviewError("Enter an executable and its arguments."))?;
            let cwd = match string(&request["cwd"]) {
                Some(path) => PathBuf::from(path),
                None => crate::harness::home()?.0,
            };
            let env = request["pass_env"]
                .as_array()
                .filter(|names| {
                    names.len() <= 64
                        && names.iter().all(|name| {
                            string(name).is_some_and(|name| {
                                name.bytes().next().is_some_and(|first| {
                                    first.is_ascii_alphabetic() || first == b'_'
                                }) && name
                                    .bytes()
                                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
                            })
                        })
                })
                .ok_or(ReviewError("Enter valid environment variable names."))?;
            let value = json!({"server_id":name,"transport":"stdio","argv":argv,"cwd":cwd,
                "pass_env":env,"timeout_seconds":18});
            crate::discovery::Profile::load(&value, None)?;
            value
        }
        _ => return Err(ReviewError("Choose local stdio or HTTPS.").into()),
    };
    let store = ReviewStore::open(db)?;
    store.connection().execute(
        "INSERT INTO standalone_servers VALUES (?1,?2,'configured')
         ON CONFLICT(name) DO UPDATE SET profile=excluded.profile,state='configured'
         WHERE standalone_servers.profile<>excluded.profile",
        params![name, profile.to_string()],
    )?;
    list(db)
}

pub fn remove(db: &Path, name: &str) -> Result<Value> {
    crate::harness::unlink_registered_server(db, name)?;
    ReviewStore::open(db)?
        .connection()
        .execute("DELETE FROM standalone_servers WHERE name=?1", [name])?;
    list(db)
}

pub fn state(db: &Path, profile: &Value, state: &str) -> Result<()> {
    ReviewStore::open(db)?.connection().execute(
        "UPDATE standalone_servers SET state=?3 WHERE name=?1 AND profile=?2",
        params![profile["server_id"].as_str(), profile.to_string(), state],
    )?;
    Ok(())
}

pub fn failure(db: &Path, profile: &Value, error: &(dyn Error + 'static)) -> Result<()> {
    let status = match error.downcast_ref::<ReviewError>().map(|error| error.0) {
        Some(
            AUTH_REQUIRED
            | "The configured bearer credential is unavailable."
            | "Sign in to Codex before connecting its hosted apps.",
        ) => "sign_in_required",
        Some("The HTTPS server denied access.") => "access_denied",
        _ => "unavailable",
    };
    state(db, profile, status)
}

pub fn check(db: &Path, name: &str) -> Result<Value> {
    let profile = profile(db, name)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let result: Result<()> = runtime.block_on(async {
        let codex_home = crate::harness::codex_home()?;
        let mut upstream =
            crate::gateway::Upstream::open_with_codex_home(&profile, Some(&codex_home))?;
        upstream.initialize().await?;
        let tools = upstream.catalog().await?;
        upstream.verify()?;
        if self::profile(db, name)? == profile {
            let source = format!("gateway:direct:{name}");
            let mut store = ReviewStore::open(db)?;
            store.observe_gateway_catalog(&source, upstream.identity(), &tools)?;
            state(db, &profile, "catalog_ready")?;
        }
        Ok(())
    });
    if let Err(error) = result {
        if profile["transport"] == "codex_hosted" {
            eprintln!(
                "{}",
                error
                    .downcast_ref::<ReviewError>()
                    .map_or("Hosted connector check failed.", |error| error.0)
            );
        }
        failure(db, &profile, error.as_ref())?;
        ReviewStore::open(db)?.catalog_check_failed(&format!("gateway:direct:{name}"))?;
    }
    list(db)
}
