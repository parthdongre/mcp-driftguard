import { useRef, useState } from 'react';
import { request } from './bridge';
import { Disclosure } from './Disclosure';

interface HarnessSource {
  source_id: string; config_digest: string; harness: string; name: string;
  scope: string; kind: string; config_path: string; transport: string;
  ready: boolean; issue: string | null;
}
interface ScanResult { project_dir: string; sources: HarnessSource[]; warnings: string[] }
interface FetchResult { tools: number; servers: number; warnings?: string[] }

export function HarnessConnections({ native, onCollected }: { native: boolean; onCollected: () => void }) {
  const [project, setProject] = useState('');
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [results, setResults] = useState<Record<string, string>>({});
  const [sourceErrors, setSourceErrors] = useState<Record<string, string>>({});
  const [sourceWarnings, setSourceWarnings] = useState<Record<string, string[]>>({});
  const working = useRef(false);
  const discover = async () => {
    if (working.current) return;
    working.current = true; setBusy('scan'); setError(''); setNotice(''); setScan(null); setResults({}); setSourceErrors({}); setSourceWarnings({});
    try {
      const found = await request<ScanResult>({ action: 'harness_scan', ...(project.trim() ? { project_dir: project.trim() } : {}) });
      setScan(found); setProject(found.project_dir);
      setNotice(found.sources.length ? `Found ${found.sources.length} harness connections.` : 'No connections found. Select your project directory, or configure an MCP server in Codex or Claude Code.');
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not scan harness connections.'); }
    finally { working.current = false; setBusy(''); }
  };
  const collect = async (source: HarnessSource) => {
    if (working.current || !scan) return;
    working.current = true; setBusy(source.source_id); setError(''); setNotice('');
    setSourceErrors(previous => ({ ...previous, [source.source_id]: '' }));
    setSourceWarnings(previous => ({ ...previous, [source.source_id]: [] }));
    try {
      const result = await request<FetchResult>({ action: 'harness_fetch', project_dir: scan.project_dir,
        source_id: source.source_id, config_digest: source.config_digest });
      const message = `${result.tools} ${result.tools === 1 ? 'definition' : 'definitions'} collected from ${result.servers} ${result.servers === 1 ? 'source' : 'sources'}.`;
      setResults(previous => ({ ...previous, [source.source_id]: message }));
      setSourceWarnings(previous => ({ ...previous, [source.source_id]: result.warnings ?? [] }));
      setNotice(`${message} Open Security review to inspect them.`); onCollected();
    } catch (failure) { setSourceErrors(previous => ({ ...previous, [source.source_id]: failure instanceof Error ? failure.message : 'Could not collect definitions.' })); }
    finally { working.current = false; setBusy(''); }
  };
  return <section className="panel connection-setup harness-connections" aria-label="Harness connections">
    <Disclosure title="Connect your coding harness" level={2}>
    <form onSubmit={event => { event.preventDefault(); void discover(); }}>
      <label className="form-label">Project directory<input disabled={!!busy || !native} value={project}
        onChange={event => { setProject(event.target.value); setScan(null); setResults({}); setSourceErrors({}); setNotice(''); setError(''); }}
        placeholder="Optional absolute path, e.g. /Users/you/my-project" />
        <small>Leave blank to scan user configuration. Select a project to include its MCP settings.</small></label>
      <button className="button primary" disabled={!native || !!busy} type="submit">{busy === 'scan' ? 'Scanning…' : 'Find harness connections'}</button>
    </form>
    {!native ? <p className="scope-note small">Open the native desktop app to discover local harnesses and fetch definitions. Browser preview cannot access your local configuration.</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    <div role="status" aria-live="polite">{notice ? <p className="harness-notice">{notice}</p> : null}</div>
    {scan?.warnings.map((warning, index) => <p className="form-error" key={index}>{warning}</p>)}
    </Disclosure>
    {scan?.sources.length ? <div className="harness-list">{scan.sources.map(source => <article className="harness-source" key={source.source_id}>
      <Disclosure title={source.name}>
        <p className="small muted">{source.harness === 'codex' ? 'Codex' : 'Claude Code'} · {source.scope}</p>
        <p>{source.kind === 'runtime' ? source.harness === 'codex' ? 'Read the MCP catalog through Codex App Server, using its configuration and authentication.' : 'Read the tools Claude Code exposes through its MCP server.' : `Configured MCP server · ${source.transport}`}</p>
        <Disclosure title="Configuration location" level={4}><code>{source.config_path}</code></Disclosure>
        {source.issue ? <p className="form-error">{source.issue}</p> : null}
        {sourceErrors[source.source_id] ? <p className="form-error" role="alert">{sourceErrors[source.source_id]}</p> : null}
        {sourceWarnings[source.source_id]?.map((warning, index) => <p className="form-error" key={index}>{warning}</p>)}
        {results[source.source_id] ? <p className="harness-notice">{results[source.source_id]}</p> : null}
        <p className="small muted">Fetching starts this connection with your user permissions and reads definitions without calling tools.</p>
      <button className="button subtle" disabled={!source.ready || !!busy} onClick={() => void collect(source)}>
        {busy === source.source_id ? 'Fetching…' : results[source.source_id] ? 'Refresh definitions' : 'Fetch definitions'}
      </button>
      </Disclosure>
    </article>)}</div> : null}
    <Disclosure title="Connection details">
      <p>Scanning reads configuration only. Fetching starts the selected server, or Codex’s configured MCP servers, with your user permissions. Existing harness configuration stays unchanged.</p>
      <p>Collected definitions appear in Security review and Tool evolution. Live interception requires routing the client through the gateway. Codex exposes its MCP catalog here; built-in shell and editing tools are outside that catalog.</p>
    </Disclosure>
  </section>;
}
