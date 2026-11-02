import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import { Disclosure } from './Disclosure';
import type { BridgeAction, BridgeRequest } from './types';

type LiveStatus = {
  running: boolean; installed?: boolean; clients: number; verified: boolean;
  codex_available?: boolean; config_path?: string; sample_path?: string;
  tool: { sha256: string; revision: number; status: string } | null;
  job: { stage: string; message?: string; sha256?: string; revision?: number };
  message?: string;
};

export function LiveConnection({ native, onChanged }: { native: boolean; onChanged: () => void }) {
  const [data, setData] = useState<LiveStatus | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const working = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const previousJob = useRef('idle');
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const refresh = useCallback(async () => {
    if (!native || working.current) return;
    const sequence = ++generation.current;
    try {
      const next = await request<LiveStatus>({ action: 'live_status' });
      if (!mounted.current || sequence !== generation.current) return;
      if (previousJob.current === 'running' && next.job.stage !== 'running') changed.current();
      previousJob.current = next.job.stage;
      setData(next);
    } catch (failure) {
      if (mounted.current && sequence === generation.current) setError(failure instanceof Error ? failure.message : 'Connection status is unavailable.');
    }
  }, [native]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 2000);
    return () => { mounted.current = false; generation.current += 1; window.clearInterval(timer); };
  }, [refresh]);
  const act = async (action: BridgeAction, label: string) => {
    if (!native || working.current) return;
    working.current = true; generation.current += 1; setBusy(label); setError(''); setNotice('');
    try {
      const payload: BridgeRequest = action === 'live_verify' && data?.tool ? {
        action, expected_sha256: data.tool.sha256, expected_revision: data.tool.revision,
      } : { action };
      const result = await request<LiveStatus>(payload);
      const next = await request<LiveStatus>({ action: 'live_status' });
      if (mounted.current) {
        setData(next); setNotice(result.message ?? ''); previousJob.current = next.job.stage;
        changed.current();
      }
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : 'Connection operation failed.');
    } finally { working.current = false; if (mounted.current) setBusy(''); }
  };
  const codexVerified = data?.verified && data.job.stage === 'complete' &&
    data.job.sha256 === data.tool?.sha256 && data.job.revision === data.tool?.revision;
  return <section className="panel connection-setup">
    <Disclosure title="Connect Codex" level={2}>
      <p>Set up and test a protected local Filesystem connection here.</p>
      <ol className="live-steps" aria-label="Codex connection progress">
        <li className={data?.running && data.installed ? 'complete' : ''}>Connection prepared</li>
        <li className={data?.verified ? 'complete' : ''}>Local read verified</li>
        <li className={codexVerified ? 'complete' : ''}>Codex MCP read verified</li>
      </ol>
      {!native ? <p className="small muted">Open the desktop app to connect your installed Codex CLI.</p> : null}
      <div className="inline-actions">
        <button className="button primary" disabled={!native || !!busy || !!data?.running} onClick={() => { void act('live_connect', 'Preparing connection…'); }}>Connect</button>
        {data?.running ? <>
          <button className="button primary" disabled={!!busy || !data.tool || data.job.stage === 'running'} onClick={() => { void act('live_verify', 'Approving and testing…'); }}>Approve &amp; test local read</button>
          <button className="button subtle" disabled={!!busy || !data.verified || !data.codex_available || data.job.stage === 'running'} onClick={() => { void act('live_run_codex', 'Starting Codex…'); }}>Run sample in Codex</button>
          {data.job.stage === 'running' ? <button className="button subtle" disabled={!!busy} onClick={() => { void act('live_cancel_codex', 'Cancelling…'); }}>Cancel Codex test</button> : null}
        </> : null}
        {data?.running || data?.installed ? <button className="button subtle" disabled={!!busy} onClick={() => { void act('live_disconnect', 'Disconnecting…'); }}>Disconnect</button> : null}
      </div>
      {busy ? <p role="status">{busy}</p> : null}
      {data?.running ? <>
        <p className="small" role="status">Gateway running · {data.clients} MCP clients attached{data.verified ? ' · Local read verified' : ''}</p>
        {!data.codex_available ? <p className="small">Install the Codex CLI and sign in normally to enable the Codex test.</p> : null}
        <Disclosure title="Read approval details" level={3}>
          <p>Approve <strong>read_text_file</strong> under <strong>driftguard-filesystem</strong>. The upstream server can access only its app-owned sample folder. This button approves the displayed definition and reads check.txt to verify it.</p>
          <p className="small live-hash">Definition: {data.tool?.sha256} · revision {data.tool?.revision}</p>
          <p className="small live-hash">Sample: {data.sample_path}</p>
        </Disclosure>
      </> : null}
      {data?.job.stage === 'running' ? <p role="status">Codex is running a read-only sample task. You can cancel it here.</p> : data?.job.message ? <p role="status">{data.job.message}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <Disclosure title="How setup works" level={3}>
        <p>Connect installs the pinned Filesystem server in app storage, starts a shared background gateway, and adds one backed-up Codex TOML entry. Disconnect stops this gateway and restores your previous settings if they have not changed.</p>
        <p>Run sample in Codex starts a fresh, read-only task using your normal Codex sign-in and account. It reports success only after an actual MCP sample read. Existing chats load the new connection on their next session; they are not restarted.</p>
        <p className="small live-hash">{data?.config_path}</p>
      </Disclosure>
    </Disclosure>
  </section>;
}
