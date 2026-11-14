import { useEffect, useState } from 'react';
import { request } from './bridge';
import { formatTime } from './review-utils';
import type { AuditEvent, GraphRoute, ToolDefinition } from './types';
import { Dialog } from './Dialog';
import './sentinel.css';

export interface SentinelCall {
  id: number;
  source: string;
  session: string;
  tool: string;
  sha256: string | null;
  revision: number | null;
  started_at: string;
  ended_at: string | null;
  state: 'active' | 'completed' | 'failed' | 'blocked' | 'unconfirmed';
  reason: string | null;
  previous_success: number | null;
  previous_sha256: string | null;
}

const reasons: Record<string, string> = {
  server_stopped: 'The server was stopped across managed routes.',
  tool_blocked: 'A tool block prevented dispatch.',
  version_not_approved: 'This session lacked approval for the current tool definition.',
  credential_in_request: 'The gateway detected credential material in the request and withheld it.',
  sensitive_value_reuse: 'An argument matched a sensitive value previously observed in this gateway session.',
  input_contract: 'The arguments or tool contract failed validation.',
  tool_unavailable: 'The tool was absent from the current server catalog.',
  upstream_or_output_failure: 'The request reached upstream processing. Delivery failed and external effects may be unknown.',
  upstream_reported_error: 'The upstream tool reported an error.',
};

interface Evidence {
  definition: ToolDefinition | null;
  changes: AuditEvent[];
  current_policy: string;
}

export function Sentinel({ calls, routes, onRefresh }: {
  calls: SentinelCall[]; routes: GraphRoute[]; onRefresh: () => void;
}) {
  const [past, setPast] = useState<SentinelCall[]>([]);
  const [selectedId, select] = useState<number | null>(null);
  const [filter, setFilter] = useState('');
  const [route, setRoute] = useState('');
  const [session, setSession] = useState('');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [exhausted, setExhausted] = useState(false);
  const [confirm, setConfirm] = useState<'stop' | 'resume' | 'clear' | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const records = [...new Map([...past, ...calls].map(call => [call.id, call])).values()].sort((a,b) => b.id-a.id);
  const managed = routes.filter(item => item.kind === 'gateway');
  const chosen = managed.find(item => item.source_id === route);
  const visible = records.filter(call => (!route || call.source === route) && (!session || call.session === session)
    && (!filter || filter === call.state) && call.tool.toLowerCase().includes(query.trim().toLowerCase()));
  const selected = records.find(call => call.id === selectedId);
  useEffect(() => {
    setEvidence(null);
    if (!selectedId) return;
    let active = true;
    void request<Evidence>({ action: 'sentinel_evidence', call_id: selectedId })
      .then(value => { if (active) setEvidence(value); })
      .catch(failure => { if (active) setError(String(failure.message ?? failure)); });
    return () => { active = false; };
  }, [selectedId]);
  const update = async () => {
    if (!confirm) return;
    setBusy(true); setError('');
    try {
      if (confirm === 'clear') {
        await request({ action: 'sentinel_clear' });
        setPast([]); select(null); setExhausted(false);
      } else if (chosen) {
        await request({ action: confirm === 'stop' ? 'sentinel_stop' : 'sentinel_resume', server_id: chosen.source_id });
      }
      setConfirm(null); onRefresh();
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  };
  const older = async () => {
    setBusy(true); setError('');
    try {
      const page = await request<SentinelCall[]>({ action: 'sentinel_calls', before_id: records.at(-1)?.id });
      setPast([...records, ...page]); setExhausted(page.length < 200);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  };
  return <section className="panel sentinel" aria-labelledby="sentinel-heading">
    <div className="sentinel-header">
      <div><h2 id="sentinel-heading">Sentinel · Time Machine</h2>
        <p>Gateway sessions record call status and tool versions. Prompt text, arguments, and results stay out of this history.</p></div>
      <button className="button subtle" onClick={() => setConfirm('clear')} disabled={!records.length}>Clear call history</button>
    </div>
    <div className="sentinel-toolbar">
      <select aria-label="Managed route" value={route} onChange={event => { setRoute(event.target.value); setSession(''); }}>
        <option value="">All managed routes</option>
        {managed.map(item => <option key={item.source_id} value={item.source_id}>{item.client_label} · {item.server_id}{item.stopped ? ' · Stopped' : ''}</option>)}
      </select>
      <select aria-label="Gateway session" value={session} onChange={event => setSession(event.target.value)}>
        <option value="">All gateway sessions</option>
        {[...new Set(records.filter(call => !route || call.source === route).map(call => call.session))].map(id => <option key={id} value={id}>{id.slice(0, 8)}</option>)}
      </select>
      <select aria-label="Call status" value={filter} onChange={event => setFilter(event.target.value)}>
        <option value="">All call statuses</option>
        {['active', 'completed', 'blocked', 'failed', 'unconfirmed'].map(state => <option key={state}>{state}</option>)}
      </select>
      <input type="search" aria-label="Filter recorded tools" placeholder="Find a recorded tool…" value={query} onChange={event => setQuery(event.target.value)} />
      {chosen ? <button className={chosen.stopped ? 'button subtle' : 'button danger-outline'} onClick={() => setConfirm(chosen.stopped ? 'resume' : 'stop')}>
        {chosen.stopped ? 'Resume managed server' : 'Stop managed server'}
      </button> : null}
    </div>
    {error ? <p className="form-error sentinel-message" role="alert">{error}</p> : null}
    {visible.length ? <ol className="sentinel-calls">
      {visible.map(call => <li key={call.id}><button className="sentinel-call" aria-pressed={selectedId === call.id} onClick={() => select(call.id)}>
        <span><strong>{call.tool}</strong><small>{call.source} · {formatTime(call.started_at)}</small></span>
        <span className="sentinel-state" data-state={call.state}>{call.state}</span>
      </button></li>)}
    </ol> : <p className="sentinel-message">{records.length ? 'No calls match these filters.' : 'Start an MCP call through a managed gateway to see it here.'}</p>}
    {!exhausted && records.length >= 200 ? <button className="button subtle sentinel-more" disabled={busy} onClick={() => void older()}>Load older calls</button> : null}
    {selected ? <div className="sentinel-evidence">
      <h3>{selected.tool}</h3>
      <p>{selected.reason ? reasons[selected.reason] ?? selected.reason : selected.state === 'unconfirmed'
        ? 'The session ended or stopped reporting before an outcome was recorded.' : `Call ${selected.state}.`}</p>
      <p>Gateway session {selected.session.slice(0, 8)}{selected.revision ? ` · Review revision ${selected.revision}` : ''}</p>
      {selected.previous_success ? <p>
        Last successful call <button className="text-button" disabled={!records.some(call => call.id === selected.previous_success)}
          onClick={() => select(selected.previous_success)}>#{selected.previous_success}</button>
        {selected.sha256 && selected.previous_sha256 && selected.sha256 !== selected.previous_sha256 ? ' · Definition changed since that call.' : ''}
      </p> : null}
      {evidence?.changes.length ? <details><summary>Recorded changes before this call</summary><ul>
        {evidence.changes.map(event => <li key={event.id}>{event.event.replaceAll('_', ' ')} · {formatTime(event.timestamp)}</li>)}
      </ul></details> : null}
      {evidence?.definition ? <details><summary>Tool definition at the time</summary><pre>{JSON.stringify(evidence.definition, null, 2)}</pre></details> : null}
      {evidence ? <details><summary>Policy comparison</summary>
        <p>{evidence.current_policy === 'version_eligible' ? 'The recorded version was eligible under the policy when opened.'
          : reasons[evidence.current_policy]}</p>
        <p>This comparison uses saved metadata. A new call would also need to pass request checks.</p>
      </details> : null}
    </div> : null}
    {confirm ? <Dialog title={confirm === 'clear' ? 'Clear Sentinel call history?' : confirm === 'stop' ? 'Stop this managed MCP server?' : 'Resume this managed MCP server?'} onClose={() => { if (!busy) setConfirm(null); }}>
      <p className="dialog-copy">{confirm === 'clear' ? 'This removes completed and inactive call records. Tool reviews and security decisions stay available.'
        : confirm === 'stop' ? `New calls to ${chosen?.server_id} will be blocked across managed routes. Calls already dispatched may finish.`
        : `Resume eligible calls to ${chosen?.server_id}. Existing blocks, quarantines, and approval rules still apply.`}</p>
      <div className="dialog-actions"><button className="button subtle" onClick={() => setConfirm(null)} disabled={busy}>Cancel</button>
        <button className="button primary" disabled={busy} onClick={() => void update()}>{confirm === 'clear' ? 'Clear history' : confirm === 'stop' ? 'Stop server' : 'Resume server'}</button></div>
    </Dialog> : null}
  </section>;
}
