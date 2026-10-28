import { useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import { Disclosure } from './Disclosure';
import { collectionSummary } from './fetch-utils';
import type { FetchResult } from './fetch-utils';

interface HarnessSource {
  source_id: string; config_digest: string; harness: string; name: string;
  scope: string; kind: string; config_path: string; transport: string;
  ready: boolean; issue: string | null;
}
interface ScanResult { project_dir: string; sources: HarnessSource[]; warnings: string[] }
interface Outcome { result?: FetchResult; error?: string }

export function HarnessConnections({ native, onCollected }: { native: boolean; onCollected: () => void }) {
  const [project, setProject] = useState('');
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [busy, setBusy] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const working = useRef(false);
  useEffect(() => {
    if (!busy || busy === 'scan') return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  const discover = async () => {
    if (working.current) return;
    working.current = true; setBusy('scan'); setError(''); setNotice(''); setScan(null); setOutcomes({});
    try {
      const found = await request<ScanResult>({ action: 'harness_scan', ...(project.trim() ? { project_dir: project.trim() } : {}) });
      setScan(found); setProject(found.project_dir);
      setNotice(found.sources.length ? `${found.sources.length} local connections found.` : 'No local CLI connections found. Hosted apps use the app catalog import above.');
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not scan local connections.'); }
    finally { working.current = false; setBusy(''); }
  };
  const collect = async (source: HarnessSource) => {
    if (working.current || !scan) return;
    working.current = true; setBusy(source.source_id); setElapsed(0); setError(''); setNotice('');
    setOutcomes(previous => ({ ...previous, [source.source_id]: {} }));
    try {
      const result = await request<FetchResult>({ action: 'harness_fetch', project_dir: scan.project_dir,
        source_id: source.source_id, config_digest: source.config_digest });
      setOutcomes(previous => ({ ...previous, [source.source_id]: { result } }));
      onCollected();
    } catch (failure) { setOutcomes(previous => ({ ...previous, [source.source_id]: { error: failure instanceof Error ? failure.message : 'Could not collect definitions.' } })); }
    finally { working.current = false; setBusy(''); }
  };
  const active = scan?.sources.find(source => source.source_id === busy);
  return <section className="panel connection-setup harness-connections" aria-label="Harness connections">
    <Disclosure title="Connect your coding harness" level={2}>
      <p>Find local Codex and Claude Code MCP servers. Apps installed in ChatGPT/Codex use the hosted catalog above.</p>
      <form onSubmit={event => { event.preventDefault(); void discover(); }}>
        <div className="form-label"><label htmlFor="harness-project">Project directory</label><input id="harness-project" aria-describedby="harness-project-help" disabled={!!busy || !native} value={project}
          onChange={event => { setProject(event.target.value); setScan(null); setOutcomes({}); setNotice(''); setError(''); }}
          placeholder="Optional absolute project path" />
          <small id="harness-project-help">Leave blank for user configuration.</small></div>
        <button className="button primary" disabled={!native || !!busy} type="submit">{busy === 'scan' ? 'Scanning…' : 'Find harness connections'}</button>
      </form>
      {!native ? <p className="small muted">Local discovery requires the native desktop app.</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {notice ? <p className="collection-status" role="status">{notice}</p> : null}
      {scan?.warnings.map((warning, index) => <p className="collection-warning" key={index}>{warning}</p>)}
    </Disclosure>
    {active ? <p className="fetch-progress" role="status" aria-live="polite">Fetching {active.name} · {elapsed}s <span>Discovery may take up to 90 seconds. Reviews remain available.</span></p> : null}
    {scan?.sources.length ? <div className="harness-list">{scan.sources.map(source => {
      const outcome = outcomes[source.source_id];
      const result = outcome?.result;
      const summary = result ? collectionSummary(result) : null;
      return <article className="harness-source" key={source.source_id}><Disclosure title={source.name}>
        <p className="source-meta">{source.harness === 'codex' ? 'Codex' : 'Claude Code'} · {source.scope} · {source.transport}</p>
        <p className="source-description">{source.kind === 'runtime' ? source.harness === 'codex' ? 'MCP tools exposed by the local Codex CLI.' : 'Tools exposed by Claude Code.' : 'Configured local MCP connection.'}</p>
        <div className="source-actions"><button className="button subtle" disabled={!source.ready || !!busy} title="Starts the selected connection and reads definitions without calling tools." onClick={() => void collect(source)}>
          {busy === source.source_id ? `Fetching… ${elapsed}s` : result && result.tools > 0 ? 'Refresh definitions' : 'Fetch definitions'}
        </button>{summary ? <span className={`collection-status ${summary.tone}`} role="status">{summary.message}</span> : null}</div>
        {source.issue ? <p className="collection-warning">{source.issue}</p> : null}
        {outcome?.error ? <p className="form-error" role="alert">{outcome.error}</p> : null}
        {result?.warnings?.length ? <Disclosure title="Collection details" className="inline-detail" level={4}><ul>{result.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></Disclosure> : null}
        <Disclosure title="Configuration location" className="inline-detail" level={4}><code>{source.config_path}</code></Disclosure>
      </Disclosure></article>;
    })}</div> : null}
    <Disclosure title="Connection details"><p>Scanning reads configuration. Fetching starts owned discovery processes with your user permissions and never calls tools. Existing harness settings stay unchanged. Collected definitions do not intercept client calls.</p></Disclosure>
  </section>;
}
