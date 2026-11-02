import { useEffect, useRef, useState } from 'react';
import { request } from './bridge';
import { Disclosure } from './Disclosure';
import { MAX_HOST_CATALOG_BYTES, parseHostCatalog } from './host-catalog-utils';
import type { HostSource } from './host-catalog-utils';

export function HostedApps({ native, onImported }: { native: boolean; onImported: () => void }) {
  const [sources, setSources] = useState<HostSource[]>([]);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState('');
  const selection = useRef(0);
  useEffect(() => {
    let active = true;
    if (native) void request<HostSource[]>({ action: 'host_catalog_list' }).then(data => { if (active && selection.current === 0) setSources(data); }).catch(failure => { if (active && selection.current === 0) setError(failure instanceof Error ? failure.message : 'Saved host catalogs could not be loaded.'); });
    return () => { active = false; };
  }, [native]);
  const save = async () => {
    if (busy) return;
    setBusy(true); setError('');
    let saved = 0;
    try {
      for (const source of sources) {
        setStatus(`Saving ${source.name}…`);
        await request({ action: 'host_catalog_import', source });
        saved++;
      }
      setPending(false); setStatus(`${saved} app ${saved === 1 ? 'catalog' : 'catalogs'} saved for review.`); onImported();
    } catch (failure) { setError(`${saved} app catalogs saved. ${failure instanceof Error ? failure.message : 'Import failed.'} You can retry this import.`); setStatus(''); }
    finally { setBusy(false); }
  };
  const search = query.trim().toLowerCase();
  const visible = sources.filter(source => !search || `${source.name} ${source.description}`.toLowerCase().includes(search) || source.tools.some(tool => `${tool.name} ${tool.description}`.toLowerCase().includes(search)));
  return <section className="panel connection-setup hosted-apps">
    <Disclosure title="ChatGPT / Codex installed apps" level={2}>
      <p>Installed host apps are separate from local CLI MCP servers. Import a catalog exported from the host to inspect their app and tool descriptions.</p>
      <label className="form-label">Hosted app catalog<input type="file" accept=".json,application/json" disabled={busy} aria-label="Choose hosted app catalog" onChange={event => {
        const file = event.target.files?.[0]; if (!file) return;
        const generation = ++selection.current;
        setError(''); setStatus('');
        if (file.size > MAX_HOST_CATALOG_BYTES) { setError('Choose a catalog smaller than 16 MiB.'); return; }
        void file.text().then(text => { const parsed = parseHostCatalog(text); if (selection.current === generation) { setSources(parsed); setPending(true); setQuery(''); } }).catch(failure => { if (selection.current === generation) setError(failure instanceof Error ? failure.message : 'Catalog could not be opened.'); });
      }} /></label>
      <p className="small muted">This imports names and descriptions only. It does not connect accounts, invoke tools, import credentials, or claim a complete input schema.</p>
      {pending ? <button className="button primary" disabled={!native || busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save app catalogs to workspace'}</button> : null}
      {!native && pending ? <p className="small muted">Catalog preview only. Use the native app to save it.</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {status ? <p className="collection-status" role="status">{status}</p> : null}
    </Disclosure>
    {sources.length ? <>
      <label className="form-label catalog-search">Find an app or tool<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search names and descriptions" /></label>
      <p className="small muted catalog-count">{visible.length} apps · {sources.reduce((total, source) => total + source.tools.length, 0)} described tools · {pending ? 'Preview' : 'Imported metadata'}</p>
      {visible.map(source => <Disclosure title={source.name} key={source.source_id}>
        <p>{source.description || 'No app description was provided by the host.'}</p>
        <p className="small muted">{source.tools.length} tools exposed in this snapshot · {source.captured_at}</p>
        {!source.tools.length ? <p className="small muted">{source.visibility === 'skills_only' ? 'This plugin exposes skills rather than callable tools in this session.' : 'No callable tool descriptions are exposed to this session.'}</p> : source.tools.filter(tool => !search || `${source.name} ${source.description}`.toLowerCase().includes(search) || `${tool.name} ${tool.description}`.toLowerCase().includes(search)).map(tool => <Disclosure title={tool.name} key={tool.name} level={4}><p>{tool.description || 'No description supplied.'}</p><p className="small muted">Input schema not exported by host. Review metadata only.</p></Disclosure>)}
      </Disclosure>)}
    </> : null}
  </section>;
}
