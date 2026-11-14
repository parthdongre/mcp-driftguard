import { useEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type { GraphRoute, GraphTool, MonitoringSettings, ToolRecord } from './types';
import type { SentinelCall } from './Sentinel';
import type { GraphPreferences } from './McpSettings';
import { gatewayState } from './GatewayServers';
import { formatTime } from './review-utils';
import { statusLabel } from './bridge';
import { Icon } from './Icon';
import './connection-graph.css';

interface Props {
  calls: SentinelCall[];
  preferences: GraphPreferences;
  monitoring: MonitoringSettings;
  routes: GraphRoute[] | null;
  tools: ToolRecord[];
  sources: Map<string, string>;
  loading: boolean;
  error: string;
  demo: boolean;
  native: boolean;
  onConnect: () => void;
  onDemo: () => void;
  searchRef: RefObject<HTMLInputElement | null>;
  onActivity: (source: string, tool: string) => void;
  onEvidence: (source: string, tool: string, view: 'definition' | 'history') => void;
}

interface Node {
  id: string;
  label: string;
  detail: string;
  tone?: 'live' | 'active' | 'completed' | 'attention';
  activity?: 'active' | 'completed' | 'attention';
  source?: string;
  select: () => void;
}

const PAGE_SIZE = 12;
const pending = new Set(['pending', 'unreviewed', 'review_required']);
const filters = [
  ['all', 'All statuses'], ['needs_review', 'Needs review'], ['approved', 'Approved'],
  ['blocked', 'Blocked'], ['quarantined', 'Quarantined'], ['denied', 'Denied'],
  ['revoked', 'Revoked'],
];
const matches = (tool: GraphTool, filter: string) =>
  filter === 'all' || (filter === 'needs_review' ? pending.has(tool.status) : tool.status === filter);
const routeLabel = (route: GraphRoute) =>
  route.client_label || route.client_id || (route.kind === 'review' ? 'Review only' : 'Gateway');
const toolId = (source: string, name: string) => JSON.stringify([source, name]);
const serverId = (route: GraphRoute) =>
  JSON.stringify([route.kind, route.kind === 'gateway' ? route.server_id : route.source_id, route.connection?.id]);

function connectorRoutes(route: GraphRoute): GraphRoute[] {
  if (!route.tools.some(tool => tool.connection)) return [route];
  const groups = new Map<string, GraphRoute>();
  for (const tool of route.tools) {
    const id = tool.connection?.id ?? '';
    let group = groups.get(id);
    if (!group) {
      group = { ...route, connection: tool.connection, server_id: tool.connection?.label ?? route.server_id, tools: [] };
      groups.set(id, group);
    }
    group.tools.push(tool);
  }
  return [...groups.values()].sort((a, b) => a.server_id.localeCompare(b.server_id));
}

function reviewRoutes(tools: ToolRecord[], sources: Map<string, string>): GraphRoute[] {
  const routes = new Map<string, GraphRoute>();
  for (const tool of tools) {
    let route = routes.get(tool.server_id);
    if (!route) {
      route = {
        source_id: tool.server_id, server_id: sources.get(tool.server_id) || tool.server_id,
        kind: 'review', client_id: null, client_label: null, active: false, tools: [],
      };
      routes.set(tool.server_id, route);
    }
    route.tools.push({ tool_name: tool.tool_name, status: tool.blocked ? 'blocked' : tool.status,
      version_count: null, connection: tool.connection });
  }
  return [...routes.values()];
}

function Edges({ columns, selected, height }: { columns: Node[][]; selected: string; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    let frame = 0;
    const animated = columns[2].some(node => node.activity === 'active') &&
      !matchMedia('(prefers-reduced-motion: reduce)').matches;
    const draw = (now = 0) => {
      const diagram = canvas.parentElement;
      if (!diagram) return;
      const bounds = [...diagram.querySelectorAll<HTMLElement>('.graph-column')];
      const ratio = window.devicePixelRatio || 1;
      const width = Math.round(canvas.clientWidth * ratio);
      const height = Math.round(canvas.clientHeight * ratio);
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;
      const context = canvas.getContext('2d');
      if (!context || bounds.length !== 3) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
      context.lineWidth = 1.5;
      const colors = getComputedStyle(canvas);
      const glow = { active: colors.getPropertyValue('--green').trim(),
        completed: colors.getPropertyValue('--green').trim(), attention: colors.getPropertyValue('--red').trim() };
      const index = columns[1].findIndex(node => node.id === selected);
      if (index === -1) return;
      const y = (row: number) => 74 + row * 57;
      const edge = (from: number, to: number, row: number, next: number, activity?: Node['activity']) => {
        const gap = (to - from) / 2;
        const active = activity === 'active';
        context.lineWidth = activity ? 2.5 : 1.5;
        context.strokeStyle = activity ? glow[activity] : colors.color;
        context.setLineDash(active ? [5, 6] : []);
        context.lineDashOffset = active ? -(now / 40) % 11 : 0;
        context.beginPath();
        context.moveTo(from, y(row));
        context.bezierCurveTo(from + gap, y(row), to - gap, y(next), to, y(next));
        context.stroke();
      };
      columns[0].forEach((node, row) => edge(
        bounds[0].offsetLeft + bounds[0].offsetWidth, bounds[1].offsetLeft, row, index, node.activity));
      columns[2].forEach((node, row) => edge(bounds[1].offsetLeft + bounds[1].offsetWidth, bounds[2].offsetLeft,
        index, row, node.activity));
    };
    draw();
    const tick = (now: number) => { draw(now); frame = requestAnimationFrame(tick); };
    if (animated) frame = requestAnimationFrame(tick);
    const resize = new ResizeObserver(() => draw());
    resize.observe(canvas);
    const theme = new MutationObserver(() => draw());
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => { cancelAnimationFrame(frame); resize.disconnect(); theme.disconnect(); };
  }, [columns, selected, height]);
  return <canvas className="graph-edges" ref={ref} aria-hidden="true" />;
}

export function ConnectionGraph({ calls, preferences, monitoring, routes, tools, sources, loading, error, demo, native, onConnect, onDemo, searchRef, onActivity, onEvidence }: Props) {
  const graph = useMemo(() => (routes ?? reviewRoutes(tools, sources)).flatMap(connectorRoutes), [routes, tools, sources]);
  const servers = useMemo(() => {
    const groups = new Map<string, GraphRoute[]>();
    for (const route of graph) {
      const id = serverId(route);
      const group = groups.get(id);
      if (group) group.push(route);
      else groups.set(id, [route]);
    }
    return groups;
  }, [graph]);
  const [server, setServer] = useState('');
  const [source, setSource] = useState('');
  const [selected, setSelected] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [followLive, setFollowLive] = useState(preferences.follow);
  const now = Date.now();
  const callsBySource = new Map<string, SentinelCall>();
  const callByTool = new Map<string, SentinelCall>();
  for (const call of calls) {
    const since = now - Date.parse(call.ended_at ?? call.started_at);
    if (call.state === 'unconfirmed' || (call.state !== 'active' && !(since < 8000))) continue;
    const key = toolId(call.source, call.tool);
    const previous = callByTool.get(key);
    if (!previous || (call.state === 'active' && previous.state !== 'active')) callByTool.set(key, call);
    const previousSource = callsBySource.get(call.source);
    if (!previousSource || (call.state === 'active' && previousSource.state !== 'active')) callsBySource.set(call.source, call);
  }
  const liveCalls = [...callsBySource.values()].sort((left, right) =>
    Number(right.state === 'active') - Number(left.state === 'active') || right.id - left.id);
  const routesBySource = new Map<string, GraphRoute[]>();
  for (const route of graph) {
    if (route.kind === 'gateway') {
      const group = routesBySource.get(route.source_id);
      if (group) group.push(route);
      else routesBySource.set(route.source_id, [route]);
    }
  }
  const activeBranch = (call: SentinelCall) => routesBySource.get(call.source)?.find(route =>
    route.tools.some(tool => tool.tool_name === call.tool));
  const followedCall = followLive ? liveCalls.find(call => activeBranch(call)) : undefined;
  const followedRoute = followedCall && activeBranch(followedCall);
  const serverKey = followedRoute ? serverId(followedRoute) : servers.has(server) ? server : servers.keys().next().value;
  const branch = (serverKey && servers.get(serverKey)) || [];
  const activeRoute = followedRoute ?? branch.find(route => route.source_id === source);
  const term = query.trim().toLocaleLowerCase();
  const matched = (activeRoute ? [activeRoute] : branch).flatMap(route =>
    route.tools.filter(tool => matches(tool, filter) && tool.tool_name.toLocaleLowerCase().includes(term))
      .map(tool => ({ route, tool, id: toolId(route.source_id, tool.tool_name) })));
  if (followedCall) {
    const focusedTool = toolId(followedCall.source, followedCall.tool);
    matched.sort((left, right) => Number(right.id === focusedTool) - Number(left.id === focusedTool));
  }
  const pageCount = Math.max(1, Math.ceil(matched.length / PAGE_SIZE));
  const currentPage = followedCall ? 0 : Math.min(page, pageCount - 1);
  const visible = matched.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const evidence = visible.find(item => item.id === selected);
  const lastCheck = branch.map(route => route.last_checked ?? '').sort().at(-1);
  const monitoredRoute = activeRoute ?? branch.find(route => route.active);
  const lastUse = monitoredRoute && calls.find(call => call.source === monitoredRoute.source_id);
  const activeChecks = lastUse && now - Date.parse(lastUse.started_at) < monitoring.active_window_seconds * 1000;
  const activityTone = (call?: SentinelCall): Node['activity'] => {
    if (!preferences.highlight || !call) return undefined;
    if (call.state === 'completed' || call.state === 'active') return call.state;
    return 'attention';
  };
  const pickServer = (id: string) => {
    setFollowLive(false); setServer(id); setSource(''); setSelected(''); setPage(0);
  };
  const serverEntries = [...servers];
  const serverIndex = serverEntries.findIndex(([id]) => id === serverKey);
  const serverPage = Math.max(0, Math.floor(serverIndex / PAGE_SIZE));
  const visibleServers = serverEntries.slice(serverPage * PAGE_SIZE, (serverPage + 1) * PAGE_SIZE);
  const columns: Node[][] = [
    branch.map(route => ({
      id: route.source_id, label: routeLabel(route),
      detail: route.kind === 'review' ? route.client_id ? 'Review only' : 'Recorded definitions' : route.active ? 'Active' : route.connection_state ? gatewayState(route.connection_state) : 'Offline',
      tone: activityTone(callsBySource.get(route.source_id)) ?? (route.stopped ? 'attention' : route.active ? 'live' : undefined),
      activity: activityTone(callsBySource.get(route.source_id)),
      select: () => {
        setFollowLive(false); setServer(serverId(route));
        setSource(current => current === route.source_id ? '' : route.source_id); setPage(0);
      },
    })),
    visibleServers.map(([id, group]) => ({
      id, label: group[0].server_id,
      detail: group[0].kind === 'review' ? 'Review source' : group[0].connection_state && !group.some(route => route.active) ? gatewayState(group[0].connection_state) : `${group.length} ${group.length === 1 ? 'route' : 'routes'}`,
      tone: activityTone(liveCalls.find(call => group.some(route => route.source_id === call.source))),
      select: () => pickServer(id),
    })),
    visible.map(({ route, tool, id }) => {
      const activity = activityTone(callByTool.get(id));
      return {
        id, label: tool.tool_name,
        detail: `${statusLabel(tool.status)} · ${routeLabel(route)}`,
        tone: activity ?? (route.stopped || ['blocked', 'quarantined', 'denied'].includes(tool.status) ? 'attention' : undefined),
        activity,
        select: () => {
          setFollowLive(false); setServer(serverId(route)); setSource(activeRoute?.source_id ?? ''); setSelected(id);
        },
      };
    }),
  ];
  const height = Math.max(310, 110 + 57 * (Math.max(...columns.map(column => column.length)) - 1));
  if (!graph.length) return <section className="panel graph-empty">
    <Icon name="graph" size={32} />
    <h2>{loading ? 'Reading the MCP graph…' : error ? 'The MCP graph is unavailable' : 'No MCP connections to map yet'}</h2>
    <p>{error || (native ? 'Connect a coding harness and open a session to see its server and tools.' : 'Explore the guided demo to see how tool definitions and review evidence are linked.')}</p>
    {!loading && !error ? <button className="button primary" onClick={native ? onConnect : onDemo}>
      {native ? 'Open MCP connections' : 'Explore guided demo'}
    </button> : null}
  </section>;
  return <section className="panel graph-panel" aria-label="Connection graph">
    <div className="graph-toolbar">
      {servers.size > 1 ? <label className="graph-filter">Server
        <select value={serverKey} onChange={event => pickServer(event.target.value)}>
          {serverEntries.map(([id, group]) => <option key={id} value={id}>
            {group[0].server_id}{group[0].kind === 'review' ? ' (review source)' : ''}
          </option>)}
        </select>
      </label> : null}
      <label className="search-field"><Icon name="search" size={16} />
        <input ref={searchRef} type="search" aria-label="Find a tool in this server" placeholder="Find a tool…"
          value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} />
      </label>
      <label className="graph-filter">Tool status
        <select value={filter} onChange={event => { setFilter(event.target.value); setPage(0); }}>
          {filters.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      {native && !demo && routes ? <label className="mcp-setting-toggle"><input type="checkbox" checked={followLive}
        onChange={event => {
          if (!event.target.checked && serverKey) pickServer(serverKey);
          else setFollowLive(event.target.checked);
        }} />Follow live activity</label> : null}
      <div className="graph-zoom" role="group" aria-label="Graph zoom">
        <button className="icon-button" aria-label="Zoom out" disabled={zoom <= 1}
          onClick={() => setZoom(value => Math.max(1, value - .2))}>−</button>
        <button className="button subtle" aria-label="Reset zoom" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button>
        <button className="icon-button" aria-label="Zoom in" disabled={zoom >= 1.59}
          onClick={() => setZoom(value => Math.min(1.6, value + .2))}>+</button>
      </div>
    </div>
    {error ? <p className="graph-note" role="status">Showing the last available evidence. {error}</p> : null}
    {demo ? <p className="graph-note">Guided demo · recorded definitions</p> : null}
    {branch.some(route => route.connection_state === 'sign_in_required') ? <p className="graph-note">
      Authentication required. <button type="button" className="text-button" onClick={onConnect}>Open MCP connections</button>
    </p> : null}
    <div className="graph-viewport" tabIndex={0} role="region" aria-label="Scrollable MCP topology">
      <div style={{ minWidth: 660 * zoom, width: `${100 * zoom}%` }}>
      <div className="graph-diagram" style={{ height, zoom }}>
        <Edges columns={columns} selected={serverKey ?? ''} height={height} />
        {columns.map((nodes, index) => <div className="graph-column" key={index}>
          <h2>{['Coding harnesses', 'MCP servers', 'Tools'][index]}</h2>
          {nodes.map(node => <button type="button" className="graph-node" key={node.id}
            title={node.label} aria-pressed={node.id === [activeRoute?.source_id, serverKey, selected][index]}
            aria-label={`${node.label} · ${node.detail}`} data-tone={node.tone} onClick={node.select}>
            <span className="graph-node-icon"><Icon name={(['connections', 'graph', 'file'] as const)[index]} size={17} /></span>
            <span className="graph-node-text"><strong>{node.label}</strong><small>{node.detail}</small></span>
          </button>)}
          {index === 2 && !nodes.length ? <p className="graph-no-tools">{branch.every(route => route.tools.length === 0) ? 'No tool catalog loaded yet.' : 'No tools match these filters.'}</p> : null}
        </div>)}
      </div>
      </div>
    </div>
    <div className="graph-pagination">
      <span aria-live="polite">{matched.length} {matched.length === 1 ? 'tool' : 'tools'}{activeRoute ? ` · ${routeLabel(activeRoute)}` : ''}</span>
      {lastCheck ? <span>Last catalog check {formatTime(lastCheck)}
        {monitoredRoute?.active ? ` · ${activeChecks ? monitoring.active_seconds : monitoring.idle_seconds} s checks` : ''}</span> : null}
      {pageCount > 1 && !followedCall ? <div>
        <button className="button subtle" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button>
        <span>Page {currentPage + 1} of {pageCount}</span>
        <button className="button subtle" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>Next</button>
      </div> : null}
    </div>
    {evidence ? <section className="graph-evidence" aria-label="Selected tool evidence">
      <div><h2>{evidence.tool.tool_name}</h2>
        <p>{routeLabel(evidence.route)} · {evidence.route.server_id} · {statusLabel(evidence.tool.status)}
          {evidence.tool.version_count !== null ? ` · ${evidence.tool.version_count} ${evidence.tool.version_count === 1 ? 'version' : 'versions'}` : ''}</p></div>
      <div>
        <button className="button subtle" onClick={() => onActivity(evidence.route.source_id, evidence.tool.tool_name)}>View tool activity</button>
        <button className="button subtle" onClick={() => onEvidence(evidence.route.source_id, evidence.tool.tool_name, 'history')}>View version history</button>
        <button className="button primary" onClick={() => onEvidence(evidence.route.source_id, evidence.tool.tool_name, 'definition')}>Open security review</button>
      </div>
    </section> : null}
  </section>;
}
