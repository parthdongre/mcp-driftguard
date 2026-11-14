import { useState } from 'react';
import type { Review, ReviewAction, ToolDefinition, ToolRecord } from './types';
import { Icon } from './Icon';
import { displayValue, formatTime } from './review-utils';
import { statusLabel } from './bridge';
import { Disclosure } from './Disclosure';
import { CatalogLabels } from './ToolCatalog';

export const classLabels: Record<string, string> = {
  C0: 'No meaningful change', C1: 'Benign maintenance', C2: 'Capability expansion', C3: 'Suspicious drift',
  unreviewed: 'First observation',
};

function DefinitionColumn({ tool, old, compare, observed }: { tool: ToolDefinition | null; old?: boolean; compare: ToolDefinition | null; observed?: boolean }) {
  const fields = ['description', 'inputSchema', 'outputSchema', 'annotations'];
  return <section className="definition-column" aria-label={old ? observed ? 'Initial definition' : 'Approved definition' : 'Observed definition'}>
    <div className="definition-heading"><span className={`dot ${old ? 'green' : 'amber'}`} />
      <strong>{old ? observed ? 'Initial baseline' : 'Approved baseline' : 'Observed version'}</strong><span>{old ? observed ? 'FIRST OBSERVATION' : 'TRUSTED REFERENCE' : 'UNDER REVIEW'}</span>
    </div>
    {tool ? fields.map(field => {
      const changed = compare !== null && JSON.stringify(tool[field]) !== JSON.stringify(compare[field]);
      return <Disclosure title={({ description: 'Purpose', inputSchema: 'Input contract', outputSchema: 'Output contract', annotations: 'Safety annotations' })[field] ?? field} className={`definition-field ${changed ? (old ? 'removed' : 'added') : ''}`} key={field} level={4}>
        {changed ? <span className="change-tag">{old ? 'Previous' : 'Changed'}</span> : null}
        {field === 'inputSchema' && tool['x-driftguard-input-schema'] === 'not-exported' ? <p>The host exported names and descriptions only. A complete input schema was not provided; this import cannot authorize live calls.</p> : field === 'description' ? <p>{displayValue(tool[field])}</p> : <pre>{displayValue(tool[field])}</pre>}
      </Disclosure>;
    }) : <div className="definition-empty"><Icon name="file" size={28} /><h3>No approved baseline</h3>
      <p>This is a first observation. Review the full definition before trusting this tool.</p></div>}
    {tool ? Object.keys(tool).filter(key => !['name', ...fields].includes(key)).map(key => <Disclosure title={key} className="definition-field" key={key} level={4}>
      <pre>{displayValue(tool[key])}</pre>
    </Disclosure>) : null}
  </section>;
}

export function DefinitionDiff({ oldTool, newTool, observed }: { oldTool: ToolDefinition | null; newTool: ToolDefinition; observed?: boolean }) {
  return <div className="definition-diff"><DefinitionColumn tool={oldTool} old compare={newTool} observed={observed} />
    <DefinitionColumn tool={newTool} compare={oldTool} /></div>;
}

export function ReviewPanel({ review, catalogTool, sourceLabel, onDecision, busy }: {
  review: Review; catalogTool?: ToolRecord; sourceLabel?: string;
  onDecision: (action: ReviewAction) => void; busy: boolean;
}) {
  const [view, setView] = useState<'structured' | 'raw'>('structured');
  const capabilities = Object.entries(review.capability_delta ?? {}).filter(([, value]) => Array.isArray(value) && value.length > 0);
  const quarantined = review.quarantine_active ?? review.status === 'quarantined';
  const catalogOnly = review.server_id.startsWith('harness:');
  const hosted = review.server_id === 'harness:codex:codex_apps';
  return <div className="review-detail">
    <div className="detail-heading"><div><h2>{review.tool_name}</h2>
      <p className="review-source">{sourceLabel || review.server_id}</p>
      {catalogTool ? <CatalogLabels tool={catalogTool} /> : null}
    </div>
      {catalogOnly ? <span className="badge" title="This source is outside the DriftGuard gateway">Catalog only</span> : null}
      <span className={`badge ${review.blocked || review.classification === 'C3' ? 'danger' : review.classification === 'C2' ? 'warning' : ''}`}>{review.blocked ? 'Blocked' : review.classification ? `${review.classification} · ${classLabels[review.classification]}` : review.old_tool ? statusLabel(review.status) : 'First observation'}</span></div>
    <Disclosure title="Version details" className="review-disclosure"><p>{review.server_id}</p><div className="review-meta"><span>Revision {review.revision ?? '—'}</span><span>{formatTime(review.observed_at)}</span>
      <span className="mono" title={review.sha256}>SHA-256 {review.sha256.slice(0, 12)}…</span><span>{statusLabel(review.status)}</span></div></Disclosure>
    <Disclosure title="Review evidence" className="review-disclosure">
      {review.model_decision ? <p>Model {review.model_decision.id} recommended {statusLabel(review.model_decision.action).toLowerCase()}.
        {' '}Risk score {review.model_decision.score.toFixed(3)}.</p> : null}
      {review.reasons?.length || !review.model_decision ? <ul>{(review.reasons?.length ? review.reasons : ['No automated evidence is available.']).map(reason => <li key={reason}>{reason}</li>)}</ul> : null}
      {capabilities.length ? <div className="capability-chips">{capabilities.map(([key, values]) => <span key={key}>{key.replaceAll('_', ' ')}: {(values as string[]).join(', ')}</span>)}</div> : null}
      <p className="small muted">Capability signals are inferred from definitions. They do not verify what the server actually executes.</p>
    </Disclosure>
    <div className="section-toolbar"><div className="segmented" role="group" aria-label="Definition view">
      <button aria-pressed={view === 'structured'} onClick={() => setView('structured')}>Compare fields</button>
      <button aria-pressed={view === 'raw'} onClick={() => setView('raw')}>Full JSON</button></div></div>
    {view === 'structured' ? <DefinitionDiff oldTool={review.old_tool} newTool={review.new_tool} observed={review.baseline_kind === 'observed'} /> : <div className="definition-diff raw"><pre aria-label="Baseline JSON">{review.old_tool ? JSON.stringify(review.old_tool, null, 2) : 'No baseline'}</pre><pre aria-label="Observed JSON">{JSON.stringify(review.new_tool, null, 2)}</pre></div>}
    <div className="review-actions"><div><Icon name="lock" size={15} /><span>{review.shared_blocked ? 'Blocked across all gateway routes.' : review.blocked ? 'Blocked on this gateway route.' : hosted ? 'Codex controls access to this hosted tool. Disconnect or disable the app in Codex to stop its calls.' : catalogOnly ? 'Review only · Route the server through DriftGuard to enforce decisions.' : review.server_id.startsWith('gateway:') ? 'Decisions apply to this version across sessions.' : 'Decision binds to this exact definition.'}</span></div>
      {review.blocked !== undefined && !catalogOnly ? <button className="button danger-outline" disabled={busy}
        onClick={() => onDecision(review.shared_blocked ? 'unblock_tool_all' : 'block_tool_all')}>
        {review.shared_blocked ? 'Unblock all harnesses' : 'Block across harnesses'}
      </button> : null}
      {review.route_blocked ? <button className="button subtle" disabled={busy}
        onClick={() => onDecision('unblock_tool')}>Clear route block</button> : null}
      <button className="button subtle" disabled={busy || review.status === 'denied'} onClick={() => onDecision('deny')}>{catalogOnly ? 'Record denial' : 'Deny'}</button>
      <button className="button danger-outline" disabled={busy}
        onClick={() => onDecision(quarantined ? 'release_quarantine' : 'quarantine')}>
        {quarantined ? 'Release to review' : catalogOnly ? 'Record quarantine' : 'Quarantine'}
      </button>
      <button className="button primary" title={quarantined ? 'Release this version to review before approving.' : undefined}
        disabled={busy || review.status === 'approved' || quarantined || review.blocked}
        onClick={() => onDecision('approve')}><Icon name="check" size={16} />{catalogOnly ? 'Record approval' : 'Approve version'}</button></div>
  </div>;
}
