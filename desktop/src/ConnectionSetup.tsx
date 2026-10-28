import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { request } from './bridge';
import { buildClientConfig, buildHttpProfile, buildProfile } from './connection-utils';
import type { RuntimeInfo } from './connection-utils';
import { downloadText } from './review-utils';
import { Disclosure } from './Disclosure';

export function ConnectionSetup({ native }: { native: boolean }) {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [server, setServer] = useState('');
  const [transport, setTransport] = useState('stdio');
  const [endpoint, setEndpoint] = useState('');
  const [auth, setAuth] = useState('none');
  const [tokenEnv, setTokenEnv] = useState('');
  const [secret, setSecret] = useState('');
  const [credentialBusy, setCredentialBusy] = useState(false);
  const [credentialNotice, setCredentialNotice] = useState('');
  const [argv, setArgv] = useState('');
  const [cwd, setCwd] = useState('');
  const [protocol, setProtocol] = useState('2025-11-25');
  const [env, setEnv] = useState('');
  const [profile, setProfile] = useState<ReturnType<typeof buildProfile> | ReturnType<typeof buildHttpProfile> | null>(null);
  const [profilePath, setProfilePath] = useState('');
  const [client, setClient] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    if (native) void request<RuntimeInfo>({ action: 'runtime_info' })
      .then(info => { if (active) setRuntime(info); })
      .catch(() => { if (active) setError('The local engine information is unavailable. Reopen the packaged app.'); });
    return () => { active = false; };
  }, [native]);
  const prepare = (event: FormEvent) => {
    event.preventDefault(); setError(''); setClient('');
    try { setProfile(transport === 'http'
      ? buildHttpProfile(server.trim(), endpoint.trim(), protocol, auth, tokenEnv.trim())
      : buildProfile(server.trim(), argv, cwd.trim(), protocol, env)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Check the source fields.'); }
  };
  return <section className="panel connection-setup">
    <Disclosure title="Set up a protected connection" level={2}>
    <p>Create a source profile, then route your MCP client through the local gateway.</p>
    <form onSubmit={prepare}>
      <div className="connection-fields">
        <label className="form-label">Connection transport<select aria-label="Connection transport" value={transport} onChange={event => { setTransport(event.target.value); setProfile(null); setClient(''); setSecret(''); }}><option value="stdio">Local process · stdio</option><option value="http">Remote endpoint · Streamable HTTP</option></select></label>
        <label className="form-label">Source identifier<input required maxLength={128} value={server} onChange={event => { setServer(event.target.value); setProfile(null); setClient(''); }} placeholder="my-local-server" /></label>
        {transport === 'stdio' ? <><label className="form-label">Working directory<input required value={cwd} onChange={event => { setCwd(event.target.value); setProfile(null); setClient(''); }} placeholder="Absolute directory containing the server" /></label>
        <label className="form-label">Server command as JSON<textarea required rows={3} value={argv} onChange={event => { setArgv(event.target.value); setProfile(null); setClient(''); }} placeholder={'["/absolute/path/to/executable", "/absolute/path/to/server.py"]'} /><small>Each argument is separate. Review the executable before connecting; launching it gives it your user permissions.</small></label></> : <label className="form-label">HTTPS endpoint<input required type="url" value={endpoint} onChange={event => { setEndpoint(event.target.value); setProfile(null); setClient(''); setCredentialNotice(''); }} placeholder="https://server.example/mcp" /></label>}
        <label className="form-label">MCP protocol<select aria-label="MCP protocol" value={protocol} onChange={event => { setProtocol(event.target.value); setProfile(null); setClient(''); }}><option value="2025-11-25">2025-11-25 · initialize handshake</option><option value="2026-07-28">2026-07-28 · discovery handshake</option></select></label>
        {transport === 'stdio' ? <label className="form-label">Environment variable names<input value={env} onChange={event => { setEnv(event.target.value); setProfile(null); setClient(''); }} placeholder="Optional: API_TOKEN, OTHER_VARIABLE" /><small>Names only. Configure their values in the trusted MCP client environment.</small></label> : <>
          <label className="form-label">HTTP authentication<select aria-label="HTTP authentication" value={auth} onChange={event => { setAuth(event.target.value); setProfile(null); setClient(''); setSecret(''); }}><option value="none">No bearer credential</option><option value="environment">Named environment variable</option><option value="vault">Operating system credential store</option></select></label>
          {auth === 'environment' ? <label className="form-label">Bearer environment variable<input required value={tokenEnv} onChange={event => { setTokenEnv(event.target.value); setProfile(null); setClient(''); }} placeholder="MCP_API_TOKEN" /><small>Configure its value in your trusted MCP client environment.</small></label> : null}
          {auth === 'vault' ? <div><label className="form-label">Bearer credential<input type="password" autoComplete="off" value={secret} onChange={event => setSecret(event.target.value)} /><small>Bound to this exact source and endpoint. Stored values are never returned to the interface.</small></label><button className="button subtle" type="button" disabled={!native || credentialBusy || !secret} onClick={() => {
            try { buildHttpProfile(server.trim(), endpoint.trim(), protocol, 'vault', ''); }
            catch (failure) { setError(failure instanceof Error ? failure.message : 'Check the source and endpoint.'); return; }
            setCredentialBusy(true); setError(''); setCredentialNotice('');
            void request<{ available: boolean; stored: boolean; message?: string }>({ action: 'store_http_credential', server_id: server.trim(), url: endpoint.trim(), secret })
              .then(result => { setSecret(''); if (!result.available) throw new Error(result.message ?? 'Unlock your OS credential store.'); setCredentialNotice('Credential saved in the operating system store.'); })
              .catch(failure => { setSecret(''); setError(failure instanceof Error ? failure.message : 'Credential storage failed.'); })
              .finally(() => setCredentialBusy(false));
          }}>{credentialBusy ? 'Saving…' : 'Save to OS credential store'}</button>{credentialNotice ? <p className="small" role="status">{credentialNotice}</p> : null}</div> : null}
        </>}
      </div>
      <button className="button primary" type="submit">Prepare source profile</button>
    </form>
    {profile ? <div className="connection-output"><h3>1. Save your source profile</h3><p>Download this file to a permanent local location. Preparing it does not start the server.</p><pre>{JSON.stringify(profile, null, 2)}</pre><button className="button subtle" onClick={() => downloadText(profile.server_id + '.json', JSON.stringify(profile, null, 2))}>Download source profile</button>
      <h3>2. Add the gateway to your MCP client</h3><label className="form-label">Saved profile absolute path<input value={profilePath} onChange={event => { setProfilePath(event.target.value); setClient(''); }} placeholder="Full path to the downloaded JSON file" /></label>
      {!native ? <p className="small muted">Open the native app to create a client configuration using its installed engine and local review database.</p> : <button className="button primary" disabled={!runtime?.engine_available} onClick={() => { try { setClient(JSON.stringify(buildClientConfig(runtime!, profilePath.trim(), profile.server_id), null, 2)); setError(''); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Check the saved profile path.'); } }}>Create client configuration</button>}
      {client ? <><pre aria-label="MCP client configuration">{client}</pre><button className="button subtle" onClick={() => downloadText('driftguard-client-config.json', client)}>Download client configuration</button><h3>3. Review new tools</h3><p>Merge this entry into your MCP client configuration and restart that client. Return here and refresh the workspace to review its new session. Each changed definition requires approval.</p></> : null}
    </div> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    </Disclosure>
  </section>;
}
