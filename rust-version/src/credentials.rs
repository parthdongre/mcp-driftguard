use std::error::Error;

use crate::review::ReviewError;
use sha2::{Digest, Sha256};

type Result<T> = std::result::Result<T, Box<dyn Error>>;
const SERVICE: &str = "io.driftguard.desktop.http";
const UNAVAILABLE: ReviewError =
    ReviewError("The operating system credential store is unavailable or locked.");
const MAX_STORED_BYTES: usize = 8192;

fn account(server_id: &str, endpoint: &str, https_only: bool) -> Result<String> {
    if server_id.is_empty()
        || server_id.len() > 128
        || !server_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
    {
        return Err(ReviewError("Invalid credential server ID.").into());
    }
    crate::http::endpoint(endpoint, !https_only)?;
    let mut hash = Sha256::new();
    hash.update(server_id.as_bytes());
    hash.update([0]);
    hash.update(endpoint.as_bytes());
    Ok(format!("{:x}", hash.finalize()))
}

fn valid_secret(secret: &str, limit: usize) -> bool {
    (8..=limit).contains(&secret.len()) && secret.bytes().all(|byte| (33..=126).contains(&byte))
}

pub fn read(server_id: &str, endpoint: &str) -> Result<Option<String>> {
    let identity = account(server_id, endpoint, false)?;
    platform::read(&identity)?
        .map(|secret| {
            if valid_secret(&secret, MAX_STORED_BYTES) {
                Ok(secret)
            } else {
                Err(ReviewError("The stored bearer credential is invalid.").into())
            }
        })
        .transpose()
}

pub fn write(server_id: &str, endpoint: &str, secret: Option<&str>) -> Result<()> {
    if secret.is_some_and(|secret| !valid_secret(secret, 2048)) {
        return Err(ReviewError(
            "A bearer credential must contain 8–2048 printable non-space ASCII characters.",
        )
        .into());
    }
    platform::write(&account(server_id, endpoint, true)?, secret)
}

#[cfg(target_os = "macos")]
mod platform {
    use security_framework::os::macos::keychain::SecKeychain;
    use security_framework::os::macos::passwords::find_generic_password;
    use security_framework::passwords::delete_generic_password;

    use super::*;

    const NOT_FOUND: i32 = -25300;

    pub fn read(identity: &str) -> Result<Option<String>> {
        match find_generic_password(None, SERVICE, identity) {
            Ok((password, _)) if password.len() <= MAX_STORED_BYTES => {
                let secret = std::str::from_utf8(password.as_ref()).map_err(|_| UNAVAILABLE)?;
                Ok(Some(secret.to_owned()))
            }
            Err(error) if error.code() == NOT_FOUND => Ok(None),
            _ => Err(UNAVAILABLE.into()),
        }
    }

    pub fn write(identity: &str, secret: Option<&str>) -> Result<()> {
        match secret {
            Some(secret) => match find_generic_password(None, SERVICE, identity) {
                Ok((_, mut item)) => item.set_password(secret.as_bytes()),
                Err(error) if error.code() == NOT_FOUND => {
                    SecKeychain::default().and_then(|keychain| {
                        keychain.add_generic_password(SERVICE, identity, secret.as_bytes())
                    })
                }
                Err(error) => Err(error),
            }
            .map_err(|_| UNAVAILABLE.into()),
            None => match delete_generic_password(SERVICE, identity) {
                Ok(()) => Ok(()),
                Err(error) if error.code() == NOT_FOUND => Ok(()),
                Err(_) => Err(UNAVAILABLE.into()),
            },
        }
    }
}

#[cfg(windows)]
mod platform {
    use std::{ptr, slice};

    use windows_sys::Win32::Foundation::{GetLastError, ERROR_NOT_FOUND};
    use windows_sys::Win32::Security::Credentials::{
        CredDeleteW, CredFree, CredReadW, CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE,
        CRED_TYPE_GENERIC,
    };

    use super::*;

    struct ReadCredential(*mut CREDENTIALW);

    impl Drop for ReadCredential {
        fn drop(&mut self) {
            // CredReadW transfers ownership of this allocation to the caller.
            unsafe { CredFree(self.0.cast()) };
        }
    }

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain([0]).collect()
    }

    fn target(identity: &str) -> Vec<u16> {
        wide(&format!("{SERVICE}:{identity}"))
    }

    pub fn read(identity: &str) -> Result<Option<String>> {
        let target = target(identity);
        let mut credential = ptr::null_mut();
        // The target remains NUL terminated and valid for the duration of this call.
        if unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut credential) } == 0 {
            return if unsafe { GetLastError() } == ERROR_NOT_FOUND {
                Ok(None)
            } else {
                Err(UNAVAILABLE.into())
            };
        }
        if credential.is_null() {
            return Err(UNAVAILABLE.into());
        }
        let owner = ReadCredential(credential);
        // The pointer and blob belong to the Windows allocation until owner drops.
        let item = unsafe { &*owner.0 };
        let size = item.CredentialBlobSize as usize;
        if size == 0 || size > MAX_STORED_BYTES || item.CredentialBlob.is_null() {
            return Err(UNAVAILABLE.into());
        }
        let bytes = unsafe { slice::from_raw_parts(item.CredentialBlob, size) };
        let secret = std::str::from_utf8(bytes).map_err(|_| UNAVAILABLE)?;
        Ok(Some(secret.to_owned()))
    }

    pub fn write(identity: &str, secret: Option<&str>) -> Result<()> {
        let mut target = target(identity);
        let Some(secret) = secret else {
            // Windows consumes the NUL-terminated target during the call.
            let result = unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) };
            return if result != 0 || unsafe { GetLastError() } == ERROR_NOT_FOUND {
                Ok(())
            } else {
                Err(UNAVAILABLE.into())
            };
        };
        let mut username = wide(identity);
        let mut bytes = secret.as_bytes().to_vec();
        let credential = CREDENTIALW {
            Type: CRED_TYPE_GENERIC,
            TargetName: target.as_mut_ptr(),
            CredentialBlobSize: bytes.len() as u32,
            CredentialBlob: bytes.as_mut_ptr(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            UserName: username.as_mut_ptr(),
            ..Default::default()
        };
        // All buffers are valid until the synchronous CredWriteW call returns.
        if unsafe { CredWriteW(&credential, 0) } != 0 {
            Ok(())
        } else {
            Err(UNAVAILABLE.into())
        }
    }
}

#[cfg(all(unix, not(target_os = "macos")))]
mod platform {
    use std::io::{self, Read, Write};
    use std::os::fd::AsRawFd;
    use std::os::unix::process::CommandExt;
    use std::process::{Child, Command, Stdio};
    use std::time::{Duration, Instant};

    use super::*;

    const TIMEOUT: Duration = Duration::from_secs(20);
    const POLL: Duration = Duration::from_millis(10);

    #[derive(Clone, Copy)]
    enum Operation<'a> {
        Read,
        Write(&'a str),
        Delete,
    }

    pub fn read(identity: &str) -> Result<Option<String>> {
        exchange(
            Command::new("secret-tool"),
            identity,
            Operation::Read,
            TIMEOUT,
        )
    }

    pub fn write(identity: &str, secret: Option<&str>) -> Result<()> {
        let operation = secret.map_or(Operation::Delete, Operation::Write);
        exchange(Command::new("secret-tool"), identity, operation, TIMEOUT)?;
        Ok(())
    }

    fn exchange(
        mut command: Command,
        identity: &str,
        operation: Operation<'_>,
        timeout: Duration,
    ) -> Result<Option<String>> {
        match operation {
            Operation::Read => command.arg("lookup"),
            Operation::Write(_) => command.args(["store", "--label=MCP DriftGuard"]),
            Operation::Delete => command.arg("clear"),
        };
        let mut child = SecretTool {
            process: command
                .args(["service", SERVICE, "account", identity])
                .stdin(if matches!(operation, Operation::Write(_)) {
                    Stdio::piped()
                } else {
                    Stdio::null()
                })
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .process_group(0)
                .spawn()
                .map_err(|_| UNAVAILABLE)?,
            reaped: false,
        };
        let deadline = Instant::now() + timeout;
        if let Operation::Write(secret) = operation {
            let input = child.process.stdin.take().ok_or(UNAVAILABLE)?;
            write_secret(input, secret, deadline)?;
        }
        let mut output = child.process.stdout.take().ok_or(UNAVAILABLE)?;
        nonblocking(&output)?;

        let mut bytes = Vec::new();
        let mut buffer = [0; 1024];
        let mut eof = false;
        while Instant::now() < deadline {
            if !eof {
                match output.read(&mut buffer) {
                    Ok(0) => eof = true,
                    Ok(count) if bytes.len() + count <= MAX_STORED_BYTES + 1 => {
                        bytes.extend_from_slice(&buffer[..count]);
                        continue;
                    }
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
                    _ => return Err(UNAVAILABLE.into()),
                }
            }
            // Keep the child unreaped while output is open. A descendant may
            // have inherited the pipe and still need process-group cleanup.
            if let Some(status) = if eof {
                child.process.try_wait().map_err(|_| UNAVAILABLE)?
            } else {
                None
            } {
                child.reaped = true;
                return if matches!(operation, Operation::Read) && status.code() == Some(1) {
                    Ok(None)
                } else if !status.success() {
                    Err(UNAVAILABLE.into())
                } else if matches!(operation, Operation::Read) {
                    let value = String::from_utf8(bytes).map_err(|_| UNAVAILABLE)?;
                    Ok(Some(value.trim_end_matches('\n').to_owned()))
                } else {
                    Ok(None)
                };
            }
            pause(deadline);
        }
        Err(UNAVAILABLE.into())
    }

    fn write_secret(
        mut input: impl Write + AsRawFd,
        secret: &str,
        deadline: Instant,
    ) -> Result<()> {
        nonblocking(&input)?;
        let line = format!("{secret}\n");
        let mut remaining = line.as_bytes();
        while !remaining.is_empty() && Instant::now() < deadline {
            match input.write(remaining) {
                Ok(count) if count > 0 => remaining = &remaining[count..],
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => pause(deadline),
                _ => return Err(UNAVAILABLE.into()),
            }
        }
        if remaining.is_empty() {
            Ok(())
        } else {
            Err(UNAVAILABLE.into())
        }
    }

    fn pause(deadline: Instant) {
        std::thread::sleep(POLL.min(deadline.saturating_duration_since(Instant::now())));
    }

    fn nonblocking(pipe: &impl AsRawFd) -> Result<()> {
        let fd = pipe.as_raw_fd();
        // The caller owns this file descriptor until the calls return.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags == -1 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } == -1
        {
            return Err(UNAVAILABLE.into());
        }
        Ok(())
    }

    struct SecretTool {
        process: Child,
        reaped: bool,
    }

    impl Drop for SecretTool {
        fn drop(&mut self) {
            if !self.reaped {
                // The child owns its process group and its PID has not been reaped.
                unsafe { libc::kill(-(self.process.id() as libc::pid_t), libc::SIGKILL) };
                let _ = self.process.wait();
            }
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn helper_gets_secret_only_through_stdin() {
            let mut helper = Command::new("/bin/sh");
            helper.args([
                "-c",
                "test \"$1\" = store && test \"$4\" = io.driftguard.desktop.http && test \"$6\" = fixture-account && IFS= read -r secret && test \"$secret\" = authored-fixture-token",
                "fixture",
            ]);
            assert!(exchange(
                helper,
                "fixture-account",
                Operation::Write("authored-fixture-token"),
                Duration::from_secs(1)
            )
            .is_ok());
        }

        #[test]
        fn lookup_bounds_waiting_and_output() {
            for script in ["sleep 5", "sleep 5 &", "head -c 9000 /dev/zero"] {
                let mut helper = Command::new("/bin/sh");
                helper.args(["-c", script]);
                let start = Instant::now();
                assert!(exchange(
                    helper,
                    "fixture",
                    Operation::Read,
                    Duration::from_millis(150)
                )
                .is_err());
                assert!(start.elapsed() < Duration::from_secs(2));
            }
        }
    }
}

#[cfg(not(any(unix, windows)))]
mod platform {
    use super::*;

    pub fn read(_: &str) -> Result<Option<String>> {
        Err(UNAVAILABLE.into())
    }

    pub fn write(_: &str, _: Option<&str>) -> Result<()> {
        Err(UNAVAILABLE.into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn account_matches_python_and_binds_exact_endpoint() {
        let identity = account("fixture", "https://example.com/mcp", true).unwrap();
        assert_eq!(
            identity,
            "cf6b5ef1d5a1dc61fe440a96a3fad3db7559ad3fc759f53ea8a6a315dc77b8c0"
        );
        assert_ne!(
            identity,
            account("fixture", "https://example.com/mcp/", true).unwrap()
        );
        assert_ne!(
            identity,
            account("different", "https://example.com/mcp", true).unwrap()
        );
    }

    #[test]
    fn rejects_untrusted_endpoint_forms_and_invalid_tokens() {
        assert!(account("fixture", "http://127.0.0.1:8080/mcp", true).is_err());
        assert!(account("fixture", "http://127.0.0.1:8080/mcp", false).is_ok());
        assert!(account("fixture", "http://127.1:8080/mcp", false).is_err());
        assert!(account("fixture", "https://@example.com/mcp", true).is_err());
        assert!(account("fixture", "https://example.com/mcp?secret=x", true).is_err());
        assert!(write("fixture", "https://example.com/mcp", Some("invalid token")).is_err());
    }
}
