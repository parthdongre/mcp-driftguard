import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { request } from './bridge';
import { Disclosure } from './Disclosure';
import type { BridgeRequest } from './types';

export function gatewayState(state: string) {
  switch (state) {
    case 'catalog_ready': return 'Catalog ready';
    case 'sign_in_required': return 'Authentication required';
    case 'access_denied': return 'Access denied';
    case 'startup_failed': return 'Codex startup failed';
    case 'unavailable': return 'Unavailable';
    default: return 'Configured';
  }
}

interface Server {
  server_id: string;
  transport: 'http' | 'stdio' | 'codex_hosted';
  url?: string;
  use_os_vault: boolean;
  state: string;
  command: string;
  args: string[];
}

export function GatewayServers({ onChanged }: { onChanged: () => void }) {
  const harnesses = [['codex', 'Codex'], ['claude', 'Claude Code'], ['cursor', 'Cursor'],
    ['antigravity', 'Antigravity'], ['gemini', 'Gemini CLI'], ['opencode', 'OpenCode'], ['vscode', 'VS Code / Copilot']];
  const [harness, setHarness] = useState('codex');
  const [launchCommand, setLaunchCommand] = useState('');
  const [servers, setServers] = useState<Server[]>([]);
  const [name, setName] = useState('');
  const [transport, setTransport] = useState<'http' | 'stdio'>('http');
  const [url, setUrl] = useState('');
  const [program, setProgram] = useState('');
  const [args, setArgs] = useState('');
  const [env, setEnv] = useState('');
  const [cwd, setCwd] = useState('');
  const [vault, setVault] = useState(false);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let mounted = true;
    void request<Server[]>({ action: 'gateway_servers' }).then(result => {
      if (mounted) setServers(result);
    }).catch(() => {
      if (mounted) { setFailed(true); setMessage('Could not load gateway servers.'); }
    });
    return () => { mounted = false; };
  }, []);

  const run = async (operation: () => Promise<Server[]>, success: string) => {
    setBusy(true); setFailed(false); setMessage('');
    try {
      setServers(await operation());
      setMessage(success);
      onChanged();
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : 'The gateway operation failed.');
    } finally { setBusy(false); }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const id = name.trim();
    const payload: BridgeRequest = { action: 'save_gateway_server', server_id: id, transport };
    if (transport === 'http') {
      Object.assign(payload, { url: url.trim(), use_os_vault: vault });
    } else {
      Object.assign(payload, { argv: [program.trim(), ...args.split('\n').filter(Boolean)],
        pass_env: env.split(/[,\s]+/).filter(Boolean), cwd: cwd.trim() || undefined });
    }
    void run(async () => {
      if (transport === 'http' && vault && token) {
        await request({ action: 'store_http_credential', server_id: id, url: url.trim(), secret: token });
        setToken('');
      }
      const saved = await request<Server[]>(payload);
      setServers(saved);
      onChanged();
      return request<Server[]>({ action: 'check_gateway_server', server_id: id });
    }, 'Server saved. Check its status below.');
  };

  const launchGatewayOnly = async () => {
    setBusy(true); setFailed(false); setMessage('Checking Codex routes…');
    setLaunchCommand('');
    try {
      const result = await request<{ command?: string; opened: boolean; skipped: Pick<Server, 'server_id' | 'state'>[] }>({
        action: 'launch_gateway_only_codex', open_terminal: navigator.platform.startsWith('Mac'),
      });
      const skipped = result.skipped.map(server => `${server.server_id} (${gatewayState(server.state)})`).join(', ');
      if (!result.opened && !result.command) {
        setFailed(true);
        setMessage(`No gateway servers are ready. ${skipped}. Resolve the listed issues, then run Check catalog.`);
        return;
      }
      if (!result.opened && result.command) setLaunchCommand(result.command);
      const status = result.opened ? 'Opened verified gateway-only Codex in Terminal.' : 'Verified routes. Run the command below.';
      setMessage(skipped ? `${status} Skipped ${skipped}.` : status);
    } catch (error) {
      setFailed(true); setMessage(error instanceof Error ? error.message : 'Could not verify Codex routes.');
    } finally { setBusy(false); }
  };

  return <section className="panel compact-panel" aria-labelledby="gateway-servers-heading">
    <div className="section-heading"><h2 id="gateway-servers-heading">Gateway servers</h2>
      <button className="button primary" disabled={busy || !servers.length}
        onClick={() => void launchGatewayOnly()}>Launch gateway-only Codex</button></div>
    <p className="mcp-activity-note muted">Gateway-only Codex starts in a clean, read-only workspace and uses a separate sign-in.</p>
    {launchCommand ? <pre className="mcp-activity-note">{launchCommand}</pre> : null}
    <div className="mcp-activity-note">
      <button className="button subtle" disabled={busy} onClick={() => void run(
        () => request({ action: 'register_codex_hosted' }),
        'Checked the signed-in Codex hosted catalog. See codex-hosted below.',
      )}>Connect Codex hosted apps</button>
    </div>
    {servers.length ? <ul className="managed-harness-list">{servers.map(server =>
      <li key={server.server_id}>
        <div><strong>{server.server_id}</strong><span>{gatewayState(server.state)}</span>
          <Disclosure title="Harness configuration">
            <p>Add this stdio entry to your client’s MCP settings and open a new session.</p>
            <pre>{JSON.stringify({ command: server.command, args: server.args }, null, 2)}</pre>
          </Disclosure>
        </div>
        <div className="managed-harness-actions">
          <label className="mcp-setting-toggle">Harness
            <select aria-label={`Harness for ${server.server_id}`} value={harness} disabled={busy}
              onChange={event => setHarness(event.target.value)}>
              {harnesses.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <button className="button subtle" disabled={busy} onClick={() => void run(() => request({
            action: 'link_gateway_server', server_id: server.server_id, harness,
          }), 'Gateway added to the selected harness. Open a new harness session.')}>Add to harness</button>
          <button className="button subtle" disabled={busy} onClick={() => void run(() => request({
            action: 'check_gateway_server', server_id: server.server_id,
          }), 'Catalog check finished.')}>Check catalog</button>
          <button className="button subtle" disabled={busy} onClick={() => void run(() => request({
            action: 'remove_gateway_server', server_id: server.server_id,
          }), 'Gateway server removed.')}>Remove</button>
        </div>
      </li>)}</ul> : null}
    <Disclosure title="Add an MCP server" defaultOpen={!servers.length}>
      <form className="mcp-settings" onSubmit={save}>
        <fieldset disabled={busy}>
          <div className="mcp-settings-actions">
            <button className="button subtle" type="button" onClick={() => {
              setName('binance'); setTransport('http'); setUrl('https://agent.binance.com/mcp/agentic');
              setVault(false); setToken('');
            }}>Binance market data</button>
            <button className="button subtle" type="button" onClick={() => {
              setName('alpaca'); setTransport('stdio'); setProgram('uvx'); setArgs('alpaca-mcp-server');
              setEnv('ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_TOOLSETS, ALPACA_PAPER_TRADE');
            }}>Alpaca Trading MCP</button>
          </div>
          <div className="mcp-settings-intervals">
            <label>Server name<input value={name} onChange={e => setName(e.target.value)} required pattern="[A-Za-z0-9_.\-]+" /></label>
            <label>Transport<select value={transport} onChange={e => setTransport(e.target.value === 'http' ? 'http' : 'stdio')}>
              <option value="http">HTTPS</option><option value="stdio">Local command (stdio)</option>
            </select></label>
            {transport === 'http' ? <label>MCP endpoint<input type="url" value={url} onChange={e => setUrl(e.target.value)} required /></label> : <>
              <label>Executable<input value={program} onChange={e => setProgram(e.target.value)} required /></label>
              <label>Arguments, one per line<textarea value={args} onChange={e => setArgs(e.target.value)} /></label>
              <label>Working directory<input value={cwd} onChange={e => setCwd(e.target.value)} /></label>
              <label>Environment variable names<input value={env} onChange={e => setEnv(e.target.value)} /></label>
            </>}
          </div>
          {transport === 'http' ? <>
            <label className="mcp-setting-toggle"><input type="checkbox" checked={vault} onChange={e => setVault(e.target.checked)} />Use a bearer token from the OS credential store</label>
            {vault ? <label>Bearer token<input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" /></label> : null}
          </> : <p>Credential values come from the environment of the process that starts the gateway.</p>}
          <div className="mcp-settings-actions"><button type="submit" className="button primary">Save and check catalog</button></div>
        </fieldset>
      </form>
    </Disclosure>
    {message ? <p className="mcp-activity-note" role={failed ? 'alert' : 'status'}>{message}</p> : null}
  </section>;
}
