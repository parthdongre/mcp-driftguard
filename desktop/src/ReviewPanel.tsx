import { useState } from 'react';
import type { Review, ToolDefinition } from './types';
import { Icon } from './Icon';
import { displayValue, formatTime } from './review-utils';
import { statusLabel } from './bridge';

export const classLabels: Record<string, string> = {
  C0: 'No meaningful change', C1: 'Benign maintenance', C2: 'Capability expansion', C3: 'Suspicious drift',
  unreviewed: 'First observation',
};

function DefinitionColumn({ tool, old, compare }: { tool: ToolDefinition | null; old?: boolean; compare: ToolDefinition | null }) {
  const fields = ['description', 'inputSchema', 'outputSchema', 'annotations'];
  return <section className="definition-column" aria-label={old ? 'Approved definition' : 'Observed definition'}>
    <div className="definition-heading"><span className={`dot ${old ? 'green' : 'amber'}`} />
      <strong>{old ? 'Approved baseline' : 'Observed version'}</strong><span>{old ? 'TRUSTED REFERENCE' : 'UNDER REVIEW'}</span>
    </div>
    {tool ? fields.map(field => {
      const changed = compare !== null && JSON.stringify(tool[field]) !== JSON.stringify(compare[field]);
      return <div className={`definition-field ${changed ? (old ? 'removed' : 'added') : ''}`} key={field}>
        <div className="field-label"><span>{({ description: 'Purpose', inputSchema: 'Input contract', outputSchema: 'Output contract', annotations: 'Safety annotations' })[field]}</span>
          {changed ? <span className="change-tag">{old ? 'Previous' : 'Changed'}</span> : null}</div>
        {field === 'description' ? <p>{displayValue(tool[field])}</p> : <pre>{displayValue(tool[field])}</pre>}
      </div>;
    }) : <div className="definition-empty"><Icon name="file" size={28} /><h3>No approved baseline</h3>
      <p>This is a first observation. Review the full definition before trusting this tool.</p></div>}
    {tool ? Object.keys(tool).filter(key => !['name', ...fields].includes(key)).map(key => <div className="definition-field" key={key}>
      <div className="field-label">{key}</div><pre>{displayValue(tool[key])}</pre>
    </div>) : null}
  </section>;
}

export function DefinitionDiff({ oldTool, newTool }: { oldTool: ToolDefinition | null; newTool: ToolDefinition }) {
  return <div className="definition-diff"><DefinitionColumn tool={oldTool} old compare={newTool} />
    <DefinitionColumn tool={newTool} compare={oldTool} /></div>;
}

export function ReviewPanel({ review, onDecision, busy, onTimeline }: {
  review: Review; onDecision: (action: 'approve' | 'deny' | 'quarantine') => void; busy: boolean; onTimeline: () => void;
}) {
  const [view, setView] = useState<'structured' | 'raw'>('structured');
  const capabilities = Object.entries(review.capability_delta ?? {}).filter(([, value]) => Array.isArray(value) && value.length > 0);
  return <div className="review-detail">
    <div className="detail-heading"><div><div className="eyebrow">{review.server_id}</div><h2>{review.tool_name}</h2></div>
      <span className={`badge ${review.classification === 'C3' ? 'danger' : review.classification === 'C2' ? 'warning' : ''}`}>{review.classification ?? 'NEW'} · {review.classification ? classLabels[review.classification] : 'First observation'}</span></div>
    <div className="review-meta"><span>Revision {review.revision ?? '—'}</span><span>{formatTime(review.observed_at)}</span>
      <span className="mono" title={review.sha256}>SHA-256 {review.sha256.slice(0, 12)}…</span><span>{statusLabel(review.status)}</span></div>
    <section className="evidence-summary"><div className="evidence-title"><Icon name="alert" /><strong>Review the change, then decide</strong></div>
      <ul>{(review.reasons?.length ? review.reasons : ['No automated evidence is available. A human decision is required before this definition is approved.']).map(reason => <li key={reason}>{reason}</li>)}</ul>
      {capabilities.length ? <div className="capability-chips">{capabilities.map(([key, values]) => <span key={key}>{key.replaceAll('_', ' ')}: {(values as string[]).join(', ')}</span>)}</div> : null}
      <p className="small muted">Capability signals are inferred from definitions. They do not verify what the server actually executes.</p>
    </section>
    <div className="section-toolbar"><div className="segmented" aria-label="Definition view"><button aria-pressed={view === 'structured'} onClick={() => setView('structured')}>Compare fields</button>
      <button aria-pressed={view === 'raw'} onClick={() => setView('raw')}>Full JSON</button></div>
      <button className="text-button" onClick={onTimeline}>View evolution <Icon name="arrow" size={15} /></button></div>
    {view === 'structured' ? <DefinitionDiff oldTool={review.old_tool} newTool={review.new_tool} /> : <div className="definition-diff raw"><pre aria-label="Approved JSON">{review.old_tool ? JSON.stringify(review.old_tool, null, 2) : 'No approved baseline'}</pre><pre aria-label="Observed JSON">{JSON.stringify(review.new_tool, null, 2)}</pre></div>}
    <div className="review-actions"><div><Icon name="lock" size={15} /><span>Decision binds to this exact definition.</span></div>
      <button className="button subtle" disabled={busy || review.status === 'denied'} onClick={() => onDecision('deny')}>Deny</button>
      <button className="button danger-outline" disabled={busy || review.status === 'quarantined'} onClick={() => onDecision('quarantine')}>Quarantine</button>
      <button className="button primary" title={review.classification === 'C3' || review.status === 'quarantined' ? 'Correct the source and observe a safe version before approval.' : undefined} disabled={busy || review.status === 'approved' || review.status === 'quarantined' || review.classification === 'C3'} onClick={() => onDecision('approve')}><Icon name="check" size={16} />Approve version</button></div>
  </div>;
}
