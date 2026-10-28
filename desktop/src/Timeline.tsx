import { useState } from 'react';
import type { HistoryVersion } from './types';
import { formatTime } from './review-utils';
import { statusLabel } from './bridge';
import { Icon } from './Icon';
import { Disclosure } from './Disclosure';

export function Timeline({ history, onReview }: { history: HistoryVersion[]; onReview: () => void }) {
  const [selected, setSelected] = useState<number | null>(null);
  const chronological = [...history].sort((a, b) => (a.revision ?? 0) - (b.revision ?? 0));
  const version = chronological.find(item => item.revision === selected) ?? chronological.at(-1);
  if (!version) return <div className="empty compact"><Icon name="timeline" size={34} /><h2>No tool history yet</h2><p>Import and review a tool, then observe a later version to inspect its evolution.</p></div>;
  const maxCusum = Math.max(0.5, ...chronological.map(v => v.cusum_score ?? 0));
  const points = chronological.flatMap((item, index) => typeof item.cusum_score === 'number' && Number.isFinite(item.cusum_score) ? [{
    x: 35 + index / Math.max(1, chronological.length - 1) * 650,
    y: 152 - item.cusum_score / maxCusum * 120,
    item, index,
  }] : []);
  const hasMetrics = points.length > 0;
  return <div className="timeline-content">
    <div className="section-heading"><div><h2>{version.tool_name}</h2><p>Approved references and observed changes, in order.</p></div><button className="button subtle" onClick={onReview}>Open current review <Icon name="arrow" size={15} /></button></div>
    <section className="chart-panel"><Disclosure title="Cumulative change signal">
      {hasMetrics ? <svg viewBox="0 0 720 190" role="img" aria-labelledby="chart-title"><title id="chart-title">CUSUM over {chronological.length} observations. Exact values are listed below.</title>
        {[32, 92, 152].map(y => <line key={y} x1="35" x2="685" y1={y} y2={y} className="chart-grid" />)}
        <text x="4" y="37" className="chart-label">{maxCusum.toFixed(2)}</text><text x="8" y="157" className="chart-label">0</text>
        <path d={points.map((point, index) => `${index > 0 && point.index === points[index - 1].index + 1 ? 'L' : 'M'}${point.x} ${point.y}`).join(' ')} className="chart-line" />
        {points.map(({ x, y, item }) => <g key={item.sha256}><circle cx={x} cy={y} r={item.sha256 === version.sha256 ? 6 : 4} className="chart-point" /><text x={x} y="180" textAnchor="middle" className="chart-label">v{item.revision}</text></g>)}
      </svg> : <p className="muted chart-empty">Sequential metrics have not been recorded for this lineage.</p>}
      <p className="small muted">A research signal, not a calibrated attack probability. Missing values are shown as unavailable in the version details.</p>
    </Disclosure></section>
    <div className="timeline-split"><div className="version-list" aria-label="Observed versions">{chronological.map(item => <button key={`${item.revision}-${item.sha256}`} className={item.sha256 === version.sha256 ? 'version selected' : 'version'} onClick={() => setSelected(item.revision ?? null)} aria-pressed={item.sha256 === version.sha256}>
      <span><strong>Version {item.revision ?? '—'}</strong></span><Icon name="chevron" size={14} />
    </button>)}</div>
      <section className="version-detail"><Disclosure title={`Version ${version.revision ?? '—'}`} defaultOpen><p>{version.description ?? 'No description declared.'}</p><p><span>{statusLabel(version.status)}</span> · {formatTime(version.observed_at)}</p>
        <div className="signal-grid">{[['Adjacent signal', version.step_risk], ['Approved-baseline signal', version.baseline_risk], ['CUSUM', version.cusum_score]].map(([name, value]) => <div key={name as string}><span>{name}</span><strong>{typeof value === 'number' ? value.toFixed(3) : 'Unavailable'}</strong></div>)}</div>
        <p className="small muted mono">SHA-256 {version.sha256}</p>
        {version.raw_tool ? <Disclosure title="Definition at this revision"><pre>{JSON.stringify(version.raw_tool, null, 2)}</pre></Disclosure> : null}
      </Disclosure></section></div>
  </div>;
}
