import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { AuditEvent, BridgeRequest, HistoryVersion, Page, Review, ToolRecord, Workspace } from './types';
import { DemoWorkspace, emptyOverview, hasNativeBridge, isPending, request, statusLabel, toolKey } from './bridge';
import { Icon } from './Icon';
import type { IconName } from './Icon';
import { Dialog } from './Dialog';
import { ReviewPanel, classLabels } from './ReviewPanel';
import { Timeline } from './Timeline';
import { AnnotationLab } from './AnnotationLab';
import { ConnectionSetup } from './ConnectionSetup';
import { ConnectionHealth } from './ConnectionHealth';
import { Disclosure } from './Disclosure';
import { HarnessConnections } from './HarnessConnections';
import { HostedApps } from './HostedApps';
import { downloadText, formatTime, matchesActivityFilter, MAX_IMPORT_BYTES, parseDefinitions, safeAuditExport } from './review-utils';

const navigation: { page: Page; label: string; icon: IconName; shortcut?: string }[] = [
  { page: 'overview', label: 'Overview', icon: 'overview', shortcut: '1' },
  { page: 'connections', label: 'MCP connections', icon: 'connections', shortcut: '2' },
  { page: 'review', label: 'Security review', icon: 'review', shortcut: '3' },
  { page: 'timeline', label: 'Tool evolution', icon: 'timeline', shortcut: '4' },
  { page: 'activity', label: 'Security activity', icon: 'activity', shortcut: '5' },
  { page: 'research', label: 'Research laboratory', icon: 'research', shortcut: '6' },
];
const initialWorkspace: Workspace = { overview: emptyOverview, tools: [], activity: [] };
type Theme = 'system' | 'dark' | 'light';

function Empty({ icon, title, children, action, onAction }: { icon: IconName; title: string; children: string; action?: string; onAction?: () => void }) {
  return <div className="empty"><span className="empty-icon"><Icon name={icon} size={32} /></span><h2>{title}</h2><p>{children}</p>
    {action ? <button className="button primary" onClick={onAction}>{action}<Icon name="arrow" size={16} /></button> : null}</div>;
}

function ToolRow({ tool, selected, onClick }: { tool: ToolRecord; selected?: boolean; onClick: () => void }) {
  return <button className={`tool-row compact-tool ${selected ? 'selected' : ''}`} onClick={onClick} aria-pressed={selected} aria-label={`${tool.tool_name} · ${tool.server_id}`} title={`${tool.tool_name} · ${tool.server_id}`}>
    <span className="tool-text"><strong>{tool.tool_name}</strong></span><Icon name="chevron" size={15} />
  </button>;
}

export default function App() {
  const [page, setPage] = useState<Page>('overview');
  const [workspace, setWorkspace] = useState<Workspace>(initialWorkspace);
  const [demo, setDemo] = useState<DemoWorkspace | null>(null);
  const [selectedKey, setSelectedKey] = useState('');
  const [review, setReview] = useState<Review | null>(null);
  const [history, setHistory] = useState<HistoryVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [activityFilter, setActivityFilter] = useState('all');
  const [refreshCount, setRefreshCount] = useState(0);
  const [dialog, setDialog] = useState<'import' | 'approve' | 'export' | null>(null);
  const [theme, setTheme] = useState<Theme>(() => {
    try { const stored = localStorage.getItem('driftguard.theme.v1'); return stored === 'light' || stored === 'dark' ? stored : 'system'; } catch { return 'system'; }
  });
  const requestSequence = useRef(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const native = hasNativeBridge();
  const selectedTool = workspace.tools.find(tool => toolKey(tool) === selectedKey) ?? workspace.tools[0];
  const send = useCallback(<T,>(payload: BridgeRequest): Promise<T> => demo ? demo.request<T>(payload) : request<T>(payload), [demo]);

  const reload = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true); setError('');
    if (!demo && !native) { setWorkspace(initialWorkspace); setLoading(false); return; }
    try {
      const [overview, tools, activity] = await Promise.all([
        send<Workspace['overview']>({ action: 'overview' }), send<ToolRecord[]>({ action: 'list_tools' }), send<AuditEvent[]>({ action: 'activity' }),
      ]);
      if (sequence === requestSequence.current) { setWorkspace({ overview, tools, activity }); setRefreshCount(count => count + 1); }
    } catch (failure) { if (sequence === requestSequence.current) setError(failure instanceof Error ? failure.message : 'Unable to read the local workspace.'); }
    finally { if (sequence === requestSequence.current) setLoading(false); }
  }, [demo, native, send]);

  useEffect(() => { void reload(); return () => { requestSequence.current += 1; }; }, [reload]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [page]);
  useEffect(() => {
    let active = true;
    setReview(null); setHistory([]);
    if (!selectedTool || (!native && !demo)) return;
    const payload = { server_id: selectedTool.server_id, tool_name: selectedTool.tool_name };
    void Promise.all([send<Review>({ action: 'review', ...payload }), send<HistoryVersion[]>({ action: 'history', ...payload })])
      .then(([nextReview, versions]) => { if (active) { setReview(nextReview); setHistory(versions); } })
      .catch(failure => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load review evidence.'); });
    return () => { active = false; };
  }, [selectedTool?.server_id, selectedTool?.tool_name, refreshCount, native, demo, send]);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme; };
    apply(); media.addEventListener('change', apply);
    try { localStorage.setItem('driftguard.theme.v1', theme); } catch { /* A theme preference is optional. */ }
    return () => media.removeEventListener('change', apply);
  }, [theme]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (document.querySelector('dialog[open]')) return;
      if (event.metaKey || event.ctrlKey) {
        const destination = navigation.find(item => item.shortcut === event.key);
        if (destination) { event.preventDefault(); setPage(destination.page); }
        else if (event.key === 'k') { event.preventDefault(); searchRef.current?.focus(); }
        else if (event.key === ',') { event.preventDefault(); setPage('settings'); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const openReview = (tool: ToolRecord) => { setSelectedKey(toolKey(tool)); setPage('review'); setQuery(''); };
  const decide = async (action: 'approve' | 'deny' | 'quarantine') => {
    if (!review || busy) return;
    if (action === 'approve' && dialog !== 'approve') { setDialog('approve'); return; }
    setBusy(true); setError('');
    try {
      await send({ action, server_id: review.server_id, tool_name: review.tool_name, expected_sha256: review.sha256, expected_revision: review.revision });
      setDialog(null); setNotice(`${demo ? 'Demo decision' : 'Decision'} saved: ${statusLabel(action === 'approve' ? 'approved' : action === 'deny' ? 'denied' : 'quarantined')}.`);
      await reload();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'The decision could not be saved.'); }
    finally { setBusy(false); }
  };
  const startDemo = () => { setDemo(new DemoWorkspace()); setSelectedKey(''); setPage('overview'); setNotice('Guided demo opened. All observations and decisions are isolated fixtures.'); };
  const exitDemo = () => { setDemo(null); setSelectedKey(''); setWorkspace(initialWorkspace); setPage('overview'); setNotice('Guided demo closed. Fixture decisions were discarded.'); };
  const filteredTools = workspace.tools.filter(tool => `${tool.tool_name} ${tool.server_id} ${tool.description ?? ''}`.toLowerCase().includes(query.toLowerCase()));
  const pending = workspace.tools.filter(isPending);
  const events = workspace.activity.filter(event => matchesActivityFilter(event.event, activityFilter) && `${event.event} ${event.server_id ?? ''} ${event.tool_name ?? ''}`.toLowerCase().includes(query.toLowerCase()));
  const sources = [...new Set([...(workspace.overview.server_list ?? []).map(server => server.server_id), ...workspace.tools.map(tool => tool.server_id)])];
  const heading = page === 'settings' ? 'Settings' : navigation.find(item => item.page === page)?.label ?? 'Overview';

  return <div className="app-shell">
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className="sidebar"><div className="brand"><span className="brand-mark"><Icon name="shield" size={23} /></span><div><strong>DriftGuard</strong><span>MCP SECURITY WORKSPACE</span></div></div>
      <div className="workspace-label">WORKSPACE <span>LOCAL</span></div>
      <nav aria-label="Main navigation">{navigation.map(item => <button key={item.page} aria-label={item.label} aria-current={page === item.page ? 'page' : undefined} className={`nav-item ${page === item.page ? 'active' : ''}`} onClick={() => { setPage(item.page); setQuery(''); }}>
        <Icon name={item.icon} /><span>{item.label}</span>{item.page === 'review' && workspace.overview.pending > 0 ? <span className="nav-count">{workspace.overview.pending}</span> : null}
      </button>)}</nav>
      <div className="sidebar-bottom"><div className="local-note"><Icon name="lock" size={15} /><span>Private by default<small>Analysis stays on this device</small></span></div>
        <button className={`nav-item ${page === 'settings' ? 'active' : ''}`} aria-label="Settings" onClick={() => setPage('settings')} aria-current={page === 'settings' ? 'page' : undefined}><Icon name="settings" /><span>Settings</span><kbd>⌘ ,</kbd></button>
        <div className="sidebar-version"><span>RESEARCH PREVIEW</span><span>0.1</span></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb">Workspace <Icon name="chevron" size={12} /><strong>{heading}</strong></div>
      <div className="topbar-actions"><span className={`connection-state ${demo ? 'fixture' : ''}`}><span className="dot" />{demo ? 'Guided demo' : native ? 'Local desktop' : 'Browser preview'}</span>
        <button className="icon-button" aria-label="Refresh local workspace" title="Refresh local workspace" disabled={loading} onClick={() => void reload()}><Icon name="refresh" size={17} /></button></div></header>
      <div className={`mode-banner ${demo ? 'demo' : ''}`}><Icon name={demo ? 'research' : 'lock'} size={15} /><span>{demo ? 'Isolated research fixture · No connected clients · Decisions are discarded when you exit' : native ? 'Protection covers only MCP calls explicitly routed through the configured gateway.' : 'Browser preview · Native gateway unavailable · No MCP connections are protected'}</span>
        {demo ? <button onClick={exitDemo}>Exit demo</button> : <button onClick={startDemo}>Explore guided demo <Icon name="arrow" size={13} /></button>}</div>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading"><div><h1>{heading}</h1></div>
          {page === 'overview' || page === 'connections' ? <button className="button primary" onClick={() => setDialog('import')} disabled={!!demo}><Icon name="plus" size={16} />Import definitions</button> : null}
          {page === 'activity' ? <button className="button subtle" disabled={!events.length} onClick={() => setDialog('export')}><Icon name="download" size={16} />Export summary</button> : null}
        </div>
        {error ? <div className="error-banner" role="alert"><Icon name="alert" size={18} /><span>{error}</span><button className="icon-button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div> : null}
        {notice ? <div className="notice" role="status"><Icon name="check" size={15} /><span>{notice}</span><button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss notification"><Icon name="close" size={15} /></button></div> : null}
        {loading ? <div className="loading-line" role="status">Reading local workspace…</div> : null}

        {page === 'overview' ? <>
          <section className="panel compact-panel"><Disclosure title={demo ? 'Demonstration workspace' : 'Protection scope'} level={2}><p>{demo ? 'A real deterministic detector trace, presented as an isolated learning scenario.' : workspace.overview.scope}</p><p>{demo ? 'Fixture mode' : 'Review workspace'}</p></Disclosure></section>
          <div className="stats-grid">{[['Definition sources', workspace.overview.servers], ['Observed tools', workspace.overview.tools], ['Needs review', workspace.overview.pending], ['Quarantined', workspace.overview.quarantined]].map(([label, value]) => <div className="stat" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
          <div className="overview-split">
            <section className="panel"><div className="section-heading"><h2>Review queue <span className="number-label">{pending.length}</span></h2><button className="text-button" onClick={() => setPage('review')}>View all <Icon name="arrow" size={15} /></button></div>
              {pending.length ? <div className="tool-list">{pending.slice(0, 5).map(tool => <ToolRow key={toolKey(tool)} tool={tool} onClick={() => openReview(tool)} />)}</div> : <div className="inline-empty"><h3>{workspace.tools.length ? 'Your review queue is clear' : 'Trust starts with a review'}</h3><button className="text-button" disabled={!!demo} onClick={() => setDialog('import')}>Import definitions <Icon name="arrow" size={14} /></button></div>}
            </section>
            <section className="panel activity-panel"><div className="section-heading"><h2>Recent activity</h2></div>
              {workspace.activity.length ? <div className="event-list">{workspace.activity.slice(0, 4).map((event, index) => <Disclosure title={event.event.replaceAll('_', ' ')} key={String(event.id ?? index)}><p>{event.tool_name ?? 'Workspace'} · {formatTime(event.timestamp)}</p></Disclosure>)}</div> : <div className="inline-empty"><h3>No recorded events</h3></div>}
            </section>
          </div>
          <section className="panel compact-panel"><Disclosure title="About tool review" level={2}>
            <Disclosure title="Definitions are evidence"><p>They describe claims, not verified behavior.</p></Disclosure>
            <Disclosure title="Trust is version bound"><p>Approvals apply to an exact definition.</p></Disclosure>
            <Disclosure title="History matters"><p>Small changes can accumulate over time.</p></Disclosure>
          </Disclosure></section>
        </> : null}

        {page === 'connections' ? <>
          {!demo ? <><HostedApps native={native} onImported={() => { void reload(); }} /><HarnessConnections native={native} onCollected={() => { void reload(); }} /><ConnectionSetup native={native} /><ConnectionHealth native={native} /></> : <section className="panel compact-panel"><Disclosure title="Connect your coding harness" level={2}><p>Exit the guided demo to connect your local harness.</p><button className="button primary" onClick={exitDemo}>Exit demo and connect</button></Disclosure></section>}
          <section className="panel compact-panel"><Disclosure title="Definition sources" level={2}>
            {sources.length ? sources.map(source => <Disclosure title={workspace.overview.server_list?.find(item => item.server_id === source)?.display_name || source} key={source}>
              <p>{workspace.tools.filter(tool => tool.server_id === source).length} observed tools · {demo ? 'Fixture source' : 'Recorded definitions'}</p>
              <button className="button subtle" disabled={!workspace.tools.some(item => item.server_id === source)} onClick={() => { const tool = workspace.tools.find(item => item.server_id === source); if (tool) openReview(tool); }}>Review tools <Icon name="arrow" size={15} /></button>
            </Disclosure>) : <Empty icon="connections" title="Add your first definition source" action="Import tool definitions" onAction={() => setDialog('import')}>Choose an exported MCP tools/list result. The import is local and does not execute server code.</Empty>}
          </Disclosure></section>
          <section className="panel compact-panel"><Disclosure title="From observation to protection" level={2}>
            <Disclosure title="Inspect the server"><p>Review its executable, origin, permissions, and declared tools before running it.</p></Disclosure>
            <Disclosure title="Route your MCP client"><p>Use the gateway CLI and bind the server identity to the same local database. Definition collection alone does not intercept client calls.</p></Disclosure>
            <Disclosure title="Review exact versions"><p>New or changed definitions require a decision. Calls outside the gateway bypass this protection.</p></Disclosure>
          </Disclosure></section>
        </> : null}

        {page === 'review' || page === 'timeline' ? workspace.tools.length ? <div className="review-layout"><aside className="review-sidebar"><label className="search-field"><Icon name="search" size={16} /><input ref={searchRef} placeholder="Find a tool…" aria-label="Search tools" value={query} onChange={event => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label><div className="list-label">OBSERVED TOOLS <span>{filteredTools.length}</span></div>{filteredTools.map(tool => <ToolRow key={toolKey(tool)} tool={tool} selected={toolKey(tool) === toolKey(selectedTool)} onClick={() => setSelectedKey(toolKey(tool))} />)}{!filteredTools.length ? <p className="no-results">No matching tools.</p> : null}</aside><section className="review-workspace">{page === 'timeline' ? <Timeline key={selectedKey || selectedTool?.tool_name} history={history} onReview={() => setPage('review')} /> : review ? <ReviewPanel review={review} busy={busy} onDecision={action => void decide(action)} onTimeline={() => setPage('timeline')} /> : <div className="loading-evidence" role="status">Reading review evidence…</div>}</section></div> : <section className="panel"><Empty icon={page === 'review' ? 'review' : 'timeline'} title={page === 'review' ? 'No definitions to review yet' : 'Every tool has a history'} action="Explore guided demo" onAction={startDemo}>Import tool definitions in MCP connections, or explore an isolated detector trace to see the workflow.</Empty></section> : null}

        {page === 'activity' ? <section className="panel compact-panel">
          <div className="activity-toolbar"><label className="search-field"><Icon name="search" size={16} /><input ref={searchRef} aria-label="Search security activity" placeholder="Search activity…" value={query} onChange={event => setQuery(event.target.value)} /></label><label className="filter-label">Event <select value={activityFilter} onChange={event => setActivityFilter(event.target.value)}><option value="all">All events</option><option value="approve">Approvals</option><option value="quarantine">Quarantines</option><option value="deny">Denials</option><option value="observ">Observations</option></select></label><span className="small muted">{events.length} events</span></div>
          {events.length ? events.map((event, index) => <Disclosure title={event.event.replaceAll('_', ' ')} key={String(event.id ?? index)} level={2}>
            <p>{event.tool_name ?? 'Workspace'} · {event.server_id ?? 'Local'}</p><p>{formatTime(event.timestamp)}</p>
            {event.detail ? <pre>{typeof event.detail === 'string' ? event.detail : JSON.stringify(event.detail, null, 2)}</pre> : null}
          </Disclosure>) : <Empty icon="activity" title={query || activityFilter !== 'all' ? 'No matching events' : 'No security events recorded'}>Observations and decisions will appear here as you use the local workspace.</Empty>}
        </section> : null}

        <div hidden={page !== 'research'}><AnnotationLab /></div>

        {page === 'settings' ? <div className="settings-layout">
          <section className="panel compact-panel"><Disclosure title="Appearance" level={2}>
            <Disclosure title="Color theme"><p>Follows your device when System is selected.</p><div className="segmented">{(['system', 'light', 'dark'] as Theme[]).map(value => <button key={value} aria-pressed={theme === value} onClick={() => setTheme(value)}>{value === 'system' ? 'System' : value === 'light' ? <><Icon name="sun" size={14} />Light</> : <><Icon name="moon" size={14} />Dark</>}</button>)}</div></Disclosure>
            <Disclosure title="Typography"><p>Uses your device’s native interface font, including San Francisco on macOS. Text scales with your browser or system zoom.</p></Disclosure>
            <Disclosure title="Reduced motion"><p>Respects your operating system’s accessibility preference.</p><span className="badge">System controlled</span></Disclosure>
          </Disclosure></section>
          <section className="panel compact-panel"><Disclosure title="Privacy & protection" level={2}>
            <Disclosure title="Local analysis"><p>The frontend sends requests only to the native local bridge.</p><span className="badge positive">On-device</span></Disclosure>
            <Disclosure title="Cloud analysis"><p>No cloud provider or telemetry is configured in this prototype.</p><span className="badge">Disabled</span></Disclosure>
            <Disclosure title="Credentials"><p>HTTPS bearer credentials can use the operating system store or a named environment variable. Set them up in MCP connections.</p></Disclosure>
            <Disclosure title="Protection scope"><p>Only explicitly routed gateway clients are mediated. Importing or collecting definitions does not protect a client.</p></Disclosure>
          </Disclosure></section>
          <section className="panel compact-panel"><Disclosure title="Keyboard shortcuts" level={2}><div className="shortcut-grid">{navigation.map(item => <div key={item.page}><span>{item.label}</span><kbd>⌘ / Ctrl {item.shortcut}</kbd></div>)}<div><span>Search current list</span><kbd>⌘ / Ctrl K</kbd></div><div><span>Settings</span><kbd>⌘ / Ctrl ,</kbd></div></div></Disclosure></section>
        </div> : null}
        <footer className="page-footer"><span><Icon name="lock" size={12} />Local workspace · No telemetry</span><span>Definitions describe claims. Runtime behavior requires separate verification.</span></footer>
      </main>
    </div>
    {dialog === 'import' ? <ImportDialog native={native} onClose={() => setDialog(null)} onImport={async (server_id, identity, tools) => { await send({ action: 'import_definitions', server_id, identity, tools }); setDialog(null); setNotice(`${tools.length} definitions imported for review. No MCP connection was opened.`); await reload(); setPage('review'); }} /> : null}
    {dialog === 'approve' && review ? <Dialog title="Approve this exact version?" onClose={() => { if (!busy) setDialog(null); }}><div className="approval-context"><span className={`badge ${review.classification === 'C3' ? 'danger' : 'warning'}`}>{review.classification ? `${review.classification} · ${classLabels[review.classification]}` : 'First observation'}</span><h3>{review.tool_name}</h3><p>This trusts the observed definition for <strong>{review.server_id}</strong>. Future changes are evaluated against this approval.</p><p className="small muted">Approval is not a verification of server runtime behavior. Review the source and requested capabilities independently.</p><code>{review.sha256}</code></div><div className="dialog-actions"><button className="button subtle" disabled={busy} onClick={() => setDialog(null)}>Cancel</button><button className="button primary" disabled={busy} onClick={() => void decide('approve')}>{busy ? 'Saving…' : demo ? 'Approve fixture version' : 'Approve reviewed version'}</button></div></Dialog> : null}
    {dialog === 'export' ? <Dialog title="Export an audit summary" wide onClose={() => setDialog(null)}><p className="dialog-copy">This summary includes event types and timestamps. Definitions, arguments, reasons, identities, and event details are omitted. Inspect it before sharing.</p><textarea className="export-preview" readOnly value={safeAuditExport(events, !!demo)} aria-label="Audit summary preview" /><div className="dialog-actions"><button className="button subtle" onClick={() => setDialog(null)}>Close</button><button className="button primary" onClick={() => downloadText('driftguard-audit-summary.json', safeAuditExport(events, !!demo))}><Icon name="download" size={15} />Download JSON</button></div></Dialog> : null}
  </div>;
}

function ImportDialog({ native, onClose, onImport }: { native: boolean; onClose: () => void; onImport: (server: string, identity: string, tools: ReturnType<typeof parseDefinitions>) => Promise<void> }) {
  const [server, setServer] = useState('');
  const [identity, setIdentity] = useState('');
  const [text, setText] = useState('');
  const [filename, setFilename] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true);
    try { const tools = parseDefinitions(text); await onImport(server.trim(), identity.trim(), tools); }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'The definitions could not be imported.'); }
    finally { setBusy(false); }
  };
  return <Dialog title="Import tool definitions" onClose={() => { if (!busy) onClose(); }}><form onSubmit={event => void submit(event)}><p className="dialog-copy">Choose an exported MCP tools/list result. Importing records definitions for review and does not execute or connect to the server.</p>
    {!native ? <div className="scope-note small">The native desktop bridge is required to save definitions. This browser is a visual preview.</div> : null}
    <label className="form-label">Source name<input autoFocus required maxLength={200} placeholder="e.g. local-repository-server" value={server} onChange={event => setServer(event.target.value)} /></label>
    <label className="form-label">Server identity binding<input required maxLength={512} placeholder="Configuration fingerprint or verified identity" value={identity} onChange={event => setIdentity(event.target.value)} /><small>A visible identity label, never an API key or token.</small></label>
    <label className="file-drop"><Icon name="file" size={24} /><strong>{filename || 'Choose a tool-definition JSON file'}</strong><span>tools/list result or array · 1 MiB maximum</span><input type="file" accept=".json,application/json" aria-label="Choose tool definitions JSON" onChange={event => { const file = event.target.files?.[0]; if (!file) return; if (file.size > MAX_IMPORT_BYTES) { setError('Choose a JSON file smaller than 1 MiB.'); return; } void file.text().then(value => { try { parseDefinitions(value); setText(value); setFilename(file.name); setError(''); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Invalid JSON.'); } }); }} /></label>
    {error ? <p className="form-error" role="alert">{error}</p> : null}<div className="dialog-actions"><button className="button subtle" type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="button primary" type="submit" disabled={!native || !text || busy}>{busy ? 'Importing…' : 'Import for review'}</button></div></form></Dialog>;
}
