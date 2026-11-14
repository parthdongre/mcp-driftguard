import { useState } from 'react';
import { Icon } from './Icon';
import { formatTime } from './review-utils';
import './harness-helpers.css';

interface Helper {
  harness: string;
  kind: string;
  name: string;
  location: string;
  sha256: string;
  enabled: boolean | null;
}

interface HelperChange extends Helper {
  id: number;
  observed_at: string;
  change: 'added' | 'modified' | 'removed';
}

export interface HelpersReport {
  helpers: Helper[];
  changes: HelperChange[];
  issues: string[];
  new_changes: number;
}

const labels: Record<string, string> = {
  skill: 'Skill', plugin: 'Plugin', hook: 'Hook', subagent: 'Subagent',
  instruction: 'Instruction', command: 'Command', permission: 'Permission',
};

export function HarnessHelpers({ report, error, loading, onScan }: {
  report: HelpersReport | null; error: string; loading: boolean; onScan: () => void;
}) {
  const [view, setView] = useState<'inventory' | 'changes'>('inventory');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('');
  const [harness, setHarness] = useState('');
  const [limit, setLimit] = useState(40);
  const records: (Helper | HelperChange)[] = view === 'inventory' ? report?.helpers ?? [] : report?.changes ?? [];
  const kinds = [...new Set(records.map(item => item.kind))].sort();
  const harnesses = [...new Set(records.map(item => item.harness))].sort();
  const term = query.trim().toLowerCase();
  const matches = records.filter(item => (!kind || item.kind === kind) &&
    (!harness || item.harness === harness) && `${item.name} ${item.location}`.toLowerCase().includes(term));
  return <section className="panel helper-panel" aria-labelledby="harness-helpers-heading">
    <div className="helper-heading">
      <div>
        <h2 id="harness-helpers-heading">Harness helpers</h2>
        <p>Track local Codex and Claude Code helpers and permission settings.</p>
      </div>
      <button className="button subtle" onClick={onScan} disabled={loading}><Icon name="refresh" size={15} />Scan helpers</button>
    </div>
    {loading ? <p className="helper-message" role="status">Scanning harness helpers…</p> : null}
    {error ? <p className="form-error helper-message" role="alert">{error}</p> : null}
    {report?.issues.length ? <details className="helper-message"><summary>{report.issues.length} helper locations unavailable</summary>
      <p>DriftGuard kept the last inventory for these locations.</p>
      <ul>{report.issues.map(location => <li key={location}><code>{location}</code></li>)}</ul>
    </details> : null}
    {report ? <>
      <div className="helper-toolbar">
        <div className="segmented" role="group" aria-label="Helper view">
          <button aria-pressed={view === 'inventory'} onClick={() => { setView('inventory'); setKind(''); setHarness(''); setLimit(40); }}>Inventory</button>
          <button aria-pressed={view === 'changes'} onClick={() => { setView('changes'); setKind(''); setHarness(''); setLimit(40); }}>Recent changes</button>
        </div>
        <label className="search-field"><Icon name="search" size={15} />
          <input type="search" aria-label="Search helpers" placeholder="Search helpers…" value={query}
            onChange={event => { setQuery(event.target.value); setLimit(40); }} />
        </label>
        <select aria-label="Filter helper type" value={kind} onChange={event => { setKind(event.target.value); setLimit(40); }}>
          <option value="">All helper types</option>
          {kinds.map(value => <option key={value} value={value}>{labels[value] ?? value}</option>)}
        </select>
        <select aria-label="Filter helper harness" value={harness} onChange={event => { setHarness(event.target.value); setLimit(40); }}>
          <option value="">All harnesses</option>
          {harnesses.map(value => <option key={value}>{value}</option>)}
        </select>
      </div>
      <p className="helper-count" role="status">{matches.length} {view === 'inventory' ? 'helpers' : 'changes'}</p>
      {matches.length ? <ul className="helper-items">
        {matches.slice(0, limit).map(item => {
          const change = 'change' in item ? item : null;
          return <li key={change?.id ?? JSON.stringify([item.harness, item.kind, item.location, item.name])}>
            <div>
              <strong>{item.name}</strong>
              <p>{item.harness} · {labels[item.kind] ?? item.kind}</p>
              <code title={item.sha256}>{item.location}</code>
            </div>
            <div className="helper-status">
              {item.enabled !== null ? <span className="badge">{item.enabled ? 'Enabled' : 'Disabled'}</span> : null}
              {change ? <><span className="badge">{change.change}</span><time dateTime={change.observed_at}>{formatTime(change.observed_at)}</time></> : null}
            </div>
          </li>;
        })}
      </ul> : <p className="helper-message">{query || kind || harness ? 'No helpers match these filters.' : view === 'inventory' ? 'No helpers found in the supported user settings.' : 'No changes detected since the first scan.'}</p>}
      {limit < matches.length ? <button className="button subtle helper-more" onClick={() => setLimit(value => value + 40)}>Show more</button> : null}
    </> : null}
  </section>;
}
