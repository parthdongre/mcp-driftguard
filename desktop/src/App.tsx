import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AuditEvent, BridgeRequest, CatalogSync, DefinitionAlerts, GraphRoute, HistoryVersion, MonitoringSettings, Page, Review, ReviewAction, ToolRecord, Workspace } from './types';
import { DemoWorkspace, emptyOverview, hasNativeBridge, isPending, request, statusLabel, toolKey } from './bridge';
import { Icon } from './Icon';
import type { IconName } from './Icon';
import { Dialog } from './Dialog';
import { ReviewPanel, classLabels } from './ReviewPanel';
import { Timeline } from './Timeline';
import { emptyCatalogFilters, filterCatalog, ToolCatalog } from './ToolCatalog';
import { AnnotationLab } from './AnnotationLab';
import { LiveConnection } from './LiveConnection';
import { HarnessHelpers } from './HarnessHelpers';
import type { HelpersReport } from './HarnessHelpers';
import { catalogLabel } from './catalog-connections';
import { ConnectionGraph } from './ConnectionGraph';
import { McpActivity } from './McpActivity';
import { ApprovalSettings, defaultMonitoring, McpSettings, readGraphPreferences } from './McpSettings';
import { Sentinel } from './Sentinel';
import type { SentinelCall } from './Sentinel';
import { Disclosure } from './Disclosure';
import { downloadText, formatTime, matchesActivityFilter, safeAuditExport } from './review-utils';

const navigation: { page: Page; label: string; icon: IconName; shortcut?: string }[] = [
  { page: 'overview', label: 'Overview', icon: 'overview', shortcut: '1' },
  { page: 'connections', label: 'MCP connections', icon: 'connections', shortcut: '2' },
  { page: 'graph', label: 'MCP graph', icon: 'graph', shortcut: '7' },
  { page: 'review', label: 'Security review', icon: 'review', shortcut: '3' },
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
  const [reviewView, setReviewView] = useState<'definition' | 'history'>('definition');
  const [catalogFilters, setCatalogFilters] = useState(emptyCatalogFilters);
  const [review, setReview] = useState<Review | null>(null);
  const [history, setHistory] = useState<HistoryVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [definitionAlerts, setDefinitionAlerts] = useState<DefinitionAlerts>({ unread: 0, latest: null });
  const [alertBusy, setAlertBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [activityFilter, setActivityFilter] = useState('all');
  const [activityTool, setActivityTool] = useState<Pick<ToolRecord, 'server_id' | 'tool_name'> | null>(null);
  const [toolEvents, setToolEvents] = useState<AuditEvent[] | null>(null);
  const [refreshCount, setRefreshCount] = useState(0);
  const [graphRoutes, setGraphRoutes] = useState<GraphRoute[] | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState('');
  const [sentinelCalls, setSentinelCalls] = useState<SentinelCall[]>([]);
  const [sentinelRefresh, setSentinelRefresh] = useState(0);
  const [catalogSync, setCatalogSync] = useState<CatalogSync | null>(null);
  const [catalogSyncing, setCatalogSyncing] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const [helpers, setHelpers] = useState<HelpersReport | null>(null);
  const [helpersLoading, setHelpersLoading] = useState(false);
  const [helpersError, setHelpersError] = useState('');
  const [rustEngine, setRustEngine] = useState(false);
  const [monitoring, setMonitoring] = useState<MonitoringSettings | null>(null);
  const [monitoringError, setMonitoringError] = useState('');
  const [graphPreferences, setGraphPreferences] = useState(readGraphPreferences);
  const [showCatalogChecks, setShowCatalogChecks] = useState<boolean | null>(null);
  const startupView = useRef(graphPreferences.startup);
  const openedStartupView = useRef(false);
  const [helperNotice, setHelperNotice] = useState('');
  const [approval, setApproval] = useState<Review | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => {
    try { const stored = localStorage.getItem('driftguard.theme.v1'); return stored === 'light' || stored === 'dark' ? stored : 'system'; } catch { return 'system'; }
  });
  const requestSequence = useRef(0);
  const alertSequence = useRef(0);
  const latestAlertId = useRef(0);
  const catalogRequest = useRef<Promise<void> | null>(null);
  const helperRequest = useRef<Promise<void> | null>(null);
  const lastHelperChange = useRef<number | null>(null);
  const demoActive = useRef(false);
  demoActive.current = !!demo;
  const searchRef = useRef<HTMLInputElement>(null);
  const native = hasNativeBridge();
  const sources = useMemo(() => new Map(workspace.overview.server_list?.map(source =>
    [source.server_id, source.display_name || source.server_id])), [workspace.overview.server_list]);
  const filteredTools = useMemo(() => filterCatalog(workspace.tools, sources, catalogFilters),
    [workspace.tools, sources, catalogFilters]);
  const selectedTool = filteredTools.find(tool => toolKey(tool) === selectedKey) ?? filteredTools[0];
  const currentReview = review && selectedTool && toolKey(review) === toolKey(selectedTool) ? review : null;
  const send = useCallback(<T,>(payload: BridgeRequest): Promise<T> => demo ? demo.request<T>(payload) : request<T>(payload), [demo]);

  const reload = useCallback(async (quiet = false) => {
    const sequence = ++requestSequence.current;
    if (!quiet) { setLoading(true); setError(''); }
    if (!demo && !native) { setWorkspace(initialWorkspace); setLoading(false); return initialWorkspace; }
    try {
      const [overview, tools, activity] = await Promise.all([
        send<Workspace['overview']>({ action: 'overview' }), send<ToolRecord[]>({ action: 'list_tools', summary: true }), send<AuditEvent[]>({ action: 'activity' }),
      ]);
      if (sequence === requestSequence.current) {
        const next = { overview, tools, activity };
        setWorkspace(next); setRefreshCount(count => count + 1);
        return next;
      }
    } catch (failure) { if (!quiet && sequence === requestSequence.current) setError(failure instanceof Error ? failure.message : 'Unable to read the local workspace.'); }
    finally { if (sequence === requestSequence.current) setLoading(false); }
    return null;
  }, [demo, native, send]);

  useEffect(() => { void reload(); return () => { requestSequence.current += 1; }; }, [reload]);
  const scanHelpers = useCallback((manual = false) => {
    if (helperRequest.current) return helperRequest.current;
    if (manual) setHelpersLoading(true);
    const task = request<HelpersReport>({ action: 'harness_helpers' }).then(report => {
      const newest = report.changes[0]?.id ?? 0;
      const previous = lastHelperChange.current;
      const count = Math.max(report.new_changes, previous === null ? 0 :
        report.changes.filter(change => change.id > previous).length);
      if (count) {
        setHelperNotice(count === 1 ? '1 harness helper changed' : `${count} harness helpers changed`);
      }
      lastHelperChange.current = newest;
      setHelpers(report);
      setHelpersError('');
    }).catch(failure => {
      setHelpersError(failure instanceof Error ? failure.message : 'Unable to scan harness helpers.');
    }).finally(() => { helperRequest.current = null; setHelpersLoading(false); });
    helperRequest.current = task;
    return task;
  }, []);
  useEffect(() => {
    if (!native || demo) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await scanHelpers();
      if (active) timer = setTimeout(() => { void poll(); }, 30000);
    };
    void request<{ engine?: string }>({ action: 'runtime_info' }).then(info => {
      if (active && info.engine === 'rust') {
        setRustEngine(true);
        if (!openedStartupView.current) {
          openedStartupView.current = true;
          setPage(current => current === 'overview' ? startupView.current : current);
          void request<MonitoringSettings>({ action: 'monitoring_settings' })
            .then(settings => setMonitoring(settings))
            .catch(failure => setMonitoringError(failure instanceof Error
              ? failure.message : 'Could not load monitoring settings.'));
        }
        void poll();
      }
    }).catch(() => {});
    return () => { active = false; clearTimeout(timer); };
  }, [demo, native, scanHelpers]);
  const syncCatalogs = useCallback(() => {
    if (catalogRequest.current) return catalogRequest.current;
    setCatalogSyncing(true); setCatalogError('');
    const task = request<CatalogSync>({ action: 'sync_harness_catalogs' })
      .then(async result => { setCatalogSync(result); if (!demoActive.current) await reload(true); })
      .catch(failure => { setCatalogError(failure instanceof Error ? failure.message : 'Could not discover MCP tools.'); })
      .finally(() => { catalogRequest.current = null; setCatalogSyncing(false); });
    catalogRequest.current = task;
    return task;
  }, [reload]);
  useEffect(() => {
    if (!native || demo || !monitoring?.discovery_enabled) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await request<{ harnesses?: { installed: boolean }[]; codex_routes?: string[] }>({ action: 'live_status' });
        if (active && (status.codex_routes?.length || status.harnesses?.some(client => client.installed))) await syncCatalogs();
      } catch {
        // Discovery retries on the next interval.
      }
      if (active) timer = setTimeout(() => { void poll(); }, monitoring.discovery_seconds * 1000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [demo, native, monitoring?.discovery_enabled, monitoring?.discovery_seconds, syncCatalogs]);
  useEffect(() => {
    if (!native || demo || page !== 'graph') return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setGraphLoading(true);
    setGraphError('');
    const poll = async () => {
      try {
        const [routes, calls] = await Promise.all([
          request<GraphRoute[]>({ action: 'connection_graph' }),
          request<SentinelCall[]>({ action: 'sentinel_calls' }).catch(() => null),
        ]);
        if (!active) return;
        setGraphRoutes(routes);
        if (calls) setSentinelCalls(calls);
        setGraphError('');
      } catch (failure) {
        if (active) setGraphError(failure instanceof Error ? failure.message : 'Unable to read the connection graph.');
      } finally {
        if (active) {
          setGraphLoading(false);
          timer = setTimeout(() => { void poll(); }, 1000);
        }
      }
    };
    void request<{ engine?: string }>({ action: 'runtime_info' }).then(info => {
      if (!active) return;
      if (info.engine === 'rust') void poll();
      else { setGraphRoutes(null); setGraphLoading(false); }
    }).catch(() => { if (active) setGraphLoading(false); });
    return () => { active = false; clearTimeout(timer); };
  }, [demo, native, page, refreshCount, sentinelRefresh]);
  useEffect(() => {
    if (!native || demo) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const sequence = ++alertSequence.current;
      try {
        const next = await request<DefinitionAlerts>({ action: 'definition_alerts' });
        if (active && sequence === alertSequence.current) {
          setDefinitionAlerts(next);
          const nextId = Math.max(next.latest?.id ?? 0, next.catalog_revision ?? 0);
          if (nextId > latestAlertId.current && await reload(true)) {
            latestAlertId.current = nextId;
          }
        }
      } catch {
        // Keep the last alert while the local engine is busy.
      }
      if (active) timer = setTimeout(() => { void poll(); }, 2500);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [demo, native, reload]);
  useEffect(() => {
    if (!native || demo || page !== 'activity') return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const scoped = activityTool && graphRoutes !== null;
    const poll = async () => {
      try {
        const activity = await request<AuditEvent[]>(scoped
          ? { action: 'tool_activity', ...activityTool } : { action: 'activity' });
        if (active && scoped) setToolEvents(activity);
        else if (active) setWorkspace(current => ({ ...current, activity }));
      } catch {
        // Keep the last recorded events while the local engine is busy.
      }
      if (active) timer = setTimeout(() => { void poll(); }, 2500);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [activityTool, demo, native, page, graphRoutes]);
  useEffect(() => {
    window.scrollTo({ top: 0 });
    document.getElementById('main-content')?.focus({ preventScroll: true });
  }, [page]);
  useEffect(() => {
    let active = true;
    setReview(null); setHistory([]);
    if (page !== 'review' || !selectedTool || (!native && !demo)) return;
    const payload = { server_id: selectedTool.server_id, tool_name: selectedTool.tool_name };
    void Promise.all([send<Review>({ action: 'review', ...payload }), send<HistoryVersion[]>({ action: 'history', ...payload })])
      .then(([nextReview, versions]) => { if (active) { setReview(nextReview); setHistory(versions); } })
      .catch(failure => { if (active) setError(failure instanceof Error ? failure.message : 'Unable to load review evidence.'); });
    return () => { active = false; };
  }, [page, selectedTool?.server_id, selectedTool?.tool_name, refreshCount, native, demo, send]);
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
        if (destination) {
          event.preventDefault(); setPage(destination.page);
          if (destination.page === 'review') setReviewView('definition');
        }
        else if (event.key === '4') { event.preventDefault(); setPage('review'); setReviewView('history'); }
        else if (event.key === 'k') { event.preventDefault(); searchRef.current?.focus(); }
        else if (event.key === ',') { event.preventDefault(); setPage('settings'); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const openReview = (tool: Pick<ToolRecord, 'server_id' | 'tool_name'>, view: 'definition' | 'history' = 'definition') => {
    setSelectedKey(toolKey(tool)); setCatalogFilters(emptyCatalogFilters);
    setReviewView(view); setPage('review');
  };
  const openGraphEvidence = async (source: string, name: string, view: 'definition' | 'history') => {
    const tool = { server_id: source, tool_name: name };
    const contains = (data: Workspace) => data.tools.some(item => item.server_id === source && item.tool_name === name);
    if (!contains(workspace)) {
      const next = await reload();
      if (!next) return;
      if (!contains(next)) {
        setError('This tool is no longer in the current catalog.');
        return;
      }
    }
    openReview(tool, view);
  };
  const openToolActivity = (server_id: string, tool_name: string) => {
    setActivityTool({ server_id, tool_name });
    setToolEvents(null);
    setActivityFilter('all');
    setQuery('');
    setPage('activity');
  };
  const dismissChanges = async () => {
    if (!definitionAlerts.new_mcp || alertBusy) return;
    const through_id = definitionAlerts.new_mcp.id;
    setAlertBusy(true);
    try {
      ++alertSequence.current;
      const next = await request<DefinitionAlerts>({ action: 'dismiss_definition_alerts', through_id });
      ++alertSequence.current;
      setDefinitionAlerts(next);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not dismiss change alerts.'); }
    finally { setAlertBusy(false); }
  };
  const decide = async (action: ReviewAction) => {
    if (busy) return;
    const decision = approval ?? currentReview;
    if (!decision) return;
    if (action === 'approve' && !approval) { setApproval(decision); return; }
    setBusy(true); setError('');
    try {
      const tool = { server_id: decision.server_id, tool_name: decision.tool_name };
      if (action === 'block_tool' || action === 'unblock_tool' || action === 'block_tool_all' || action === 'unblock_tool_all') {
        const result = await send<Review>({ action, ...tool });
        setNotice(action === 'block_tool_all' ? 'Tool blocked across harnesses.'
          : action === 'block_tool' ? 'Tool blocked on this route.'
          : result.blocked ? 'Another block still applies to this tool.' : 'Tool unblocked. Review its current version.');
        await reload();
        return;
      }
      await send({ action, ...tool, expected_sha256: decision.sha256, expected_revision: decision.revision });
      setApproval(null);
      const catalogOnly = !demo && decision.server_id.startsWith('harness:');
      const status = statusLabel(action === 'approve' ? 'approved' : action === 'deny' ? 'denied' : 'quarantined');
      setNotice(catalogOnly
        ? action === 'release_quarantine'
          ? 'Catalog quarantine released. Runtime access is controlled by the host.'
          : `Catalog decision recorded: ${status}. Runtime access is controlled by the host.`
        : action === 'release_quarantine' ? 'Quarantine released. This version needs review.'
          : `${demo ? 'Demo decision' : 'Decision'} saved: ${status}.`);
      await reload();
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'The decision could not be saved.'); }
    finally { setBusy(false); }
  };
  const startDemo = (destination: Page = 'overview') => { setDemo(new DemoWorkspace()); setSelectedKey(''); setActivityTool(null); setCatalogFilters(emptyCatalogFilters); setReviewView('definition'); setPage(destination); setNotice('Guided demo opened. All observations and decisions are isolated fixtures.'); };
  const exitDemo = () => { setDemo(null); setSelectedKey(''); setActivityTool(null); setCatalogFilters(emptyCatalogFilters); setReviewView('definition'); setWorkspace(initialWorkspace); setPage('overview'); setNotice('Guided demo closed. Fixture decisions were discarded.'); };
  const pending = workspace.tools.filter(isPending);
  const events = (activityTool ? toolEvents ?? workspace.activity : workspace.activity).filter(event =>
    (!activityTool || (event.server_id === activityTool.server_id && event.tool_name === activityTool.tool_name)) &&
    matchesActivityFilter(event.event, activityFilter) &&
    `${event.event} ${event.server_id ?? ''} ${event.tool_name ?? ''}`.toLowerCase().includes(query.toLowerCase()));
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
        {demo ? <button onClick={exitDemo}>Exit demo</button> : <button onClick={() => startDemo()}>Explore guided demo <Icon name="arrow" size={13} /></button>}</div>
      <main id="main-content" tabIndex={-1}>
        <div className="page-heading"><div><h1>{heading}</h1></div>
          {page === 'overview' && !demo ? <button className="button primary" onClick={() => setPage('connections')}><Icon name="connections" size={16} />Set up MCP</button> : null}
          {page === 'overview' && workspace.tools.length > 0 ? <button className="button subtle" onClick={() => setPage('graph')}><Icon name="graph" size={16} />Open MCP graph</button> : null}
          {page === 'activity' ? <button className="button subtle" disabled={!events.length} onClick={() => setExportOpen(true)}><Icon name="download" size={16} />Export summary</button> : null}
        </div>
        {error ? <div className="error-banner" role="alert"><Icon name="alert" size={18} /><span>{error}</span><button className="icon-button" onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" size={15} /></button></div> : null}
        {notice ? <div className="notice" role="status"><Icon name="check" size={15} /><span>{notice}</span><button className="icon-button" onClick={() => setNotice('')} aria-label="Dismiss notification"><Icon name="close" size={15} /></button></div> : null}
        {!demo && definitionAlerts.new_mcp ? <div className="notice definition-alert">
          <Icon name="connections" size={16} />
          <span role="status">{definitionAlerts.new_mcp_count === 1 ? 'New MCP added' : `${definitionAlerts.new_mcp_count ?? 1} new MCPs added`}
            {' · '}{definitionAlerts.new_mcp.detail.name || sources.get(definitionAlerts.new_mcp.server_id) || definitionAlerts.new_mcp.server_id}</span>
          <button className="button subtle" onClick={() => setPage('connections')}>View MCP connections</button>
          <button className="icon-button" disabled={alertBusy} onClick={() => void dismissChanges()}
            aria-label="Dismiss new MCP notices"><Icon name="close" size={15} /></button>
        </div> : null}
        {!demo && catalogSyncing && !workspace.tools.length && page !== 'connections' ? <div className="loading-line" role="status">Discovering configured MCP servers…</div> : null}
        {!demo && helperNotice ? <div className="notice definition-alert">
          <Icon name="alert" size={16} /><span role="status">{helperNotice}</span>
          <button className="text-button" onClick={() => {
            setPage('connections');
            requestAnimationFrame(() => document.getElementById('harness-helpers-heading')?.scrollIntoView());
          }}>View harness helpers</button>
          <button className="icon-button" aria-label="Dismiss harness helper notice" onClick={() => setHelperNotice('')}><Icon name="close" size={15} /></button>
        </div> : null}
        {loading ? <div className="loading-line" role="status">Reading local workspace…</div> : null}

        {page === 'overview' ? <>
          <section className="panel compact-panel"><Disclosure title={demo ? 'Demonstration workspace' : 'Protection scope'} level={2}><p>{demo ? 'A real deterministic detector trace, presented as an isolated learning scenario.' : workspace.overview.scope}</p><p>{demo ? 'Fixture mode' : 'Review workspace'}</p></Disclosure></section>
          <div className="stats-grid">{[['Definition sources', workspace.overview.servers], ['Observed tools', workspace.overview.tools], ['Needs review', workspace.overview.pending], ['Quarantined', workspace.overview.quarantined]].map(([label, value]) => <div className="stat" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
          <div className="overview-split">
            <section className="panel"><div className="section-heading"><h2>Review queue <span className="number-label">{pending.length}</span></h2><button className="text-button" onClick={() => setPage('review')}>View all <Icon name="arrow" size={15} /></button></div>
              {pending.length ? <div className="tool-list">{pending.slice(0, 5).map(tool => <ToolRow key={toolKey(tool)} tool={tool} onClick={() => openReview(tool)} />)}</div> : <div className="inline-empty"><h3>{workspace.tools.length ? 'Your review queue is clear' : 'Trust starts with a review'}</h3>{!demo && !workspace.tools.length ? <button className="text-button" onClick={() => setPage('connections')}>Connect a coding harness <Icon name="arrow" size={14} /></button> : null}</div>}
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

        {page === 'connections' ? demo
          ? <section className="panel"><Empty icon="connections" title="Connect a coding harness" action="Exit demo" onAction={exitDemo}>The guided demo uses an isolated workspace.</Empty></section>
          : <><LiveConnection native={native} catalogSync={catalogSync} catalogSyncing={catalogSyncing}
            tools={workspace.tools} sources={sources} onReviewConnection={source => {
              setSelectedKey(''); setCatalogFilters({ ...emptyCatalogFilters, source });
              setReviewView('definition'); setPage('review');
            }}
            catalogError={catalogError} onSync={syncCatalogs} onChanged={() => { void reload(); }} onReview={() => {
            const tool = workspace.tools.find(item => item.server_id === 'driftguard-filesystem' && item.tool_name === 'read_text_file');
            if (tool) openReview(tool);
            else { void reload(); setPage('review'); }
          }} />
          {rustEngine ? <HarnessHelpers report={helpers} error={helpersError}
            loading={helpersLoading || (!helpers && !helpersError)} onScan={() => void scanHelpers(true)} /> : null}</>
          : null}

        {page === 'graph' ? <><ConnectionGraph routes={demo ? null : graphRoutes}
          calls={demo ? [] : sentinelCalls}
          preferences={graphPreferences} monitoring={monitoring ?? defaultMonitoring}
          tools={workspace.tools} sources={sources} loading={graphLoading || loading}
          error={demo ? '' : graphError} demo={!!demo}
          onConnect={() => setPage('connections')} onDemo={() => startDemo('graph')} native={native}
          searchRef={searchRef} onActivity={openToolActivity}
          onEvidence={(source, name, view) => void openGraphEvidence(source, name, view)} />
          {!demo && rustEngine ? <><McpActivity sources={sources}
            showChecks={showCatalogChecks ?? graphPreferences.showChecks} onShowChecks={setShowCatalogChecks} />
            <Sentinel calls={sentinelCalls} routes={graphRoutes ?? []}
              onRefresh={() => setSentinelRefresh(value => value + 1)} /></> : null}</> : null}

        {page === 'review' ? workspace.tools.length ? <div className="review-layout">
          <ToolCatalog tools={workspace.tools} matches={filteredTools} sources={sources}
            selected={selectedTool} filters={catalogFilters} onFilter={setCatalogFilters}
            onSelect={tool => setSelectedKey(toolKey(tool))} searchRef={searchRef} />
          <section className="review-workspace" aria-label="Selected tool">
            {selectedTool ? <>
              <div className="review-view-switch">
                <div className="segmented" role="group" aria-label="Selected tool view">
                  <button aria-pressed={reviewView === 'definition'} onClick={() => setReviewView('definition')}>Current review</button>
                  <button aria-pressed={reviewView === 'history'} onClick={() => setReviewView('history')}>Version history</button>
                </div>
              </div>
              <div className="review-pane" key={toolKey(selectedTool) + reviewView}>
                {currentReview ? reviewView === 'history'
                  ? <Timeline history={history} />
                  : <ReviewPanel review={currentReview} catalogTool={selectedTool}
                    sourceLabel={catalogLabel(selectedTool, sources)} busy={busy}
                    onDecision={action => void decide(action)} />
                  : <div className="loading-evidence" role="status">Reading review evidence…</div>}
              </div>
            </> : <Empty icon="search" title="No matching tools">Change your search or filters to see more tools.</Empty>}
          </section>
        </div> : <section className="panel"><Empty icon="review" title="No definitions to review yet"
          action={native ? 'Connect a coding harness' : 'Explore guided demo'}
          onAction={native ? () => setPage('connections') : startDemo}>
          Connect a coding harness to collect tools, or explore the guided demo.
        </Empty></section> : null}

        {page === 'activity' ? <section className="panel compact-panel">
          {activityTool ? <div className="activity-toolbar">
            <strong>{activityTool.tool_name} · {activityTool.server_id}</strong>
            <button className="button subtle" onClick={() => setActivityTool(null)}>Clear tool filter</button>
          </div> : null}
          <div className="activity-toolbar"><label className="search-field"><Icon name="search" size={16} /><input ref={searchRef} aria-label="Search security activity" placeholder="Search activity…" value={query} onChange={event => setQuery(event.target.value)} /></label><label className="filter-label">Event <select value={activityFilter} onChange={event => setActivityFilter(event.target.value)}><option value="all">All events</option><option value="definition_changed">Definition changes</option><option value="approve">Approvals</option><option value="quarantine">Quarantines</option><option value="deny">Denials</option><option value="observ">Observations</option></select></label><span className="small muted">{events.length} events</span></div>
          {events.length ? events.map((event, index) => <Disclosure title={event.event.replaceAll('_', ' ')} key={String(event.id ?? index)} level={2}>
            <p>{event.tool_name ?? 'Workspace'} · {event.server_id ?? 'Local'}</p><p>{formatTime(event.timestamp)}</p>
            {event.detail ? <pre>{typeof event.detail === 'string' ? event.detail : JSON.stringify(event.detail, null, 2)}</pre> : null}
          </Disclosure>) : <Empty icon="activity" title={query || activityTool || activityFilter !== 'all' ? 'No matching events' : 'No security events recorded'}>Observations and decisions will appear here as you use the local workspace.</Empty>}
        </section> : null}

        <div hidden={page !== 'research'}><AnnotationLab /></div>

        {page === 'settings' ? <div className="settings-layout">
          {rustEngine && !demo ? <><ApprovalSettings /><McpSettings monitoring={monitoring} error={monitoringError}
            preferences={graphPreferences} onPreferences={next => {
              setGraphPreferences(next); setShowCatalogChecks(null);
            }}
            onSave={async settings => {
              const saved = await request<MonitoringSettings>({ action: 'set_monitoring_settings', settings });
              setMonitoring(saved);
              setMonitoringError('');
            }} /></> : null}
          <section className="panel compact-panel"><Disclosure title="Appearance" level={2}>
            <Disclosure title="Color theme"><p>Follows your device when System is selected.</p><div className="segmented">{(['system', 'light', 'dark'] as Theme[]).map(value => <button key={value} aria-pressed={theme === value} onClick={() => setTheme(value)}>{value === 'system' ? 'System' : value === 'light' ? <><Icon name="sun" size={14} />Light</> : <><Icon name="moon" size={14} />Dark</>}</button>)}</div></Disclosure>
            <Disclosure title="Typography"><p>Uses your device’s native interface font, including San Francisco on macOS. Text scales with your browser or system zoom.</p></Disclosure>
            <Disclosure title="Reduced motion"><p>Respects your operating system’s accessibility preference.</p><span className="badge">System controlled</span></Disclosure>
          </Disclosure></section>
          <section className="panel compact-panel"><Disclosure title="Privacy & protection" level={2}>
            <Disclosure title="Local analysis"><p>The frontend sends requests only to the native local bridge.</p><span className="badge positive">On-device</span></Disclosure>
            <Disclosure title="Cloud analysis"><p>No cloud provider or telemetry is configured in this prototype.</p><span className="badge">Disabled</span></Disclosure>
            <Disclosure title="Credentials"><p>Coding clients handle their own model-provider accounts and credentials.</p></Disclosure>
            <Disclosure title="Protection scope"><p>Only explicitly routed gateway clients are mediated. Importing or collecting definitions does not protect a client.</p></Disclosure>
          </Disclosure></section>
          <section className="panel compact-panel"><Disclosure title="Keyboard shortcuts" level={2}><div className="shortcut-grid">{navigation.map(item => <div key={item.page}><span>{item.label}</span><kbd>⌘ / Ctrl {item.shortcut}</kbd></div>)}<div><span>Version history</span><kbd>⌘ / Ctrl 4</kbd></div><div><span>Search current list</span><kbd>⌘ / Ctrl K</kbd></div><div><span>Settings</span><kbd>⌘ / Ctrl ,</kbd></div></div></Disclosure></section>
        </div> : null}
        <footer className="page-footer"><span><Icon name="lock" size={12} />Local workspace · No telemetry</span><span>Definitions describe claims. Runtime behavior requires separate verification.</span></footer>
      </main>
    </div>
    {approval ? <Dialog title="Approve this exact version?" onClose={() => { if (!busy) setApproval(null); }}><div className="approval-context"><span className={`badge ${approval.classification === 'C3' ? 'danger' : 'warning'}`}>{approval.classification ? `${approval.classification} · ${classLabels[approval.classification]}` : 'First observation'}</span><h3>{approval.tool_name}</h3><p>This trusts the observed definition for <strong>{approval.server_id}</strong>. Future changes are evaluated against this approval.</p><p className="small muted">Approval is not a verification of server runtime behavior. Review the source and requested capabilities independently.</p><code>{approval.sha256}</code></div><div className="dialog-actions"><button className="button subtle" disabled={busy} onClick={() => setApproval(null)}>Cancel</button><button className="button primary" disabled={busy} onClick={() => void decide('approve')}>{busy ? 'Saving…' : demo ? 'Approve fixture version' : 'Approve reviewed version'}</button></div></Dialog> : null}
    {exportOpen ? <Dialog title="Export an audit summary" wide onClose={() => setExportOpen(false)}><p className="dialog-copy">This summary includes event types and timestamps. Definitions, arguments, reasons, identities, and event details are omitted. Inspect it before sharing.</p><textarea className="export-preview" readOnly value={safeAuditExport(events, !!demo)} aria-label="Audit summary preview" /><div className="dialog-actions"><button className="button subtle" onClick={() => setExportOpen(false)}>Close</button><button className="button primary" onClick={() => downloadText('driftguard-audit-summary.json', safeAuditExport(events, !!demo))}><Icon name="download" size={15} />Download JSON</button></div></Dialog> : null}
  </div>;
}
