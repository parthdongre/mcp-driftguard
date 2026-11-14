import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { ApprovalMode, MonitoringSettings } from './types';
import { request } from './bridge';
import { Disclosure } from './Disclosure';

export interface GraphPreferences {
  startup: 'graph' | 'overview';
  follow: boolean;
  highlight: boolean;
  showChecks: boolean;
}

const preferenceKey = 'driftguard.graph.v1';
const graphDefaults: GraphPreferences = {
  startup: 'graph', follow: true, highlight: true, showChecks: true,
};

export const defaultMonitoring: MonitoringSettings = {
  active_seconds: 15, idle_seconds: 300, active_window_seconds: 120,
  discovery_seconds: 300, discovery_enabled: true,
};

export function readGraphPreferences(): GraphPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem(preferenceKey) || '{}');
    return {
      startup: stored.startup === 'overview' ? 'overview' : 'graph',
      follow: typeof stored.follow === 'boolean' ? stored.follow : graphDefaults.follow,
      highlight: typeof stored.highlight === 'boolean' ? stored.highlight : graphDefaults.highlight,
      showChecks: typeof stored.showChecks === 'boolean' ? stored.showChecks : graphDefaults.showChecks,
    };
  } catch {
    return graphDefaults;
  }
}

const intervals = [
  { field: 'active_seconds', label: 'Recently used gateway check interval (seconds)', min: 5, max: 300 },
  { field: 'active_window_seconds', label: 'Recently used window (seconds)', min: 5, max: 3600 },
  { field: 'idle_seconds', label: 'Idle gateway check interval (seconds)', min: 15, max: 3600 },
  { field: 'discovery_seconds', label: 'Discovery check interval (seconds)', min: 60, max: 3600 },
] as const;

interface Props {
  monitoring: MonitoringSettings | null;
  error: string;
  preferences: GraphPreferences;
  onPreferences: (value: GraphPreferences) => void;
  onSave: (value: MonitoringSettings) => Promise<void>;
}

export function McpSettings({ monitoring, error, preferences, onPreferences, onSave }: Props) {
  const [edited, setDraft] = useState<MonitoringSettings | null>(null);
  const draft = edited ?? monitoring ?? defaultMonitoring;
  const [message, setMessage] = useState('');
  const [failure, setFailure] = useState(false);
  const [busy, setBusy] = useState(false);

  const changePreferences = (next: GraphPreferences) => {
    try {
      localStorage.setItem(preferenceKey, JSON.stringify(next));
      onPreferences(next);
      setMessage('Graph preferences saved.');
      setFailure(false);
    } catch {
      setMessage('The app could not save graph preferences.');
      setFailure(true);
    }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (draft.active_seconds > draft.idle_seconds || draft.active_seconds > draft.active_window_seconds) {
      setFailure(true);
      setMessage('The recently used interval must fit within both the idle interval and the recently used window.');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      await onSave(draft);
      setDraft(null);
      setFailure(false);
      setMessage('Monitoring settings saved.');
    } catch (error) {
      setFailure(true);
      setMessage(error instanceof Error ? error.message : 'Could not save monitoring settings.');
    } finally {
      setBusy(false);
    }
  };

  return <section className="panel compact-panel"><Disclosure title="MCP monitoring and graph" level={2}>
    {monitoring ? <form className="mcp-settings" onSubmit={event => void save(event)}>
      <fieldset disabled={busy}>
        <legend>Catalog checks</legend>
        <p>Gateway intervals apply to running sessions. Discovery checks run while DriftGuard is open.</p>
        <div className="mcp-settings-intervals">
          {intervals.map(({ field, label, min, max }) => <label key={field}>{label}
            <input type="number" required min={min} max={max} value={Number.isNaN(draft[field]) ? '' : draft[field]}
              onChange={event => setDraft({ ...draft, [field]: event.target.valueAsNumber })} />
          </label>)}
        </div>
        <label className="mcp-setting-toggle"><input type="checkbox" checked={draft.discovery_enabled}
          onChange={event => setDraft({ ...draft, discovery_enabled: event.target.checked })} />
          Refresh discovered MCP catalogs automatically</label>
        <div className="mcp-settings-actions">
          <button type="submit" className="button primary">Save monitoring settings</button>
          <button type="button" className="button subtle" onClick={() => setDraft(defaultMonitoring)}>Restore check defaults</button>
        </div>
      </fieldset>
    </form> : !error ? <p className="small muted" role="status">Reading monitoring settings…</p> : null}
    <fieldset className="mcp-settings">
      <legend>Graph and activity</legend>
      <label className="mcp-setting-toggle">Startup view
        <select value={preferences.startup}
          onChange={event => changePreferences({ ...preferences, startup: event.target.value === 'overview' ? 'overview' : 'graph' })}>
          <option value="graph">MCP graph</option><option value="overview">Overview</option>
        </select>
      </label>
      {([
        ['follow', 'Follow the most recent tool call'],
        ['highlight', 'Highlight tool calls on the graph'],
        ['showChecks', 'Show successful catalog checks in the activity log'],
      ] as const).map(([key, label]) =>
        <label className="mcp-setting-toggle" key={key}><input type="checkbox" checked={preferences[key]}
          onChange={event => changePreferences({ ...preferences, [key]: event.target.checked })} />{label}</label>)}
    </fieldset>
    {message || error ? <p className="small" role={failure || !message ? 'alert' : 'status'}>{message || error}</p> : null}
  </Disclosure></section>;
}

export function ApprovalSettings() {
  const [mode, setMode] = useState<ApprovalMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let mounted = true;
    void request<ApprovalMode>({ action: 'approval_mode' }).then(value => {
      if (mounted) setMode(value);
    }).catch(() => { if (mounted) setMessage('Could not load automatic approvals.'); });
    return () => { mounted = false; };
  }, []);
  const save = async (value: ApprovalMode) => {
    setBusy(true);
    setMessage('');
    try {
      setMode(await request<ApprovalMode>({ action: 'set_approval_mode', mode: value }));
      setMessage('Approval policy saved.');
    } catch {
      setMessage('Could not save the approval policy.');
    } finally {
      setBusy(false);
    }
  };
  return <section className="panel compact-panel"><Disclosure title="Automatic MCP approvals" level={2}>
    <div className="mcp-settings">
      <label className="mcp-setting-toggle">First-seen tools
        <select value={mode ?? ''} disabled={!mode || busy}
          onChange={event => void save(event.target.value as ApprovalMode)}>
          {!mode ? <option value="">Loading…</option> : null}
          <option value="manual">Require manual approval (default)</option>
          <option value="read_only">Approve declared read-only tools</option>
          <option value="all_first_seen">Approve all compatible first-seen tools</option>
        </select>
      </label>
      <p>Automatic modes apply only to tools in a server's first catalog. Tools a server adds later, and any definition with hidden characters, always go to review. Read-only labels are declared by the server and are not verified. The all-tools option includes tools that can make changes. Existing approvals remain in effect.</p>
      <p>Changed definitions follow the configured decision model or go to review. Blocks and quarantine take precedence.</p>
      {message ? <p role="status">{message}</p> : null}
    </div>
  </Disclosure></section>;
}
