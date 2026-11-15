import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import { GatewayServers } from './GatewayServers';
import { Icon } from './Icon';
import type { BridgeAction, BridgeRequest, CatalogSync, ToolRecord } from './types';
import { groupCatalog } from './catalog-connections';
import { harnessPresentation } from './harness-state';

type Harness = { id: string; label: string; detected: boolean; installed: boolean; configured?: boolean; attached: number };

type LiveStatus = {
  engine?: 'rust'; pending?: number; catalog_tools?: number;
  harnesses: Harness[];
  running: boolean; installed?: boolean; clients: number; verified: boolean;
  codex_available?: boolean;
  tool: { sha256: string; revision: number; status: string; definition?: Record<string, unknown> } | null;
  job: { stage: string; message?: string; sha256?: string; revision?: number };
  message?: string;
  codex_routes?: string[];
  codex_skipped_routes?: string[];
};

export function LiveConnection({ native, onChanged, onReview, onReviewConnection, tools, sources, catalogSync, catalogSyncing, catalogError, onSync }: {
  native: boolean; onChanged: () => void; onReview: () => void; onReviewConnection: (id: string) => void;
  tools: ToolRecord[]; sources: Map<string, string>;
  catalogSync: CatalogSync | null; catalogSyncing: boolean; catalogError: string; onSync: () => Promise<void>;
}) {
  const [data, setData] = useState<LiveStatus | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [statusError, setStatusError] = useState('');
  const [notice, setNotice] = useState('');
  const working = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const previousJob = useRef('idle');
  const attachedSessions = useRef(0);
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const refresh = useCallback(async () => {
    if (!native || working.current) return;
    const sequence = ++generation.current;
    try {
      const next = await request<LiveStatus>({ action: 'live_status' });
      if (!mounted.current || sequence !== generation.current) return;
      if (previousJob.current === 'running' && next.job.stage !== 'running') changed.current();
      if (next.engine === 'rust' && attachedSessions.current !== next.clients) changed.current();
      attachedSessions.current = next.clients;
      previousJob.current = next.job.stage;
      setData(next);
      setStatusError('');
    } catch (failure) {
      if (mounted.current && sequence === generation.current) setStatusError(failure instanceof Error ? failure.message : 'Connection status is unavailable.');
    }
  }, [native]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 2000);
    return () => { mounted.current = false; generation.current += 1; window.clearInterval(timer); };
  }, [refresh]);
  const act = async (action: BridgeAction, label: string, harness?: string) => {
    if (!native || working.current) return;
    working.current = true; generation.current += 1; setBusy(label); setError(''); setNotice('');
    let operationApplied = false;
    try {
      const payload: BridgeRequest = harness ? { action, harness } : { action };
      const result = await request<LiveStatus>(payload);
      operationApplied = true;
      const next = await request<LiveStatus>({ action: 'live_status' });
      if (mounted.current) {
        setData(next); setNotice(result.message ?? ''); previousJob.current = next.job.stage;
        changed.current();
      }
      // Refresh discovery on both transitions, including removal of stale tools.
      if (next.engine === 'rust' && (action === 'live_connect' || action === 'live_disconnect')) {
        await onSync();
      }
    } catch (failure) {
      if (mounted.current) {
        const detail = failure instanceof Error ? failure.message : 'Unknown error.';
        setError(operationApplied
          ? `The harness configuration was changed, but refresh failed: ${detail}`
          : `Connection operation failed: ${detail}`);
        // Let the next timer poll reconcile state without replaying the mutation.
      }
    } finally { working.current = false; if (mounted.current) setBusy(''); }
  };
  const [skippedRoutes, setSkippedRoutes] = useState<string[]>([]);
  const routeCodex = async (restore: boolean) => {
    if (working.current) return;
    working.current = true;
    generation.current += 1;
    setBusy(restore ? 'Restoring Codex MCPs…' : 'Routing Codex MCPs…');
    setError('');
    setNotice('');
    try {
      const result = await request<{ routed: string[]; skipped: string[] }>({
        action: restore ? 'restore_codex_mcps' : 'route_codex_mcps',
      });
      const next = await request<LiveStatus>({ action: 'live_status' });
      if (mounted.current) {
        setData(next);
        setSkippedRoutes(result.skipped);
        setNotice(restore ? 'Restored direct Codex connections. Open a new Codex session.'
          : result.routed.length ? `Routed ${result.routed.length} Codex MCP servers. Open a new Codex session.`
          : 'No compatible Codex MCP servers were found in user settings.');
        changed.current();
      }
    } catch (failure) {
      if (mounted.current) setError(failure instanceof Error ? failure.message : 'Could not update Codex MCP routing.');
    } finally {
      working.current = false;
      if (mounted.current) setBusy('');
    }
  };
  const codexConnected = data?.harnesses.some(client => client.id === 'codex' &&
    (client.configured ?? (data.engine !== 'rust' && client.installed && data.running)));
  const activeJob = codexConnected && data?.job.stage === 'running';
  const bypassedRoutes = data?.codex_skipped_routes ?? skippedRoutes;
  const discovered = catalogSync?.servers.filter(server => server.state === 'observed') ?? [];
  const unavailable = catalogSync?.servers.filter(server => server.state === 'unavailable') ?? [];
  const toolCount = Math.max(data?.catalog_tools ?? 0, discovered.reduce((sum, server) => sum + (server.tools ?? 0), 0));
  const connections = groupCatalog(tools.filter(tool => tool.server_id.startsWith('harness:')), sources);
  const signIn = async (name: string) => {
    if (working.current) return;
    working.current = true;
    setBusy('Waiting for browser sign-in…');
    setError('');
    try {
      await request({ action: 'codex_mcp_sign_in', server_id: name });
      setNotice(`Signed in to ${name} in Codex.`);
      await onSync();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not complete browser sign-in.');
    } finally { working.current = false; setBusy(''); }
  };
  return <><section className="panel harness-panel" aria-labelledby="coding-harnesses">
    <div className="harness-panel-header">
      <span className="harness-panel-icon"><Icon name="connections" size={22} /></span>
      <div><h2 id="coding-harnesses">Coding harnesses</h2>
        <p>DriftGuard detects installed clients and configures their connection to its local MCP gateway.</p></div>
    </div>
    {!native ? <p className="harness-preview">Open the desktop app to detect and connect coding harnesses on this device.</p>
      : !data && !statusError ? <p role="status">Detecting installed harnesses…</p> : null}
    {data?.harnesses.length ? <ul className="managed-harness-list">{data.harnesses.map(client => {
      // The legacy Python workspace does not expose the Rust 'configured' field.
      const state = harnessPresentation({
        ...client,
        configured: client.configured ?? (data.engine !== 'rust' && client.installed && data.running),
      });
      return <li key={client.id}>
        <div><strong>{client.label}</strong><span>{state.description}</span></div>
        <div className="managed-harness-actions">
          {state.connected ? <span className={client.attached ? 'badge positive' : 'badge'}>{state.badge}</span> : null}
          {state.canDisconnect ? <button className="button subtle" disabled={!!busy || catalogSyncing}
            aria-label={`Disconnect ${client.label}`} onClick={() => void act('live_disconnect', `Disconnecting ${client.label}…`, client.id)}>Disconnect</button> : null}
          {state.canConnect ? <button className="button primary" disabled={!!busy || catalogSyncing}
            aria-label={`Connect ${client.label}`}
            onClick={() => void act('live_connect', `Connecting ${client.label}…`, client.id)}>Connect</button> : null}
        </div>
      </li>;
    })}</ul> : null}
    {data?.engine === 'rust' && data.harnesses.some(client => client.id === 'codex' && (client.installed || client.detected)) ? <>
      <div className="managed-harness-summary">
        <div><strong>Existing Codex MCP servers</strong>
          <p>{data.codex_routes?.length ? `${data.codex_routes.length} routed · ${data.codex_routes.join(', ')}`
            : 'Route compatible servers from Codex user settings through DriftGuard.'}</p></div>
        <button className="button subtle" disabled={!!busy || catalogSyncing} onClick={() => void routeCodex(Boolean(data.codex_routes?.length))}>
          {data.codex_routes?.length ? 'Restore direct connections' : 'Route existing Codex MCPs'}
        </button>
      </div>
      {bypassedRoutes.length ? <p className="harness-scope" role="alert">Not protected by DriftGuard: {bypassedRoutes.join(', ')}. These Codex MCP routes were skipped due to unsupported configuration or authentication and may still connect directly.</p> : null}
      <p className="harness-scope">Codex-hosted apps are managed by Codex. DriftGuard can review their catalog.</p>
    </> : null}
    {data ? <p className="harness-provider-note">Use OpenRouter or Ollama through your coding client’s model settings. Only MCP calls explicitly routed through DriftGuard are protected. Disconnecting removes the managed configuration; restart the client to clear cached tools and sessions.</p> : null}
    {data?.engine === 'rust' && data.harnesses.some(client => client.installed) ? <>
      <div className="managed-harness-summary">
        <div><strong>MCP tool discovery</strong>
          <p role="status">{catalogSyncing ? 'Discovering configured MCP servers…'
            : `${toolCount} ${toolCount === 1 ? 'tool' : 'tools'} in the workspace · ${data.clients} MCP ${data.clients === 1 ? 'session' : 'sessions'} attached.`}</p></div>
        <div className="managed-harness-actions">
          <button className="button subtle" disabled={catalogSyncing || !!busy} onClick={() => void onSync()}>Rescan MCPs</button>
          {toolCount > 0 ? <button className="button primary" onClick={onReview}>Review tools</button> : null}
        </div>
      </div>
      {catalogError ? <p className="form-error" role="alert">{catalogError}</p> : null}
      {unavailable.length ? <details className="harness-scope"><summary>{unavailable.length} MCP {unavailable.length === 1 ? 'catalog unavailable' : 'catalogs unavailable'}</summary>
        <ul>{unavailable.map(server => <li key={`${server.harness}:${server.name}`}>
          {data.harnesses.find(client => client.id === server.harness)?.label ?? server.harness}
          {server.name ? ` · ${server.name}` : ''} · {server.message}
          {server.harness === 'codex' && server.name && server.sign_in ? <button className="button subtle"
            disabled={!!busy || catalogSyncing} onClick={() => void signIn(server.name!)}>Sign in to {server.name}</button> : null}
        </li>)}</ul></details> : null}
      {discovered.length ? <p className="harness-scope">Discovered tools are available for review. Gateway enforcement applies to routed MCP sessions.</p> : null}
      {catalogSync && !catalogSync.servers.length && !toolCount && !catalogSyncing ? <p className="harness-scope">
        No existing MCP servers were found in the connected clients’ user settings. Open a new client session to see tools from the DriftGuard gateway.
      </p> : null}
    </> : data?.running ? <div className="managed-harness-summary">
      <div><strong>{data.verified ? 'Sample read verified' : data.tool?.status === 'approved'
        ? 'Checking the local sample' : 'Review the sample tool'}</strong>
        <p role="status">{data.verified ? `${data.clients} MCP clients attached. New harness sessions pick up the configured gateway.`
          : data.tool?.status === 'approved' ? 'DriftGuard automatically checks the read after approval.'
          : 'Approve the exact definition in Security review to let DriftGuard verify the local read.'}</p></div>
      {data.verified ? codexConnected && data.codex_available && (activeJob
        ? <button className="button subtle" disabled={!!busy} onClick={() => void act('live_cancel_codex', 'Cancelling Codex test…')}>Cancel Codex test</button>
        : <button className="button subtle" disabled={!!busy} onClick={() => void act('live_run_codex', 'Starting Codex test…')}>Verify in Codex</button>)
        : <button className="button primary" onClick={onReview}>Review sample tool</button>}
    </div> : null}
    {connections.length ? <section className="observed-connections" aria-labelledby="observed-connections-heading">
      <h2 id="observed-connections-heading">Discovered MCP connections</h2>
      <ul className="managed-harness-list">{connections.map(group => <li key={group.id}>
        <div><strong>{group.label}</strong><span>{group.tools.length} {group.tools.length === 1 ? 'tool' : 'tools'} · Review only</span></div>
        <button className="button subtle" aria-label={`Review ${group.label} tools`} onClick={() => onReviewConnection(group.id)}>View tools</button>
      </li>)}</ul>
    </section> : null}
    {busy ? <p role="status">{busy}</p> : null}
    {activeJob ? <p role="status">Codex is running the read-only sample with your existing sign-in.</p>
      : codexConnected && data?.job.message ? <p role="status">{data.job.message}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {error || statusError ? <p className="form-error" role="alert">{error || statusError}</p> : null}
  </section>
    {data?.engine === 'rust' ? <GatewayServers onChanged={onChanged} /> : null}
  </>;
}
