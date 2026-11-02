export interface RuntimeInfo {
  gateway_argv: string[] | null;
  state_path: string;
  packaged: boolean;
  engine_available: boolean;
}

export function absolutePath(value: string): boolean {
  return /^(?:\/|[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)/.test(value) && !/[\u0000-\u001f]/.test(value);
}

export function buildProfile(server: string, argvText: string, cwd: string, protocol: string, envText: string) {
  if (!/^[A-Za-z0-9_.-]{1,128}$/.test(server)) throw new Error('Use a short source name with letters, digits, dots, underscores or hyphens.');
  let argv: unknown;
  try { argv = JSON.parse(argvText); } catch { throw new Error('Enter the command as a JSON array of strings.'); }
  if (!Array.isArray(argv) || !argv.length || argv.length > 64 ||
      argv.some(arg => typeof arg !== 'string' || !arg || /[\u0000]/.test(arg)) ||
      argvText.length > 16000) throw new Error('The command must contain 1–64 nonempty strings within 16,000 characters.');
  if (!absolutePath(cwd)) throw new Error('Choose an absolute working-directory path.');
  if (!['2025-11-25', '2026-07-28'].includes(protocol)) throw new Error('Select an explicitly supported protocol.');
  const pass_env = envText.split(',').map(name => name.trim()).filter(Boolean);
  if (pass_env.length > 32 || pass_env.some(name => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name))) throw new Error('Enter environment variable names separated by commas, without their values.');
  return { server_id: server, argv: argv as string[], cwd, protocol_version: protocol, pass_env: [...new Set(pass_env)] };
}

export function buildClientConfig(runtime: RuntimeInfo, profilePath: string, server: string) {
  if (!/^[A-Za-z0-9_.-]{1,128}$/.test(server)) throw new Error('Use a short source identifier.');
  if (!runtime.engine_available || !runtime.gateway_argv?.length) throw new Error('Install the packaged engine before creating a client connection.');
  if (!absolutePath(profilePath) || !absolutePath(runtime.state_path)) throw new Error('Enter the absolute path where you saved the source profile.');
  const [command, ...args] = runtime.gateway_argv;
  return { mcpServers: { [server]: { command, args: [...args, 'serve', '--config', profilePath, '--state', runtime.state_path] } } };
}

export function buildClientSetup(runtime: RuntimeInfo, profilePath: string, server: string, target: string) {
  const config = buildClientConfig(runtime, profilePath, server);
  if (target === 'claude') return { text: JSON.stringify(config, null, 2), filename: 'driftguard-claude-code.json', type: 'application/json' };
  if (target !== 'codex') throw new Error('Choose Codex or Claude Code.');
  const entry = config.mcpServers[server];
  return { text: `[mcp_servers.${JSON.stringify(server)}]\ncommand = ${JSON.stringify(entry.command)}\nargs = ${JSON.stringify(entry.args)}\nstartup_timeout_sec = 90\n`,
    filename: 'driftguard-codex.toml', type: 'text/plain' };
}

export function buildHttpProfile(server: string, endpoint: string, protocol: string, auth: string, envName: string) {
  if (!/^[A-Za-z0-9_.-]{1,128}$/.test(server)) throw new Error('Use a short source identifier.');
  const url = new URL(endpoint);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || /[\u0000-\u0020\u007f]/.test(endpoint)) throw new Error('Use an HTTPS endpoint without embedded credentials, query or fragment.');
  if (!['2025-11-25', '2026-07-28'].includes(protocol)) throw new Error('Select a supported protocol.');
  if (!['none', 'environment', 'vault'].includes(auth)) throw new Error('Select an authentication source.');
  if (auth === 'environment' && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(envName)) throw new Error('Enter an environment variable name without its value.');
  return { server_id: server, transport: 'http' as const, url: endpoint, protocol_version: protocol,
    ...(auth === 'environment' ? { auth_token_env: envName } : {}),
    ...(auth === 'vault' ? { use_os_vault: true } : {}) };
}
