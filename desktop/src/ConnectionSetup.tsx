import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { request } from './bridge';
import { buildClientConfig, buildProfile } from './connection-utils';
import type { RuntimeInfo } from './connection-utils';
import { downloadText } from './review-utils';

export function ConnectionSetup({ native }: { native: boolean }) {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [server, setServer] = useState('');
  const [argv, setArgv] = useState('');
  const [cwd, setCwd] = useState('');
  const [protocol, setProtocol] = useState('2025-11-25');
  const [env, setEnv] = useState('');
  const [profile, setProfile] = useState<ReturnType<typeof buildProfile> | null>(null);
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
    try { setProfile(buildProfile(server.trim(), argv, cwd.trim(), protocol, env)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Check the source fields.'); }
  };
  return <section className="panel connection-setup">
    <div className="section-heading"><div><h2>Set up a protected connection</h2><p>Create a source profile, then route your MCP client through the local gateway.</p></div><span className="badge">{runtime?.packaged ? 'Bundled engine' : 'Explicit setup'}</span></div>
    <form onSubmit={prepare}>
      <div className="connection-fields">
        <label className="form-label">Source identifier<input required maxLength={128} value={server} onChange={event => { setServer(event.target.value); setProfile(null); setClient(''); }} placeholder="my-local-server" /></label>
        <label className="form-label">Working directory<input required value={cwd} onChange={event => { setCwd(event.target.value); setProfile(null); setClient(''); }} placeholder="Absolute directory containing the server" /></label>
        <label className="form-label">Server command as JSON<textarea required rows={3} value={argv} onChange={event => { setArgv(event.target.value); setProfile(null); setClient(''); }} placeholder={'["/absolute/path/to/executable", "/absolute/path/to/server.py"]'} /><small>Each argument is separate. Review the executable before connecting; launching it gives it your user permissions.</small></label>
        <label className="form-label">MCP protocol<select value={protocol} onChange={event => { setProtocol(event.target.value); setProfile(null); setClient(''); }}><option value="2025-11-25">2025-11-25 · initialize handshake</option><option value="2026-07-28">2026-07-28 · discovery handshake</option></select></label>
        <label className="form-label">Environment variable names<input value={env} onChange={event => { setEnv(event.target.value); setProfile(null); setClient(''); }} placeholder="Optional: API_TOKEN, OTHER_VARIABLE" /><small>Names only. Configure their values in the trusted MCP client environment.</small></label>
      </div>
      <button className="button primary" type="submit">Prepare source profile</button>
    </form>
    {profile ? <div className="connection-output"><h3>1. Save your source profile</h3><p>Download this file to a permanent local location. Preparing it does not start the server.</p><pre>{JSON.stringify(profile, null, 2)}</pre><button className="button subtle" onClick={() => downloadText(profile.server_id + '.json', JSON.stringify(profile, null, 2))}>Download source profile</button>
      <h3>2. Add the gateway to your MCP client</h3><label className="form-label">Saved profile absolute path<input value={profilePath} onChange={event => { setProfilePath(event.target.value); setClient(''); }} placeholder="Full path to the downloaded JSON file" /></label>
      {!native ? <p className="small muted">Open the native app to create a client configuration using its installed engine and local review database.</p> : <button className="button primary" disabled={!runtime?.engine_available} onClick={() => { try { setClient(JSON.stringify(buildClientConfig(runtime!, profilePath.trim(), profile.server_id), null, 2)); setError(''); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Check the saved profile path.'); } }}>Create client configuration</button>}
      {client ? <><pre aria-label="MCP client configuration">{client}</pre><button className="button subtle" onClick={() => downloadText('driftguard-client-config.json', client)}>Download client configuration</button><h3>3. Review new tools</h3><p>Merge this entry into your MCP client configuration and restart that client. Return here and refresh the workspace to review its new session. Each changed definition requires approval.</p></> : null}
    </div> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </section>;
}
