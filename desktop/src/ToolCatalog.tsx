import type { Ref } from 'react';
import { isPending, statusLabel, toolKey } from './bridge';
import { Icon } from './Icon';
import type { ToolRecord } from './types';
import { catalogLabel, catalogSource, groupCatalog } from './catalog-connections';

type Filters = { query: string; source: string; status: string; capability: string };
export const emptyCatalogFilters: Filters = { query: '', source: '', status: '', capability: '' };

const labels: Record<string, string> = {
  read: 'Read', write: 'Create or edit', delete: 'Delete', execute: 'Execute',
  transmit: 'Send or publish', fetch: 'Fetch', authenticate: 'Authenticate',
  filesystem: 'Filesystem', repository: 'Repository', database: 'Database',
  credentials: 'Credentials', network: 'Network', email: 'Email', payment: 'Payments',
  process: 'Process', design: 'Design', calendar: 'Calendar', messaging: 'Messaging',
};

export function filterCatalog(tools: ToolRecord[], sources: Map<string, string>, filters: Filters) {
  const terms = filters.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const [facet, value] = filters.capability.split(':');
  return tools.filter(tool => {
    if (filters.source && catalogSource(tool) !== filters.source) return false;
    if (filters.status === 'pending' ? !isPending(tool) : filters.status && (tool.blocked ? 'blocked' : tool.status) !== filters.status) return false;
    if (facet === 'operations' || facet === 'resources') {
      if (!tool.catalog?.[facet].includes(value)) return false;
    }
    if (!terms.length) return true;
    const tags = [...tool.catalog?.operations ?? [], ...tool.catalog?.resources ?? []];
    const searchable = [tool.tool_name, tool.server_id, catalogLabel(tool, sources), tool.description,
      ...tags.map(tag => labels[tag] ?? tag)].join(' ').toLowerCase();
    return terms.every(term => searchable.includes(term));
  });
}

export function ToolCatalog({ tools, matches, sources, selected, filters, onFilter, onSelect, searchRef }: {
  tools: ToolRecord[]; matches: ToolRecord[]; sources: Map<string, string>; selected?: ToolRecord;
  filters: Filters; onFilter: (next: Filters) => void; onSelect: (tool: ToolRecord) => void;
  searchRef: Ref<HTMLInputElement>;
}) {
  const groups = groupCatalog(matches, sources);
  const facets = (['operations', 'resources'] as const).map(facet => ({
    facet, values: [...new Set(tools.flatMap(tool => tool.catalog?.[facet] ?? []))].sort(),
  }));
  const availableSources = groupCatalog(tools, sources);
  const selectedKey = selected && toolKey(selected);
  return <aside className="review-sidebar" aria-label="MCP tool catalog">
    <div className="catalog-controls">
      <label className="search-field"><Icon name="search" size={16} />
        <input ref={searchRef} placeholder="Search tools or sources" aria-label="Search tools or sources"
          value={filters.query} onChange={event => onFilter({ ...filters, query: event.target.value })} />
      </label>
      <div className="catalog-filters">
        {availableSources.length > 1 ? <select className="catalog-source-filter" aria-label="MCP source"
          value={filters.source} onChange={event => onFilter({ ...filters, source: event.target.value })}>
          <option value="">All MCP sources</option>
          {availableSources.map(source => <option key={source.id} value={source.id}>{source.label}</option>)}
        </select> : null}
        <select aria-label="Review status" value={filters.status} onChange={event => onFilter({ ...filters, status: event.target.value })}>
          <option value="">All statuses</option>
          {['pending', 'approved', 'quarantined', 'denied', 'revoked'].map(status =>
            <option key={status} value={status}>{statusLabel(status)}</option>)}
          {tools.some(tool => tool.blocked) ? <option value="blocked">Blocked</option> : null}
        </select>
        <select aria-label="Inferred capability" value={filters.capability} onChange={event => onFilter({ ...filters, capability: event.target.value })}>
          <option value="">Capabilities</option>
          {facets.filter(({ values }) => values.length).map(({ facet, values }) =>
            <optgroup key={facet} label={facet === 'operations' ? 'Actions' : 'Resources'}>
              {values.map(value => <option key={value} value={`${facet}:${value}`}>{labels[value] ?? value}</option>)}
            </optgroup>)}
        </select>
      </div>
      <div className="catalog-count" role="status">
        {matches.length === tools.length ? tools.length : `${matches.length} of ${tools.length}`} tools
        {' · '}{groups.length} {groups.length === 1 ? 'source' : 'sources'}
      </div>
    </div>
    <div className="catalog-scroll">
      {groups.map(group => <section className="catalog-group" key={group.id} aria-label={group.label}>
        <h3 title={group.label}><span>{group.label}</span><span>{group.tools.length}</span></h3>
        {group.tools.map(tool => {
          const key = toolKey(tool);
          return <button key={key} className={`tool-row compact-tool catalog-tool ${key === selectedKey ? 'selected' : ''}`}
            aria-pressed={key === selectedKey} aria-label={`${tool.tool_name} · ${tool.server_id}`} onClick={() => onSelect(tool)}>
            <span className="tool-text"><strong title={tool.tool_name}>{tool.tool_name}</strong>
              <small>{statusLabel(tool.blocked ? 'blocked' : tool.status)}</small></span><Icon name="chevron" size={15} />
          </button>;
        })}
      </section>)}
      {!groups.length ? <div className="no-results"><p>No matching tools.</p>
        <button className="text-button" onClick={() => onFilter(emptyCatalogFilters)}>Clear filters</button></div> : null}
    </div>
  </aside>;
}

export function CatalogLabels({ tool }: { tool: ToolRecord }) {
  const tags = [...tool.catalog?.operations ?? [], ...tool.catalog?.resources ?? []];
  return tags.length ? <div className="catalog-labels" aria-label="Inferred capabilities">
    {tags.map(tag => <span key={tag}>{labels[tag] ?? tag}</span>)}
  </div> : null;
}
