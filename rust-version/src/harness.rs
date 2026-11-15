use std::env;
use std::error::Error;
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tempfile::NamedTempFile;

use crate::review::ReviewError;

#[path = "harness_config.rs"]
mod config;

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const LIMIT: u64 = 1024 * 1024;
const PROFILE_LIMIT: u64 = 64 * 1024;
pub(super) const ENTRY: &str = "driftguard-rust";

#[derive(Clone, Copy, PartialEq, Eq)]
enum Client {
    Codex,
    Claude,
    Cursor,
    Antigravity,
    Gemini,
    OpenCode,
    VsCode,
}

impl Client {
    const ALL: [Self; 7] = [
        Self::Codex,
        Self::Claude,
        Self::Cursor,
        Self::Antigravity,
        Self::Gemini,
        Self::OpenCode,
        Self::VsCode,
    ];

    fn parse(name: &str) -> Result<Self> {
        Self::ALL
            .into_iter()
            .find(|client| client.id() == name)
            .ok_or_else(|| ReviewError("Choose a supported coding harness.").into())
    }

    fn id(self) -> &'static str {
        match self {
            Self::Codex => "codex",
            Self::Claude => "claude",
            Self::Cursor => "cursor",
            Self::Antigravity => "antigravity",
            Self::Gemini => "gemini",
            Self::OpenCode => "opencode",
            Self::VsCode => "vscode",
        }
    }

    fn display(self) -> &'static str {
        match self {
            Self::Codex => "Codex",
            Self::Claude => "Claude Code",
            Self::Cursor => "Cursor",
            Self::Antigravity => "Antigravity",
            Self::Gemini => "Gemini CLI",
            Self::OpenCode => "OpenCode",
            Self::VsCode => "VS Code / Copilot",
        }
    }

    fn executable_names(self) -> &'static [&'static str] {
        match self {
            Self::Codex => &["codex"],
            Self::Claude => &["claude"],
            Self::Cursor => &["cursor", "cursor-agent"],
            Self::Antigravity => &["agy", "antigravity"],
            Self::Gemini => &["gemini"],
            Self::OpenCode => &["opencode"],
            Self::VsCode => &["code", "code-insiders"],
        }
    }

    fn application(self) -> Option<&'static str> {
        match self {
            Self::Codex => Some("Codex"),
            Self::Cursor => Some("Cursor"),
            Self::Antigravity => Some("Antigravity"),
            Self::OpenCode => Some("OpenCode"),
            Self::VsCode => Some("Visual Studio Code"),
            _ => None,
        }
    }

    fn detected(self, home_dir: &Path) -> bool {
        self.executable_names().iter().any(|name| on_path(name))
            || self.application().is_some_and(|app| {
                if cfg!(target_os = "macos") {
                    let name = format!("{app}.app");
                    Path::new("/Applications").join(&name).is_dir()
                        || home_dir.join("Applications").join(&name).is_dir()
                        || (self == Self::VsCode
                            && Path::new("/Applications/Visual Studio Code - Insiders.app")
                                .is_dir())
                } else if cfg!(windows) {
                    let executable = if self == Self::VsCode { "Code" } else { app };
                    let relative = Path::new(app).join(format!("{executable}.exe"));
                    let local =
                        env_path("LOCALAPPDATA").unwrap_or_else(|| home_dir.join("AppData/Local"));
                    let program_files = env_path("ProgramFiles")
                        .unwrap_or_else(|| PathBuf::from("C:/Program Files"));
                    local.join("Programs").join(&relative).is_file()
                        || program_files.join(relative).is_file()
                } else {
                    false
                }
            })
    }

    fn config_path(self, home_dir: &Path, isolated: bool) -> PathBuf {
        let configured = |variable| (!isolated).then(|| env_path(variable)).flatten();
        match self {
            Self::Codex => configured("CODEX_HOME")
                .unwrap_or_else(|| home_dir.join(".codex"))
                .join("config.toml"),
            Self::Claude => configured("CLAUDE_CONFIG_DIR")
                .unwrap_or_else(|| home_dir.to_path_buf())
                .join(".claude.json"),
            Self::Cursor => home_dir.join(".cursor/mcp.json"),
            Self::Antigravity => home_dir.join(".gemini/config/mcp_config.json"),
            Self::Gemini => configured("GEMINI_CLI_HOME")
                .unwrap_or_else(|| home_dir.to_path_buf())
                .join(".gemini/settings.json"),
            Self::OpenCode => {
                let root = configured("XDG_CONFIG_HOME")
                    .unwrap_or_else(|| home_dir.join(".config"))
                    .join("opencode");
                let json = root.join("opencode.json");
                let jsonc = root.join("opencode.jsonc");
                if json.exists() && !jsonc.exists() {
                    json
                } else {
                    jsonc
                }
            }
            Self::VsCode => {
                let base = if cfg!(target_os = "macos") {
                    home_dir.join("Library/Application Support")
                } else if cfg!(windows) {
                    configured("APPDATA").unwrap_or_else(|| home_dir.join("AppData/Roaming"))
                } else {
                    configured("XDG_CONFIG_HOME").unwrap_or_else(|| home_dir.join(".config"))
                };
                let insiders = !base.join("Code/User").is_dir()
                    && (base.join("Code - Insiders/User").is_dir()
                        || (!on_path("code") && on_path("code-insiders")));
                let editor = if insiders { "Code - Insiders" } else { "Code" };
                base.join(editor).join("User/mcp.json")
            }
        }
    }

    fn entry(self, db: &Path, profile: &Path) -> Result<Value> {
        let executable = env::current_exe()?;
        let arguments = [
            "--db",
            path_text(db)?,
            "serve",
            path_text(profile)?,
            "--client",
            self.id(),
        ];
        let command = path_text(&executable)?;
        Ok(match self {
            Self::OpenCode => {
                let argv: Vec<_> = std::iter::once(command).chain(arguments).collect();
                json!({"type":"local", "command":argv})
            }
            Self::Claude | Self::VsCode => {
                json!({"type":"stdio", "command":command, "args":arguments})
            }
            _ => json!({"command":command, "args":arguments}),
        })
    }
}

pub(crate) fn client_label(id: &str) -> Option<&'static str> {
    Client::parse(id).ok().map(Client::display)
}

pub(crate) struct CatalogConfig {
    pub id: &'static str,
    pub path: PathBuf,
    pub home: PathBuf,
    pub digest: String,
    pub isolated: bool,
    pub entries: std::collections::BTreeMap<String, Value>,
}

impl CatalogConfig {
    pub fn unchanged(&self) -> bool {
        read_text(&self.path, LIMIT)
            .ok()
            .flatten()
            .is_some_and(|text| digest(&text) == self.digest)
    }
}

pub(crate) type CatalogConfigResult = (&'static str, Result<Option<CatalogConfig>>);

pub(crate) fn catalog_configs(db: &Path) -> Result<Vec<CatalogConfigResult>> {
    let (home, isolated) = home()?;
    Ok(Client::ALL
        .into_iter()
        .map(|client| {
            let read = || {
                let manifest = read_manifest(&location(db, client))?;
                let target = if let Some(manifest) = manifest {
                    if !is_connected(client, &manifest)? {
                        return Ok(None);
                    }
                    manifest.target
                } else if client == Client::Codex {
                    let Some(routes) = codex_routes(db)? else {
                        return Ok(None);
                    };
                    routes.target
                } else {
                    return Ok(None);
                };
                let Some(text) = read_text(&target, LIMIT)? else {
                    return Ok(None);
                };
                let entries = config::catalogs(client, &text)?;
                Ok(Some(CatalogConfig {
                    id: client.id(),
                    path: target,
                    home: home.clone(),
                    digest: digest(&text),
                    isolated,
                    entries,
                }))
            };
            (client.id(), read())
        })
        .collect())
}

#[derive(Deserialize, Serialize)]
struct Manifest {
    target: PathBuf,
    profile: PathBuf,
    profile_digest: String,
    original: Option<String>,
    installed: String,
    sections: Vec<String>,
    entry: Value,
    insertion: Option<String>,
    #[serde(default)]
    disconnecting: bool,
}

fn env_path(name: &str) -> Option<PathBuf> {
    env::var_os(name)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

pub(crate) fn home() -> Result<(PathBuf, bool)> {
    if let Some(home_dir) = env_path("DRIFTGUARD_HARNESS_HOME") {
        if !home_dir.is_absolute() {
            return Err(ReviewError("Harness home must be an absolute directory.").into());
        }
        return Ok((home_dir, true));
    }
    #[allow(deprecated)]
    let home_dir = env::home_dir().filter(|path| path.is_absolute());
    Ok((
        home_dir.ok_or(ReviewError("Could not locate the user home directory."))?,
        false,
    ))
}

pub(crate) fn codex_home() -> Result<PathBuf> {
    let (home, isolated) = home()?;
    let config = Client::Codex.config_path(&home, isolated);
    Ok(config
        .parent()
        .ok_or(ReviewError("Could not locate Codex settings."))?
        .to_path_buf())
}

pub(crate) fn link_registered_server(
    db: &Path,
    name: &str,
    harness: &str,
    add: bool,
) -> Result<()> {
    let (home_dir, isolated) = home()?;
    let client = Client::parse(harness)?;
    let target = client.config_path(&home_dir, isolated);
    let directory = target
        .parent()
        .ok_or(ReviewError("Harness settings are missing."))?;
    if !directory.is_dir() {
        if !add {
            return Ok(());
        }
        fs::create_dir_all(directory)?;
    }
    let lock = open_lock(&target.with_file_name("driftguard-config.lock"))?;
    lock.lock()?;
    let mut entry = crate::servers::launcher(db, name)?;
    if client != Client::Codex {
        entry["args"]
            .as_array_mut()
            .unwrap()
            .extend([json!("--harness"), json!(client.id())]);
    }
    if client == Client::OpenCode {
        let mut command = vec![entry["command"].clone()];
        command.extend(entry["args"].as_array().unwrap().iter().cloned());
        entry = json!({"type":"local","command":command});
    } else if matches!(client, Client::Claude | Client::VsCode) {
        entry["type"] = json!("stdio");
    }
    let current = read_text(&target, LIMIT)?;
    let original = current.as_deref().unwrap_or_default();
    let updated = config::link_registered(client, original, name, &entry, add)?;
    if updated != original {
        if updated.len() as u64 > LIMIT || read_text(&target, LIMIT)? != current {
            return Err(ReviewError("Harness settings changed during setup.").into());
        }
        save(&target, &updated, false)?;
    }
    Ok(())
}

pub(crate) fn unlink_registered_server(db: &Path, name: &str) -> Result<()> {
    for client in Client::ALL {
        link_registered_server(db, name, client.id(), false)?;
    }
    Ok(())
}

pub(crate) fn codex_mcp_sign_in(name: &str) -> Result<Value> {
    let (home_dir, isolated) = home()?;
    let settings = Client::Codex.config_path(&home_dir, isolated);
    let text = read_text(&settings, LIMIT)?.ok_or(ReviewError("Codex settings are missing."))?;
    let entries = config::catalogs(Client::Codex, &text)?;
    let url = entries
        .get(name)
        .and_then(|entry| entry["url"].as_str())
        .ok_or(ReviewError(
            "Sign-in requires a remote server configured in Codex.",
        ))?;
    crate::http::validate_endpoint(url)?;
    let candidate =
        home_dir
            .join(".local/bin")
            .join(if cfg!(windows) { "codex.exe" } else { "codex" });
    let executable = if candidate.is_file() {
        candidate
    } else {
        PathBuf::from("codex")
    };
    let output = std::process::Command::new(executable)
        .current_dir(home_dir)
        .env(
            "CODEX_HOME",
            settings
                .parent()
                .ok_or(ReviewError("Codex settings are missing."))?,
        )
        .args(["mcp", "login", name])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status()?;
    if !output.success() {
        return Err(ReviewError(
            "Codex could not complete browser sign-in. Check your Codex MCP account and try again.",
        )
        .into());
    }
    Ok(json!({"signed_in":true}))
}

fn on_path(name: &str) -> bool {
    let paths = env::var_os("PATH").unwrap_or_default();
    env::split_paths(&paths)
        .filter(|path| path.is_absolute())
        .any(|dir| {
            if cfg!(windows) {
                ["exe", "cmd", "bat"]
                    .iter()
                    .any(|ext| dir.join(format!("{name}.{ext}")).is_file())
            } else {
                let file = dir.join(name);
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    file.metadata()
                        .is_ok_and(|meta| meta.is_file() && meta.permissions().mode() & 0o111 != 0)
                }
                #[cfg(not(unix))]
                file.is_file()
            }
        })
}

fn path_text(path: &Path) -> Result<&str> {
    path.to_str()
        .ok_or_else(|| ReviewError("Client paths must be UTF-8.").into())
}

fn location(db: &Path, client: Client) -> PathBuf {
    let mut name = db.as_os_str().to_os_string();
    name.push(format!(".harness-{}.json", client.id()));
    PathBuf::from(name)
}

fn open_lock(path: &Path) -> Result<File> {
    if let Ok(meta) = fs::symlink_metadata(path) {
        if !meta.file_type().is_file() {
            return Err(ReviewError("Client lock must be a regular file.").into());
        }
    }
    let mut options = OpenOptions::new();
    options.create(true).truncate(false).read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let lock = options.open(path)?;
    if !lock.metadata()?.is_file() {
        return Err(ReviewError("Client lock must be a regular file.").into());
    }
    Ok(lock)
}

fn connection_lock(manifest_path: &Path) -> Result<File> {
    let mut path = manifest_path.as_os_str().to_os_string();
    path.push(".lock");
    open_lock(Path::new(&path))
}

pub(crate) fn read_text(path: &Path, limit: u64) -> Result<Option<String>> {
    let meta = match fs::symlink_metadata(path) {
        Ok(meta) => meta,
        Err(err) if err.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(err.into()),
    };
    if !meta.file_type().is_file() || meta.len() > limit {
        return Err(ReviewError("Client settings must be a bounded regular file.").into());
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    if !file.metadata()?.is_file() {
        return Err(ReviewError("Client settings must be a regular file.").into());
    }
    let mut text = String::new();
    file.take(limit + 1).read_to_string(&mut text)?;
    if text.len() as u64 > limit {
        return Err(ReviewError("Client settings exceed the size limit.").into());
    }
    Ok(Some(text))
}

fn save(path: &Path, text: &str, private: bool) -> Result<()> {
    let directory = path
        .parent()
        .ok_or(ReviewError("Could not locate client settings directory."))?;
    let mut file = NamedTempFile::new_in(directory)?;
    if !private {
        if let Ok(meta) = fs::metadata(path) {
            file.as_file().set_permissions(meta.permissions())?;
        }
    }
    file.write_all(text.as_bytes())?;
    file.as_file().sync_all()?;
    file.persist(path)?;
    #[cfg(unix)]
    File::open(directory)?.sync_all()?;
    Ok(())
}

fn read_manifest(path: &Path) -> Result<Option<Manifest>> {
    read_text(path, LIMIT * 8)?
        .map(|text| serde_json::from_str(&text).map_err(Into::into))
        .transpose()
}

fn digest(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

fn check_entry(client: Client, manifest: &Manifest) -> Result<bool> {
    let Some(settings) = read_text(&manifest.target, LIMIT)? else {
        return Ok(false);
    };
    Ok(config::get(client, &settings, &manifest.sections)? == Some(manifest.entry.clone()))
}

fn profile_digest(path: &Path) -> Result<String> {
    let text = read_text(path, PROFILE_LIMIT)?.ok_or(ReviewError("Gateway profile is missing."))?;
    Ok(digest(&text))
}

fn same_target(left: &Path, right: &Path) -> bool {
    if left == right {
        return true;
    }
    match (left.canonicalize(), right.canonicalize()) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

fn is_connected(client: Client, manifest: &Manifest) -> Result<bool> {
    Ok(!manifest.disconnecting
        && check_entry(client, manifest)?
        && profile_digest(&manifest.profile)? == manifest.profile_digest)
}

pub fn lock_connection(db: &Path, name: &str) -> Result<(File, PathBuf)> {
    let client = Client::parse(name)?;
    let path = location(&std::path::absolute(db)?, client);
    let lock = connection_lock(&path)?;
    lock.lock_shared()?;
    let manifest =
        read_manifest(&path)?.ok_or(ReviewError("This coding harness is disconnected."))?;
    if !is_connected(client, &manifest)? {
        return Err(ReviewError("The coding harness connection or profile has changed.").into());
    }
    Ok((lock, manifest.profile))
}

fn connect(db: &Path, client: Client, profile: &Path) -> Result<Value> {
    let profile = profile.canonicalize()?;
    let profile_digest = profile_digest(&profile)?;
    let (home_dir, isolated) = home()?;
    let target = std::path::absolute(client.config_path(&home_dir, isolated))?;
    let path = location(db, client);
    let lock = connection_lock(&path)?;
    lock.lock()?;
    let directory = target
        .parent()
        .ok_or(ReviewError("Could not locate client settings directory."))?;
    fs::create_dir_all(directory)?;
    let target = directory.canonicalize()?.join(
        target
            .file_name()
            .ok_or(ReviewError("Could not locate client settings file."))?,
    );
    let config_lock = open_lock(&target.with_file_name("driftguard-config.lock"))?;
    config_lock.lock()?;
    let original = read_text(&target, LIMIT)?;
    let entry = client.entry(db, &profile)?;
    if let Some(saved) = read_manifest(&path)? {
        if !same_target(&saved.target, &target)
            || saved.profile != profile
            || saved.profile_digest != profile_digest
            || saved.entry != entry
            || saved.disconnecting
        {
            return Err(ReviewError(
                "Disconnect the existing coding harness before changing its gateway.",
            )
            .into());
        }
        if check_entry(client, &saved)? {
            return Ok(status(client, &home_dir, &target, true, true));
        }
        if saved.original != original {
            return Err(ReviewError(
                "The coding harness settings changed. Disconnect to reconcile the managed entry.",
            )
            .into());
        }
        // An interrupted write may leave the original config and the manifest.
    }
    let edited = config::install(client, original.as_deref().unwrap_or_default(), &entry)?;
    if edited.text.len() as u64 > LIMIT {
        return Err(ReviewError("The resulting client settings exceed 1 MiB.").into());
    }
    let manifest = Manifest {
        target: target.clone(),
        profile,
        profile_digest,
        original,
        installed: digest(&edited.text),
        sections: edited.sections,
        entry,
        insertion: edited.insertion,
        disconnecting: false,
    };
    save(&path, &serde_json::to_string(&manifest)?, true)?;
    if read_text(&target, LIMIT)? != manifest.original {
        return Err(ReviewError("Client settings changed during setup.").into());
    }
    save(&target, &edited.text, false)?;
    Ok(status(client, &home_dir, &target, true, true))
}

fn disconnect(db: &Path, client: Client) -> Result<Value> {
    let (home_dir, isolated) = home()?;
    let path = location(db, client);
    let lock = connection_lock(&path)?;
    lock.lock()?;
    let Some(mut saved) = read_manifest(&path)? else {
        return Ok(status(
            client,
            &home_dir,
            &client.config_path(&home_dir, isolated),
            false,
            false,
        ));
    };
    if !saved.disconnecting {
        saved.disconnecting = true;
        save(&path, &serde_json::to_string(&saved)?, true)?;
    }
    let target = &saved.target;
    let directory = target
        .parent()
        .ok_or(ReviewError("Could not locate client settings directory."))?;
    if directory.is_dir() {
        let config_lock = open_lock(&target.with_file_name("driftguard-config.lock"))?;
        config_lock.lock()?;
        if let Some(current) = read_text(target, LIMIT)? {
            let restored = if digest(&current) == saved.installed {
                Some(saved.original)
            } else {
                config::remove(
                    client,
                    &current,
                    &saved.sections,
                    &saved.entry,
                    saved.insertion.as_deref(),
                )?
                .map(Some)
            };
            if let Some(restored) = restored {
                if read_text(target, LIMIT)?.as_deref() != Some(current.as_str()) {
                    return Err(ReviewError("Client settings changed during disconnect.").into());
                }
                if let Some(text) = restored {
                    save(target, &text, false)?;
                } else {
                    fs::remove_file(target)?;
                }
            }
        }
    }
    fs::remove_file(path)?;
    Ok(status(client, &home_dir, target, false, false))
}

fn status(client: Client, home_dir: &Path, target: &Path, connected: bool, managed: bool) -> Value {
    json!({
        "id":client.id(), "name":client.display(), "config_path":target,
        "detected":client.detected(home_dir), "connected":connected, "managed":managed
    })
}

#[derive(Deserialize, Serialize)]
struct RoutedCodex {
    target: PathBuf,
    original: String,
    installed: String,
    profiles: std::collections::BTreeMap<String, Value>,
    skipped: Vec<String>,
}

fn routes_path(db: &Path) -> PathBuf {
    let mut path = db.as_os_str().to_os_string();
    path.push(".codex-routes.json");
    path.into()
}

fn codex_routes(db: &Path) -> Result<Option<RoutedCodex>> {
    read_text(&routes_path(db), LIMIT * 8)?
        .map(|text| serde_json::from_str(&text).map_err(Into::into))
        .transpose()
}

pub(crate) fn routed_codex_names(db: &Path) -> Result<Vec<String>> {
    Ok(codex_routes(db)?
        .map(|routes| routes.profiles.into_keys().collect())
        .unwrap_or_default())
}

/// Routes skipped for compatibility or authentication reasons still bypass the gateway.
pub(crate) fn skipped_codex_routes(db: &Path) -> Result<Vec<String>> {
    Ok(codex_routes(db)?
        .map(|routes| routes.skipped)
        .unwrap_or_default())
}

pub(crate) fn lock_codex_route(db: &Path, name: &str) -> Result<(File, Value)> {
    let lock = connection_lock(&routes_path(db))?;
    lock.lock_shared()?;
    let routes = codex_routes(db)?.ok_or(ReviewError("Codex gateway routing is disabled."))?;
    let profile = routes
        .profiles
        .get(name)
        .ok_or(ReviewError("Unknown Codex gateway route."))?;
    let current =
        read_text(&routes.target, LIMIT)?.ok_or(ReviewError("Codex settings are missing."))?;
    if !config::route_matches(&current, &routes.installed, name)? {
        return Err(
            ReviewError("This Codex MCP entry changed. Update its DriftGuard routing.").into(),
        );
    }
    Ok((lock, profile.clone()))
}

fn route_codex(db: &Path, restore: bool) -> Result<Value> {
    let path = routes_path(db);
    let lock = connection_lock(&path)?;
    lock.lock()?;
    let saved = codex_routes(db)?;
    if restore && saved.is_none() {
        return Ok(json!({"routed":[],"skipped":[]}));
    }
    let (home_dir, isolated) = home()?;
    let target = saved
        .as_ref()
        .map(|routes| routes.target.clone())
        .unwrap_or_else(|| Client::Codex.config_path(&home_dir, isolated));
    if !target.is_file() {
        return Err(ReviewError("Codex MCP settings are missing.").into());
    }
    let config_lock = open_lock(&target.with_file_name("driftguard-config.lock"))?;
    config_lock.lock()?;
    let current = read_text(&target, LIMIT)?.ok_or(ReviewError("Codex settings are missing."))?;
    if let Some(saved) = saved {
        let matches = saved
            .profiles
            .keys()
            .map(|name| config::route_matches(&current, &saved.installed, name))
            .collect::<Result<Vec<_>>>()?;
        if restore {
            if current != saved.original {
                let original = config::restore_routes(
                    &current,
                    &saved.original,
                    &saved.installed,
                    saved.profiles.into_keys(),
                )?;
                if read_text(&target, LIMIT)?.as_deref() != Some(current.as_str()) {
                    return Err(ReviewError("Codex settings changed during route restoration.").into());
                }
                save(&target, &original, false)?;
            }
            fs::remove_file(path)?;
            return Ok(json!({"routed":[],"skipped":[]}));
        }
        if current == saved.original {
            if read_text(&target, LIMIT)?.as_deref() != Some(current.as_str()) {
                return Err(ReviewError("Codex settings changed during route setup.").into());
            }
            save(&target, &saved.installed, false)?;
        } else if matches.contains(&false) {
            return Err(ReviewError(
                "A routed Codex entry changed. Restore the managed entries before routing again.",
            )
            .into());
        }
        return Ok(
            json!({"routed":saved.profiles.keys().collect::<Vec<_>>(),"skipped":saved.skipped}),
        );
    }
    let (installed, profiles, skipped) = config::route_toml(&current, &home_dir, db)?;
    if !profiles.is_empty() {
        if installed.len() as u64 > LIMIT
            || profiles
                .values()
                .any(|profile| profile.to_string().len() as u64 > PROFILE_LIMIT)
        {
            return Err(
                ReviewError("The routed Codex configuration exceeds its size limit.").into(),
            );
        }
        let routes = RoutedCodex {
            target: target.clone(),
            original: current,
            installed,
            profiles,
            skipped,
        };
        save(&path, &serde_json::to_string(&routes)?, true)?;
        if read_text(&target, LIMIT)?.as_deref() != Some(routes.original.as_str()) {
            return Err(ReviewError("Codex settings changed during routing.").into());
        }
        save(&target, &routes.installed, false)?;
        return Ok(
            json!({"routed":routes.profiles.keys().collect::<Vec<_>>(),"skipped":routes.skipped}),
        );
    }
    Ok(json!({"routed":[],"skipped":skipped}))
}

pub fn run(db: &Path, mut args: impl Iterator<Item = OsString>) -> Result<Value> {
    let db = std::path::absolute(db)?;
    let action = args
        .next()
        .ok_or(ReviewError("Choose list, connect, or disconnect."))?;
    let action = action.to_str().unwrap_or_default();
    if action == "list" && args.next().is_none() {
        let (home_dir, isolated) = home()?;
        let entries = Client::ALL
            .into_iter()
            .map(|client| {
                let manifest = read_manifest(&location(&db, client))?;
                let target = manifest
                    .as_ref()
                    .map(|saved| saved.target.clone())
                    .unwrap_or_else(|| client.config_path(&home_dir, isolated));
                let managed = manifest.is_some();
                let connected = match manifest {
                    Some(saved) => is_connected(client, &saved).unwrap_or(false),
                    None => false,
                };
                Ok(status(client, &home_dir, &target, connected, managed))
            })
            .collect::<Result<Vec<_>>>()?;
        return Ok(json!(entries));
    }
    let name = args
        .next()
        .ok_or(ReviewError("Choose a supported coding harness."))?;
    let client = Client::parse(name.to_str().unwrap_or_default())?;
    match action {
        "route" | "restore" if client == Client::Codex && args.next().is_none() => {
            return route_codex(&db, action == "restore");
        }
        "connect" => {
            let profile = PathBuf::from(
                args.next()
                    .ok_or(ReviewError("Choose a gateway profile."))?,
            );
            if args.next().is_none() {
                return connect(&db, client, &profile);
            }
        }
        "disconnect" if args.next().is_none() => return disconnect(&db, client),
        _ => {}
    }
    Err(ReviewError("Unexpected coding harness command arguments.").into())
}
