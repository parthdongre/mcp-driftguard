import { useEffect, useState } from 'react';
import { request } from './bridge';
import type { McpActivityEvent } from './types';

const PAGE_SIZE = 100;
const labels: Record<string, string> = {
  mcp_added: 'New MCP added', catalog_observed: 'Catalog checked',
  catalog_check_failed: 'Catalog check failed', definition_observed: 'Tool discovered',
  definition_changed: 'Definition changed', tool_removed: 'Tool removed',
  gateway_connected: 'Gateway connected', gateway_disconnected: 'Gateway disconnected',
  call_authorized: 'Call started', call_completed: 'Call completed', call_failed: 'Call failed',
  gateway_call_blocked: 'Call blocked', server_stopped: 'Server stopped',
  server_resumed: 'Server resumed', model_decision: 'Model decision',
  harness_configured: 'Harness configured', harness_disconnected: 'Harness disconnected',
  tool_auto_approved: 'Tool auto-approved', tool_approved: 'Tool approved', tool_denied: 'Tool denied', tool_quarantined: 'Tool quarantined',
  tool_release_quarantine: 'Quarantine released',
};
const timeFormat = new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric',
});
const describe = (event: McpActivityEvent) => {
  const { detail } = event;
  if (event.event === 'catalog_observed' && typeof detail.tools === 'number') {
    return `${detail.tools} ${detail.tools === 1 ? 'tool' : 'tools'} reported`;
  }
  if (event.event === 'definition_changed' && Array.isArray(detail.changed_fields)) {
    return detail.changed_fields.filter(field => typeof field === 'string').join(', ');
  }
  if (typeof detail.reason === 'string') return detail.reason.replaceAll('_', ' ');
  return '';
};

export function McpActivity({ sources, showChecks, onShowChecks }: {
  sources: Map<string, string>;
  showChecks: boolean;
  onShowChecks: (value: boolean) => void;
}) {
  return <section className="panel mcp-activity" aria-labelledby="mcp-activity-title">
    <div className="mcp-activity-heading">
      <div><h2 id="mcp-activity-title">MCP activity log</h2>
        <p className="small muted">Tool calls, catalog checks, and security decisions.</p></div>
      <label className="mcp-setting-toggle"><input type="checkbox" checked={showChecks}
        onChange={event => onShowChecks(event.target.checked)} />Show successful checks</label>
    </div>
    <McpActivityLog key={String(showChecks)} sources={sources} includeChecks={showChecks} />
  </section>;
}

function McpActivityLog({ sources, includeChecks }: {
  sources: Map<string, string>;
  includeChecks: boolean;
}) {
  const [latest, setLatest] = useState<McpActivityEvent[] | null>(null);
  const [older, setOlder] = useState<McpActivityEvent[]>([]);
  const [allLoaded, setAllLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [readError, setReadError] = useState('');
  const [pageError, setPageError] = useState('');
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const records = await request<McpActivityEvent[]>({ action: 'mcp_activity', include_checks: includeChecks });
        if (active) { setLatest(records); setReadError(''); }
      } catch {
        if (active) setReadError('Could not refresh MCP activity.');
      }
      if (active) timer = setTimeout(() => { void poll(); }, 2500);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [includeChecks]);

  const lastId = older.at(-1)?.id ?? latest?.at(-1)?.id;
  const canLoadOlder = !allLoaded && (older.length > 0 || latest?.length === PAGE_SIZE);
  const loadOlder = async () => {
    if (busy || !lastId) return;
    setBusy(true);
    setPageError('');
    try {
      const records = await request<McpActivityEvent[]>({ action: 'mcp_activity', before_id: lastId, include_checks: includeChecks });
      setOlder(previous => [...(previous.length ? previous : latest ?? []), ...records]);
      setAllLoaded(records.length < PAGE_SIZE);
    } catch {
      setPageError('Could not load older MCP activity.');
    } finally {
      setBusy(false);
    }
  };

  const events = new Map<number, McpActivityEvent>();
  for (const event of [...(latest ?? []), ...older]) events.set(event.id, event);
  const visible = [...events.values()].sort((left, right) => right.id - left.id);

  return <>
    {readError || pageError ? <p className="mcp-activity-note" role="status">{pageError || readError}</p> : null}
    {visible.length > 0 ? <div className="mcp-activity-scroll" tabIndex={0} role="region" aria-label="Recent MCP activity">
      <ol className="mcp-activity-list" role="list">
        {visible.map(event => {
          const title = labels[event.event] ?? event.event.replaceAll('_', ' ');
          const source = event.event === 'mcp_added' && typeof event.detail.name === 'string'
            ? event.detail.name : sources.get(event.server_id) ?? event.server_id;
          const detail = describe(event);
          return <li key={event.id}>
            <time dateTime={event.timestamp}>{timeFormat.format(new Date(event.timestamp))}</time>
            <strong>{title}</strong>
            <span>{source}{event.tool_name ? ` · ${event.tool_name}` : ''}</span>
            {detail ? <span className="small muted">{detail}</span> : null}
          </li>;
        })}
      </ol>
    </div> : <p className="mcp-activity-note muted">{latest ? 'No matching MCP activity has been recorded.' : readError ? 'MCP activity is unavailable.' : 'Reading MCP activity…'}</p>}
    {canLoadOlder ? <div className="mcp-activity-note">
      <button className="button subtle" disabled={busy} onClick={() => void loadOlder()}>Load older activity</button>
    </div> : null}
  </>;
}
