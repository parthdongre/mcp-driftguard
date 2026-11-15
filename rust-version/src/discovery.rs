use std::collections::BTreeMap;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::sync::{Arc, OnceLock};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{mpsc, Notify};

use crate::review::ReviewError;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
type PeerMessage = std::result::Result<Value, &'static str>;
const MAX_PROFILE: u64 = 65_536;
const MAX_LINE: u64 = 1_048_576;
pub const VERSION: &str = "2025-11-25";
pub const MODERN: &str = "2026-07-28";
pub const LEGACY: &[&str] = &[VERSION, "2025-06-18", "2025-03-26"];
const BASE_ENV: &[&str] = &[
    "PATH",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
];
const IDENTITY_KDF_ROUNDS: u32 = 100_000;
// Codex receives its home directory as a path, never as a credential.
const PATH_ENV: &[&str] = &["CODEX_HOME"];

/// Fingerprints secret material with a salted, slow KDF so stored identities
/// cannot be brute-forced offline the way a bare SHA-256 can.
pub(crate) fn identity_kdf(source: &str, context: &[u8], secret: &str) -> String {
    let mut salt = b"driftguard-identity-v1\0".to_vec();
    salt.extend_from_slice(source.as_bytes());
    salt.push(0);
    salt.extend_from_slice(context);
    let mut key = [0; 32];
    pbkdf2::pbkdf2_hmac::<Sha256>(secret.as_bytes(), &salt, IDENTITY_KDF_ROUNDS, &mut key);
    key.iter().map(|byte| format!("{byte:02x}")).collect()
}

pub struct Profile {
    pub source: String,
    executable: PathBuf,
    args: Vec<String>,
    cwd: PathBuf,
    environment: BTreeMap<String, String>,
    // Derived once: `verify` recomputes the identity on every request.
    environment_binding: OnceLock<BTreeMap<String, String>>,
    secrets: Vec<String>,
    pub timeout: Duration,
    pub version: String,
    max_line: u64,
    catalog_limits: (usize, usize, usize),
}

impl Profile {
    pub fn parse_file(path: &Path) -> Result<Value> {
        if !path.is_file() {
            return Err(ReviewError("Choose a regular MCP profile file.").into());
        }
        let mut bytes = Vec::new();
        std::fs::File::open(path)?
            .take(MAX_PROFILE + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_PROFILE {
            return Err(ReviewError("The stdio profile exceeds 64 KiB.").into());
        }
        Ok(crate::input::parse(&bytes)?)
    }

    pub fn load(config: &Value, codex_home: Option<&Path>) -> Result<Self> {
        let search = codex_home
            .zip(std::env::var_os("PATH"))
            .map(|(home, path)| codex_gateway_path(&path, home))
            .transpose()?;
        Self::load_with_path(config, search.as_deref())
    }

    fn load_with_path(config: &Value, path: Option<&std::ffi::OsStr>) -> Result<Self> {
        let fields = config
            .as_object()
            .ok_or(ReviewError("Expected a JSON profile."))?;
        if fields.keys().any(|key| {
            !matches!(
                key.as_str(),
                "server_id"
                    | "argv"
                    | "cwd"
                    | "pass_env"
                    | "timeout_seconds"
                    | "protocol_version"
                    | "transport"
                    | "max_message_bytes"
                    | "max_catalog_bytes"
                    | "max_tools"
                    | "max_pages"
            )
        }) {
            return Err(ReviewError("Unknown stdio profile field.").into());
        }
        let id = config["server_id"]
            .as_str()
            .filter(|id| {
                !id.is_empty()
                    && id.len() <= 128
                    && id
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
            })
            .ok_or(ReviewError("Expected a valid server_id."))?;
        let mut argv = strings(&config["argv"])?;
        if argv.is_empty() || argv.len() > 128 {
            return Err(ReviewError("Expected an executable and optional arguments.").into());
        }
        let requested = PathBuf::from(argv.remove(0));
        let cwd = config
            .get("cwd")
            .map(|value| {
                value
                    .as_str()
                    .map(PathBuf::from)
                    .ok_or(ReviewError("Expected an absolute cwd."))
            })
            .transpose()?
            .unwrap_or(std::env::current_dir()?);
        if !cwd.is_absolute() || !cwd.is_dir() {
            return Err(ReviewError("Use an existing absolute cwd.").into());
        }
        let executable = resolve_executable(&requested, &cwd, path)?;
        if config
            .get("transport")
            .is_some_and(|value| value != "stdio")
        {
            return Err(ReviewError("Expected a stdio profile.").into());
        }
        let version = config
            .get("protocol_version")
            .map(|value| {
                value
                    .as_str()
                    .filter(|version| *version == MODERN || LEGACY.contains(version))
                    .ok_or(ReviewError("Unsupported upstream MCP protocol."))
            })
            .transpose()?
            .unwrap_or(VERSION);
        for (field, minimum, maximum) in [
            ("max_message_bytes", 1024, 16 * 1024 * 1024),
            ("max_catalog_bytes", 1024, 64 * 1024 * 1024),
            ("max_tools", 1, 10_000),
            ("max_pages", 1, 1_000),
        ] {
            if config.get(field).is_some_and(|value| {
                !value
                    .as_u64()
                    .is_some_and(|n| (minimum..=maximum).contains(&n))
            }) {
                return Err(ReviewError("Invalid stdio profile limit.").into());
            }
        }
        let limit = |name: &str, default| config[name].as_u64().unwrap_or(default);
        let max_line = limit("max_message_bytes", MAX_LINE);
        let max_catalog = limit("max_catalog_bytes", (8 * MAX_LINE).max(max_line));
        if max_catalog < max_line {
            return Err(
                ReviewError("Catalog byte limit cannot be below the message limit.").into(),
            );
        }
        let pass_env = config
            .get("pass_env")
            .map(strings)
            .transpose()?
            .unwrap_or_default();
        if pass_env.iter().any(|name| {
            !name.as_bytes()[0].is_ascii_alphabetic() && !name.starts_with('_')
                || !name
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
        }) {
            return Err(ReviewError("Invalid environment variable name.").into());
        }
        let timeout = config
            .get("timeout_seconds")
            .map(|value| {
                value
                    .as_f64()
                    .filter(|seconds| (0.05..=300.0).contains(seconds))
                    .ok_or(ReviewError("Choose a timeout from 0.05 to 300 seconds."))
            })
            .transpose()?
            .unwrap_or(15.0);
        let mut environment = BASE_ENV
            .iter()
            .copied()
            .chain(pass_env.iter().map(String::as_str))
            .filter_map(|name| {
                std::env::var(name)
                    .ok()
                    .map(|value| (name.to_owned(), value))
            })
            .collect::<BTreeMap<_, _>>();
        if let Some(path) = path.and_then(std::ffi::OsStr::to_str) {
            environment.insert("PATH".into(), path.to_owned());
        }
        let secrets = pass_env
            .iter()
            .filter_map(|name| environment.get(name))
            .filter(|value| value.len() >= 8)
            .cloned()
            .collect();
        Ok(Self {
            source: id.to_owned(),
            executable,
            args: argv,
            cwd,
            environment,
            environment_binding: OnceLock::new(),
            secrets,
            timeout: Duration::from_secs_f64(timeout),
            version: version.to_owned(),
            max_line,
            catalog_limits: (
                max_catalog as usize,
                limit("max_tools", 1000) as usize,
                limit("max_pages", 100) as usize,
            ),
        })
    }

    pub fn for_catalog(config: &Value, environment: &Value, home: &Path) -> Result<Self> {
        #[cfg_attr(not(unix), allow(unused_mut))]
        let mut paths: Vec<PathBuf> = std::env::var_os("PATH")
            .map(|path| {
                std::env::split_paths(&path)
                    .filter(|entry| entry.is_absolute())
                    .collect()
            })
            .unwrap_or_default();
        #[cfg(unix)]
        paths.extend([
            home.join(".local/bin"),
            home.join(".cargo/bin"),
            home.join(".bun/bin"),
            PathBuf::from("/opt/homebrew/bin"),
            PathBuf::from("/usr/local/bin"),
            PathBuf::from("/usr/bin"),
            PathBuf::from("/bin"),
        ]);
        #[cfg(not(unix))]
        let _ = home;
        let path = std::env::join_paths(paths)?;
        let mut profile = Self::load_with_path(config, Some(&path))?;
        if let Some(vars) = environment.as_object() {
            for (name, value) in vars {
                let value =
                    value
                        .as_str()
                        .filter(|value| !value.contains('\0'))
                        .ok_or(ReviewError(
                            "The configured environment requires client-specific expansion.",
                        ))?;
                if name.is_empty() || name.contains(['\0', '=']) || value.contains("${") {
                    return Err(ReviewError(
                        "The configured environment requires client-specific expansion.",
                    )
                    .into());
                }
                profile.environment.insert(name.clone(), value.to_owned());
                if value.len() >= 8
                    && !BASE_ENV.contains(&name.as_str())
                    && !PATH_ENV.contains(&name.as_str())
                {
                    profile.secrets.push(value.to_owned());
                }
            }
        } else if !environment.is_null() {
            return Err(ReviewError("Expected an environment object.").into());
        }
        Ok(profile)
    }

    fn environment_binding(&self) -> &BTreeMap<String, String> {
        self.environment_binding.get_or_init(|| {
            self.environment
                .iter()
                .map(|(name, value)| {
                    let value = if BASE_ENV.contains(&name.as_str()) {
                        value.clone()
                    } else {
                        let context = [b"env\0", name.as_bytes()].concat();
                        identity_kdf(&self.source, &context, value)
                    };
                    (name.clone(), value)
                })
                .collect()
        })
    }

    pub fn identity(&self) -> Result<String> {
        // Hash the exact local binding and any direct executable or file arguments.
        let mut hashes = BTreeMap::new();
        let mut remaining = 256 * 1024 * 1024;
        for path in std::iter::once(self.executable.clone())
            .chain(self.args.iter().map(|arg| self.cwd.join(arg)))
        {
            if !path.is_file() {
                continue;
            }
            let mut file = std::fs::File::open(&path)?;
            let before = file.metadata()?;
            if before.len() > remaining {
                return Err(ReviewError("Configured files exceed the identity hash limit.").into());
            }
            let mut digest = Sha256::new();
            let mut buffer = [0; 65536];
            let mut size = 0;
            let mut reader = (&mut file).take(remaining + 1);
            loop {
                let count = reader.read(&mut buffer)?;
                if count == 0 {
                    break;
                }
                digest.update(&buffer[..count]);
                size += count as u64;
            }
            let after = file.metadata()?;
            if size > remaining || size != before.len() || before.modified()? != after.modified()? {
                return Err(
                    ReviewError("A configured file changed during catalog discovery.").into(),
                );
            }
            remaining -= size;
            hashes.insert(path, format!("{:x}", digest.finalize()));
        }
        let identity = json!({"executable": self.executable, "argv": self.args, "cwd": self.cwd,
            "protocol": self.version, "environment": self.environment_binding(), "files": hashes});
        Ok(format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&identity)?)
        ))
    }
}

fn codex_gateway_path(search: &std::ffi::OsStr, home: &Path) -> Result<std::ffi::OsString> {
    let shims = home.join("tmp/arg0");
    // Codex adds private command aliases and its bundled rg to the child search path.
    // Upstreams resolve commands against the remaining path.
    Ok(std::env::join_paths(std::env::split_paths(search).filter(
        |entry| {
            let session_shim = entry.parent() == Some(shims.as_path())
                && entry
                    .file_name()
                    .is_some_and(|name| name.to_string_lossy().starts_with("codex-arg0"));
            let packaged_tools = entry.file_name().is_some_and(|name| name == "codex-path")
                && entry
                    .parent()
                    .and_then(Path::parent)
                    .and_then(Path::parent)
                    .is_some_and(|parent| parent.ends_with("packages/standalone"));
            !session_shim && !packaged_tools
        },
    ))?)
}

// Windows runs commands such as `node` or `npx` from `node.exe` or `npx.cmd`.
// Match the extensions used for harness detection.
#[cfg(windows)]
const EXECUTABLE_EXTENSIONS: &[&str] = &["exe", "cmd", "bat"];
#[cfg(not(windows))]
const EXECUTABLE_EXTENSIONS: &[&str] = &[];

fn executable_names(path: &Path, extensions: &[&str]) -> Vec<PathBuf> {
    if extensions.is_empty() || path.extension().is_some() {
        vec![path.to_path_buf()]
    } else {
        extensions
            .iter()
            .map(|extension| path.with_extension(extension))
            .collect()
    }
}

fn resolve_executable(
    path: &Path,
    cwd: &Path,
    search: Option<&std::ffi::OsStr>,
) -> Result<PathBuf> {
    let mut candidates = Vec::new();
    if path.is_absolute() || path.components().count() > 1 {
        candidates.extend(executable_names(&cwd.join(path), EXECUTABLE_EXTENSIONS));
    } else if let Some(search) = search
        .map(std::ffi::OsStr::to_os_string)
        .or_else(|| std::env::var_os("PATH"))
    {
        candidates
            .extend(std::env::split_paths(&search).flat_map(|dir| {
                executable_names(&cwd.join(dir).join(path), EXECUTABLE_EXTENSIONS)
            }));
    }
    candidates
        .into_iter()
        .find(|path| {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                path.metadata()
                    .is_ok_and(|stat| stat.is_file() && stat.permissions().mode() & 0o111 != 0)
            }
            #[cfg(not(unix))]
            path.is_file()
        })
        .ok_or_else(|| ReviewError("The configured executable is unavailable.").into())
}

fn strings(value: &Value) -> Result<Vec<String>> {
    let values = value
        .as_array()
        .ok_or(ReviewError("Expected an array of strings."))?;
    values
        .iter()
        .map(|item| {
            item.as_str()
                .filter(|text| !text.is_empty() && !text.contains('\0'))
                .map(str::to_owned)
                .ok_or_else(|| ReviewError("Invalid profile string.").into())
        })
        .collect()
}

pub struct Peer {
    profile: Profile,
    identity: String,
    child: Child,
    stdin: ChildStdin,
    messages: mpsc::Receiver<PeerMessage>,
    changed: Arc<Notify>,
    reader: tokio::task::JoinHandle<()>,
    sequence: u64,
    codex_catalog: bool,
}

impl Peer {
    pub fn open(profile: Profile) -> Result<Self> {
        Self::open_wire(profile, false)
    }

    pub fn open_codex_catalog(profile: Profile) -> Result<Self> {
        Self::open_wire(profile, true)
    }

    fn open_wire(profile: Profile, codex_catalog: bool) -> Result<Self> {
        let identity = profile.identity()?;
        let mut command = Command::new(&profile.executable);
        command
            .args(&profile.args)
            .current_dir(&profile.cwd)
            .env_clear()
            .envs(&profile.environment)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        #[cfg(unix)]
        command.process_group(0);
        let mut child = command.spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or(ReviewError("Missing server input pipe."))?;
        let stdout = child
            .stdout
            .take()
            .ok_or(ReviewError("Missing server output pipe."))?;
        let changed = Arc::new(Notify::new());
        let (sender, messages) = mpsc::channel(32);
        let reader = tokio::spawn(read_peer(
            stdout,
            sender,
            changed.clone(),
            profile.max_line,
            codex_catalog,
        ));
        Ok(Self {
            profile,
            identity,
            child,
            stdin,
            messages,
            changed,
            reader,
            sequence: 0,
            codex_catalog,
        })
    }

    pub fn identity(&self) -> &str {
        &self.identity
    }
    pub fn source(&self) -> &str {
        &self.profile.source
    }
    pub fn version(&self) -> &str {
        &self.profile.version
    }
    pub fn timeout(&self) -> Duration {
        self.profile.timeout
    }
    pub fn catalog_limits(&self) -> (usize, usize, usize) {
        self.profile.catalog_limits
    }
    pub fn changed(&self) -> Arc<Notify> {
        self.changed.clone()
    }
    pub fn contains_secret(&self, value: &Value) -> bool {
        contains_secret(value, &self.profile.secrets)
    }

    pub fn connected(&self) -> bool {
        !self.reader.is_finished()
    }

    pub fn verify(&self) -> Result<()> {
        if self.reader.is_finished() || self.profile.identity()? != self.identity {
            return Err(ReviewError(
                "Upstream disconnected or its identity changed. Reconnect and review.",
            )
            .into());
        }
        Ok(())
    }

    async fn send(&mut self, message: &Value) -> Result<()> {
        let mut encoded = serde_json::to_vec(message)?;
        if encoded.len() as u64 >= self.profile.max_line {
            return Err(ReviewError("MCP request exceeds its byte limit.").into());
        }
        encoded.push(b'\n');
        self.stdin.write_all(&encoded).await?;
        self.stdin.flush().await?;
        Ok(())
    }

    pub async fn notify(&mut self, method: &str) -> Result<()> {
        let message = if self.codex_catalog {
            json!({"method":method,"params":{}})
        } else {
            json!({"jsonrpc":"2.0","method":method})
        };
        tokio::time::timeout(self.timeout(), self.send(&message))
            .await
            .map_err(|_| ReviewError("MCP notification timed out."))?
    }

    pub async fn request(&mut self, method: &str, params: Value) -> Result<Value> {
        let timeout = self.timeout();
        tokio::time::timeout(timeout, self.exchange(method, params))
            .await
            .map_err(|_| ReviewError("MCP request timed out."))?
    }

    async fn exchange(&mut self, method: &str, params: Value) -> Result<Value> {
        self.sequence += 1;
        let id = self.sequence;
        let mut message = json!({"id":id,"method":method,"params":params});
        if !self.codex_catalog {
            message["jsonrpc"] = json!("2.0");
        }
        self.send(&message).await?;
        let message = loop {
            let message = self
                .messages
                .recv()
                .await
                .ok_or(ReviewError("MCP server disconnected."))?
                .map_err(ReviewError)?;
            // A late reply to an earlier request that timed out is discarded.
            if message.get("method").is_none()
                && message["id"].as_u64().is_some_and(|earlier| earlier < id)
            {
                continue;
            }
            break message;
        };
        if message["id"].as_u64() != Some(id)
            || message.get("method").is_some()
            || message.get("error").is_some()
            || !message["result"].is_object()
        {
            return Err(ReviewError(
                "MCP server rejected the request or returned an invalid response.",
            )
            .into());
        }
        Ok(message["result"].clone())
    }
}

impl Drop for Peer {
    fn drop(&mut self) {
        self.reader.abort();
        #[cfg(unix)]
        if let Some(id) = self.child.id() {
            // The group was created for this child when spawned.
            unsafe {
                libc::kill(-(id as libc::pid_t), libc::SIGKILL);
            }
        }
        let _ = self.child.start_kill();
    }
}

async fn read_peer(
    stdout: ChildStdout,
    sender: mpsc::Sender<PeerMessage>,
    changed: Arc<Notify>,
    limit: u64,
    codex_catalog: bool,
) {
    let mut stdout = BufReader::new(stdout);
    let mut line = Vec::new();
    loop {
        line.clear();
        let read = (&mut stdout)
            .take(limit + 1)
            .read_until(b'\n', &mut line)
            .await;
        if !matches!(read, Ok(bytes) if bytes > 0 && bytes as u64 <= limit)
            || line.last() != Some(&b'\n')
        {
            let _ = sender.try_send(Err("MCP output ended or exceeded its framing limit."));
            break;
        }
        let Ok(message) = crate::input::parse(&line) else {
            let _ = sender.try_send(Err("Invalid upstream MCP JSON."));
            break;
        };
        if message["jsonrpc"] != "2.0" && !(codex_catalog && message.get("jsonrpc").is_none()) {
            let _ = sender.try_send(Err("MCP response uses invalid framing."));
            break;
        }
        if message.get("id").is_none() {
            if codex_catalog && message["method"].is_string() {
                continue;
            }
            match message["method"].as_str() {
                Some("notifications/tools/list_changed") => {
                    changed.notify_one();
                    continue;
                }
                Some("notifications/progress" | "notifications/message") => continue,
                _ => {}
            }
        }
        if sender.try_send(Ok(message)).is_err() {
            break;
        }
    }
    changed.notify_one();
}

fn contains_secret(value: &Value, secrets: &[String]) -> bool {
    match value {
        Value::String(text) => secrets.iter().any(|secret| text.contains(secret)),
        Value::Array(items) => items.iter().any(|item| contains_secret(item, secrets)),
        Value::Object(items) => items.iter().any(|(key, item)| {
            secrets.iter().any(|secret| key.contains(secret)) || contains_secret(item, secrets)
        }),
        _ => false,
    }
}

pub async fn scan(path: &Path) -> Result<(String, String, Vec<Value>)> {
    let config = Profile::parse_file(path)?;
    let mut upstream = crate::gateway::Upstream::open(&config)?;
    let source = format!("{}:{}", upstream.transport(), upstream.source());
    let identity = upstream.identity().to_owned();
    let timeout = upstream.timeout();
    tokio::time::timeout(timeout, async {
        upstream.initialize().await?;
        let tools = upstream.catalog().await?;
        upstream.verify()?;
        Ok((source, identity, tools))
    })
    .await
    .map_err(|_| ReviewError("MCP catalog discovery timed out."))?
}

#[cfg(test)]
#[test]
fn windows_executable_names_add_launch_extensions_only_when_missing() {
    let extensions = ["exe", "cmd", "bat"];
    assert_eq!(
        executable_names(Path::new("bin/npx"), &extensions),
        ["bin/npx.exe", "bin/npx.cmd", "bin/npx.bat"].map(PathBuf::from)
    );
    assert_eq!(
        executable_names(Path::new("bin/codex.exe"), &extensions),
        [PathBuf::from("bin/codex.exe")]
    );
    assert_eq!(
        executable_names(Path::new("bin/node"), &[]),
        [PathBuf::from("bin/node")]
    );
}

#[cfg(test)]
#[test]
fn codex_gateway_search_path_drops_only_session_shims() {
    let home = Path::new("/fixture/.codex");
    let first = home.join("tmp/arg0/codex-arg0first");
    let second = home.join("tmp/arg0/codex-arg0second");
    let unrelated = Path::new("/fixture/tools/codex-arg0custom");
    let bundled = Path::new("/fixture/.codex/packages/standalone/releases/1.0/codex-path");
    let search =
        std::env::join_paths([first.as_path(), unrelated, second.as_path(), bundled]).unwrap();
    let filtered = codex_gateway_path(&search, home).unwrap();
    assert_eq!(
        std::env::split_paths(&filtered).collect::<Vec<_>>(),
        vec![unrelated]
    );
}

#[cfg(test)]
#[test]
fn identity_kdf_is_salted_pbkdf2_sha256() {
    // Independent vector from Python's hashlib.pbkdf2_hmac with the same salt layout.
    assert_eq!(
        identity_kdf("fixture", b"env\0API_KEY", "hunter22"),
        "a77dd0b33d96d3e234523879ae6464597c451bf9154c8dd4ac67c11cebae891d"
    );
    assert_ne!(
        identity_kdf("fixture", b"env\0API_KEY", "hunter22"),
        identity_kdf("other", b"env\0API_KEY", "hunter22")
    );
    assert_ne!(
        identity_kdf("fixture", b"env\0API_KEY", "hunter22"),
        identity_kdf("fixture", b"env\0OTHER_KEY", "hunter22")
    );
}

#[cfg(test)]
fn catalog_profile(environment: Value) -> Profile {
    let cwd = std::env::temp_dir().canonicalize().unwrap();
    let executable = std::env::current_exe().unwrap();
    Profile::for_catalog(
        &json!({"server_id": "fixture", "argv": [executable], "cwd": cwd}),
        &environment,
        &cwd,
    )
    .unwrap()
}

#[cfg(test)]
#[test]
fn identity_binds_derived_secrets_not_raw_environment_values() {
    let profile = catalog_profile(json!({"API_KEY": "hunter22"}));
    let binding = profile.environment_binding();
    assert_eq!(
        binding["API_KEY"],
        identity_kdf("fixture", b"env\0API_KEY", "hunter22")
    );
    assert_eq!(binding["PATH"], profile.environment["PATH"]);
    let identity = profile.identity().unwrap();
    assert_eq!(profile.identity().unwrap(), identity);
    assert_ne!(
        catalog_profile(json!({"API_KEY": "hunter23"}))
            .identity()
            .unwrap(),
        identity
    );
}

#[cfg(test)]
#[test]
fn codex_home_path_is_not_treated_as_a_secret() {
    let profile = catalog_profile(json!({
        "CODEX_HOME": "/fixture/home/.codex", "API_KEY": "hunter22"
    }));
    assert_eq!(profile.secrets, ["hunter22"]);
    assert!(!contains_secret(
        &json!({"description": "Reads /fixture/home/.codex/config.toml"}),
        &profile.secrets
    ));
    assert!(contains_secret(&json!(["hunter22"]), &profile.secrets));
}
