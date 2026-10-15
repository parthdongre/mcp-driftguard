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
import { downloadText, formatTime, matchesActivityFilter, MAX_IMPORT_BYTES, parseDefinitions, safeAuditExport } from './review-utils';

const navigation: { page: Page; label: string; icon: IconName; shortcut?: string }[] = [
  { page: 'overview', label: 'Overview', icon: 'overview', shortcut: '1' },
  { page: 'connections', label: 'MCP connections', icon: 'connections', shortcut: '2' },
  { page: 'review', label: 'Security review', icon: 'review', shortcut: '3' },
  { page: 'timeline', label: 'Tool evolution', icon: 'timeline', shortcut: '4' },
  { page: 'activity', label: 'Security activity', icon: 'activity', shortcut: '5' },
  { page: 'research', label: 'Research laboratory', icon: 'research', shortcut: '6' },
];
const descriptions: Record<Page, string> = {
  overview: 'A clear view of what has changed and what needs your attention.',
  connections: 'Review tool definitions from explicitly configured MCP sources.',
  review: 'Understand the change. Decide what this exact version can be trusted to do.',
  timeline: 'Follow changes across time, relative to the approved baseline.',
  activity: 'An inspectable record of local security decisions.',
  research: 'Independent annotation and reproducible research, separate from protection.',
  settings: 'Your workspace, your device, your preferences.',
};
const initialWorkspace: Workspace = { overview: emptyOverview, tools: [], activity: [] };
type Theme = 'system' | 'dark' | 'light';

function Empty({ icon, title, children, action, onAction }: { icon: IconName; title: string; children: string; action?: string; onAction?: () => void }) {
  return <div className="empty"><span className="empty-icon"><Icon name={icon} size={32} /></span><h2>{title}</h2><p>{children}</p>
    {action ? <button className="button primary" onClick={onAction}>{action}<Icon name="arrow" size={16} /></button> : null}</div>;
}

function ToolRow({ tool, selected, onClick }: { tool: ToolRecord; selected?: boolean; onClick: () => void }) {
  const warning = tool.classification === 'C3' || tool.status === 'quarantined';
  return <button className={`tool-row ${selected ? 'selected' : ''}`} onClick={onClick} aria-pressed={selected} title={`${tool.tool_name} · ${tool.server_id}`}>
    <span className={`tool-symbol ${warning ? 'danger' : isPending(tool) ? 'warning' : ''}`}><Icon name={warning ? 'alert' : 'file'} /></span>
    <span className="tool-text"><strong>{tool.tool_name}</strong><small>{tool.server_id}</small></span>
    <span className={`badge ${warning ? 'danger' : isPending(tool) ? 'warning' : ''}`}>{statusLabel(tool.status)}</span><Icon name="chevron" size={14} />
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
      <nav aria-label="Main navigation">{navigation.map(item => <button key={item.page} aria-current={page === item.page ? 'page' : undefined} className={`nav-item ${page === item.page ? 'active' : ''}`} onClick={() => { setPage(item.page); setQuery(''); }}>
        <Icon name={item.icon} /><span>{item.label}</span>{item.page === 'review' && workspace.overview.pending > 0 ? <span className="nav-count">{workspace.overview.pending}</span> : null}
      </button>)}</nav>
      <div className="sidebar-bottom"><div className="local-note"><Icon name="lock" size={15} /><span>Private by default<small>Analysis stays on this device</small></span></div>
        <button className={`nav-item ${page === 'settings' ? 'active' : ''}`} onClick={() => setPage('settings')} aria-current={page === 'settings' ? 'page' : undefined}><Icon name="settings" /><span>Settings</span><kbd>⌘ ,</kbd></button>
        <div className="sidebar-version"><span>RESEARCH PREVIEW</span><span>0.1</span></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb">Workspace <Icon name="chevron" size={12} /><strong>{heading}</strong></div>
      <div className="topbar-actions"><span className={`connection-state ${demo ? 'fixture' : ''}`}><span className="dot" />{demo ? 'Guided demo' : native ? 'Local desktop' : 'Browser preview'}</span>
        <button className="icon-button" aria-label="Refresh local workspace" title="Refresh local workspace" disabled={loading} onClick={() => void reload()}><Icon name="refresh" size={17} /></button></div></header>
      <div className={`mode-banner ${demo ? 'demo' : ''}`}><Icon name={demo ? 'research' : 'lock'} size={15} /><span>{demo ? 'Isolated research fixture · No connected clients · Decisions are discarded when you exit' : native ? 'Protection covers only MCP calls explicitly routed through the configured gateway.' : 'Browser preview · Native gateway unavailable · No MCP connections are protected'}</span>
        {demo ? <button onClick={exitDemo}>Exit demo</button> : <button onClick={startDemo}>Explore guided demo <Icon name="arrow" size={13} /></button>}</div>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading"><div><div className="eyebrow">{page === 'research' ? 'EVIDENCE BEFORE CLAIMS' : 'YOUR LOCAL WORKSPACE'}</div><h1>{heading}</h1><p>{descriptions[page]}</p></div>
          {page === 'overview' || page === 'connections' ? <button className="button primary" onClick={() => setDialog('import')} disabled={!!demo}><Icon name="plus" size={16} />Import definitions</button> : null}
          {page === 'activity' ? <button className="button subtle" disabled={!events.length} onClick={() => setDialog('export')}><Icon name="download" size={16} />Export summary</button> : null}
        </div>
        {error ? <div className="error-banner" role="alert"><Icon name="alert" size={18} /><span>{error}</span><button className="icon-button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div> : null}
        {notice ? <div className="notice" role="status"><Icon name="check" size={15} /><span>{notice}</span><button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss notification"><Icon name="close" size={15} /></button></div> : null}
        {loading ? <div className="loading-line" role="status">Reading local workspace…</div> : null}

        {page === 'overview' ? <>
          <section className="protection-summary"><div className="protection-symbol"><Icon name="shield" size={38} /></div><div><span className="eyebrow">{demo ? 'DEMONSTRATION WORKSPACE' : 'PROTECTION SCOPE'}</span><h2>{demo ? 'See how trust changes over time.' : workspace.overview.tools > 0 ? 'Local review state is available.' : 'Ready for your first security review.'}</h2><p>{demo ? 'A real deterministic detector trace, presented as an isolated learning scenario.' : workspace.overview.scope}</p></div><span className="status-pill"><span className="dot amber" />{demo ? 'Fixture mode' : 'Review workspace'}</span></section>
          <div className="stats-grid">{[['Definition sources', workspace.overview.servers, 'Imported or gateway observed'], ['Observed tools', workspace.overview.tools, 'Definitions in this workspace'], ['Needs review', workspace.overview.pending, 'Awaiting an explicit decision'], ['Quarantined', workspace.overview.quarantined, 'Versions held from approval']].map(([label, value, hint]) => <div className="stat" key={label}><span>{label}</span><strong>{value}</strong><small>{hint}</small></div>)}</div>
          <div className="overview-split"><section className="panel"><div className="section-heading"><div><h2>Review queue <span className="number-label">{pending.length}</span></h2><p>New definitions and changes that need a decision.</p></div><button className="text-button" onClick={() => setPage('review')}>View all <Icon name="arrow" size={15} /></button></div>
            {pending.length ? <div className="tool-list">{pending.slice(0, 5).map(tool => <ToolRow key={toolKey(tool)} tool={tool} onClick={() => openReview(tool)} />)}</div> : <div className="inline-empty"><Icon name="review" size={25} /><h3>{workspace.tools.length ? 'Your review queue is clear' : 'Trust starts with a review'}</h3><p>{workspace.tools.length ? 'No recorded definitions are awaiting a decision.' : 'Import a tools/list JSON response to inspect a server’s declared capabilities.'}</p><button className="text-button" disabled={!!demo} onClick={() => setDialog('import')}>Import definitions <Icon name="arrow" size={14} /></button></div>}
          </section><section className="panel activity-panel"><div className="section-heading"><div><h2>Recent activity</h2><p>A record you can inspect.</p></div></div>{workspace.activity.length ? <div className="event-list">{workspace.activity.slice(0, 4).map((event, index) => <div className="event-item" key={String(event.id ?? index)}><span className="event-node" /><div><strong>{event.event.replaceAll('_', ' ')}</strong><small>{event.tool_name ?? 'Workspace'} · {formatTime(event.timestamp)}</small></div></div>)}</div> : <div className="inline-empty"><Icon name="activity" size={25} /><h3>No recorded events</h3><p>Your first observation and every review decision will appear here.</p></div>}
            <div className="panel-footer"><Icon name="lock" size={14} /><span>{workspace.overview.last_verification ? `Last catalog observation ${formatTime(workspace.overview.last_verification)}` : 'No gateway catalog observation recorded'}</span></div></section></div>
          <div className="principles-strip"><div><Icon name="file" /><strong>Definitions are evidence</strong><span>They describe claims, not verified behavior.</span></div><div><Icon name="lock" /><strong>Trust is version bound</strong><span>Approvals apply to an exact definition.</span></div><div><Icon name="timeline" /><strong>History matters</strong><span>Small changes can accumulate over time.</span></div></div>
        </> : null}

        {page === 'connections' ? <>
          <div className="scope-note"><Icon name="connections" size={22} /><div><h3>Connect through the gateway to enforce decisions</h3><p>Definition imports support inspection. They do not establish a live connection or intercept client calls. Configure your MCP client to use the DriftGuard gateway for enforcement.</p></div></div>
          <section className="panel"><div className="section-heading"><div><h2>Definition sources</h2><p>{sources.length} recorded sources · live health is not measured here</p></div></div>
            {sources.length ? sources.map(source => <div className="source-row" key={source}><span className="source-icon"><Icon name="connections" size={23} /></span><div><h3>{source}</h3><p>{workspace.tools.filter(tool => tool.server_id === source).length} observed tools</p></div><span className="badge">{demo ? 'Fixture source' : 'Recorded definitions'}</span><button className="button subtle" disabled={!workspace.tools.some(item => item.server_id === source)} onClick={() => { const tool = workspace.tools.find(item => item.server_id === source); if (tool) openReview(tool); }}>Review tools <Icon name="arrow" size={15} /></button></div>) : <Empty icon="connections" title="Add your first definition source" action="Import tool definitions" onAction={() => setDialog('import')}>Choose an exported MCP tools/list result. The import is local and does not execute server code.</Empty>}
          </section><section className="setup-guide"><div className="section-heading"><h2>From observation to protection</h2><span className="badge">Explicit configuration</span></div><ol><li><strong>Inspect the server</strong><p>Review its executable, origin, permissions, and declared tools before running it.</p></li><li><strong>Route your MCP client</strong><p>Use the gateway CLI and bind the server identity to the same local database.</p></li><li><strong>Review exact versions</strong><p>New or changed definitions require a decision. Calls outside the gateway bypass this protection.</p></li></ol></section>
        </> : null}

        {page === 'review' || page === 'timeline' ? workspace.tools.length ? <div className="review-layout"><aside className="review-sidebar"><label className="search-field"><Icon name="search" size={16} /><input ref={searchRef} placeholder="Find a tool…" aria-label="Search tools" value={query} onChange={event => setQuery(event.target.value)} /><kbd>⌘ K</kbd></label><div className="list-label">OBSERVED TOOLS <span>{filteredTools.length}</span></div>{filteredTools.map(tool => <ToolRow key={toolKey(tool)} tool={tool} selected={toolKey(tool) === toolKey(selectedTool)} onClick={() => setSelectedKey(toolKey(tool))} />)}{!filteredTools.length ? <p className="no-results">No matching tools.</p> : null}</aside><section className="review-workspace">{page === 'timeline' ? <Timeline key={selectedKey || selectedTool?.tool_name} history={history} onReview={() => setPage('review')} /> : review ? <ReviewPanel review={review} busy={busy} onDecision={action => void decide(action)} onTimeline={() => setPage('timeline')} /> : <div className="loading-evidence" role="status">Reading review evidence…</div>}</section></div> : <section className="panel"><Empty icon={page === 'review' ? 'review' : 'timeline'} title={page === 'review' ? 'No definitions to review yet' : 'Every tool has a history'} action="Explore guided demo" onAction={startDemo}>Import tool definitions in MCP connections, or explore an isolated detector trace to see the workflow.</Empty></section> : null}

        {page === 'activity' ? <section className="panel"><div className="activity-toolbar"><label className="search-field"><Icon name="search" size={16} /><input ref={searchRef} aria-label="Search security activity" placeholder="Search activity…" value={query} onChange={event => setQuery(event.target.value)} /></label><label className="filter-label">Event <select value={activityFilter} onChange={event => setActivityFilter(event.target.value)}><option value="all">All events</option><option value="approve">Approvals</option><option value="quarantine">Quarantines</option><option value="deny">Denials</option><option value="observ">Observations</option></select></label><span className="small muted">{events.length} events</span></div>{events.length ? <div className="table-scroll"><table><thead><tr><th>Event</th><th>Tool / source</th><th>Recorded at</th><th>Evidence</th></tr></thead><tbody>{events.map((event, index) => <tr key={String(event.id ?? index)}><td><span className="audit-event"><Icon name={event.event.includes('quarantine') ? 'alert' : 'activity'} size={15} />{event.event.replaceAll('_', ' ')}</span></td><td><strong>{event.tool_name ?? 'Workspace'}</strong><small>{event.server_id ?? 'Local'}</small></td><td className="mono small">{formatTime(event.timestamp)}</td><td>{event.detail ? <details><summary>Inspect</summary><pre>{typeof event.detail === 'string' ? event.detail : JSON.stringify(event.detail, null, 2)}</pre></details> : <span className="muted">—</span>}</td></tr>)}</tbody></table></div> : <Empty icon="activity" title={query || activityFilter !== 'all' ? 'No matching events' : 'No security events recorded'}>Observations and decisions will appear here as you use the local workspace.</Empty>}</section> : null}

        <div hidden={page !== 'research'}><AnnotationLab /></div>

        {page === 'settings' ? <div className="settings-layout"><section className="panel"><div className="section-heading"><div><h2>Appearance</h2><p>Use system typography and accessible native controls.</p></div></div><div className="setting-row"><div><strong>Color theme</strong><p>Follows your device when System is selected.</p></div><div className="segmented">{(['system', 'light', 'dark'] as Theme[]).map(value => <button key={value} aria-pressed={theme === value} onClick={() => setTheme(value)}>{value === 'system' ? 'System' : value === 'light' ? <><Icon name="sun" size={14} />Light</> : <><Icon name="moon" size={14} />Dark</>}</button>)}</div></div><div className="setting-row"><div><strong>Reduced motion</strong><p>Respects your operating system’s accessibility preference.</p></div><span className="badge">System controlled</span></div></section>
          <section className="panel"><div className="section-heading"><div><h2>Privacy & protection</h2><p>Clear boundaries for this application.</p></div></div><div className="setting-row"><div><strong>Local analysis</strong><p>The frontend sends requests only to the native local bridge.</p></div><span className="badge positive"><Icon name="lock" size={13} />On-device</span></div><div className="setting-row"><div><strong>Cloud analysis</strong><p>No cloud provider or telemetry is configured in this prototype.</p></div><span className="badge">Disabled</span></div><div className="setting-row"><div><strong>Credentials</strong><p>Credential storage and authenticated remote setup are not implemented. Do not import secrets.</p></div><span className="badge">Unavailable</span></div><div className="setting-row"><div><strong>Protection scope</strong><p>Only explicitly routed gateway clients. Importing a definition does not protect a client.</p></div><span className="badge">Opt-in gateway</span></div></section>
          <section className="panel"><div className="section-heading"><h2>Keyboard shortcuts</h2></div><div className="shortcut-grid">{navigation.map(item => <div key={item.page}><span>{item.label}</span><kbd>⌘ / Ctrl {item.shortcut}</kbd></div>)}<div><span>Search current list</span><kbd>⌘ / Ctrl K</kbd></div><div><span>Settings</span><kbd>⌘ / Ctrl ,</kbd></div></div></section></div> : null}
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
