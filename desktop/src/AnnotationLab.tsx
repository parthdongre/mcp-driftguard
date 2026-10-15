import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { DefinitionDiff, classLabels } from './ReviewPanel';
import { annotationsJsonl, makeAnnotation, parseCandidates } from './annotation-utils';
import type { Candidate, HumanAnnotation } from './annotation-utils';
import type { ChangeClass } from './types';
import { downloadText, MAX_IMPORT_BYTES } from './review-utils';
import { Dialog } from './Dialog';

export function AnnotationLab() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [annotations, setAnnotations] = useState<HumanAnnotation[]>([]);
  const [annotator, setAnnotator] = useState('');
  const [label, setLabel] = useState<ChangeClass | ''>('');
  const [rationale, setRationale] = useState('');
  const [secondReview, setSecondReview] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [exportOpen, setExportOpen] = useState(false);
  const [exportedCount, setExportedCount] = useState(0);
  useEffect(() => {
    if (annotations.length <= exportedCount) return;
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener('beforeunload', protect);
    return () => window.removeEventListener('beforeunload', protect);
  }, [annotations.length, exportedCount]);
  const candidate = candidates.find(item => !annotations.some(annotation => annotation.candidate_id === item.candidate_id));
  const finish = () => {
    if (!candidate) return;
    try {
      const annotation = makeAnnotation(candidate, annotator, label, rationale, secondReview);
      setAnnotations(previous => [...previous, annotation]); setLabel(''); setRationale(''); setSecondReview(false); setError('');
      setMessage('Your independent annotation was recorded in this session. Export before closing.');
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Annotation could not be recorded.'); }
  };
  return <>
    <div className="research-status"><span className="research-mark"><Icon name="research" size={30} /></span><div><span className="eyebrow">PUBLICATION READINESS</span><h2>Build the evidence, then measure.</h2><p>Independent human labels and a frozen evaluation are still required. No real-world detection accuracy is claimed here.</p></div><span className="badge warning">Research in progress</span></div>
    <div className="research-track"><div><span className="dot green" /><strong>Implemented</strong><p>Deterministic research core, version comparison, and experimental baseline infrastructure.</p></div><div><span className="dot amber" /><strong>Requires independent evidence</strong><p>Human annotation, representative real histories, and external attack evaluation.</p></div><div><span className="dot" /><strong>Not available in this interface</strong><p>Training jobs, benchmark comparisons, and published accuracy results.</p></div></div>
    <section className="panel annotation-lab"><div className="section-heading"><div><h2>Independent annotation workspace</h2><p>Blinded candidates. Human decisions. Compatible JSONL exports.</p></div><button className="button subtle" disabled={!annotations.length} onClick={() => setExportOpen(true)}><Icon name="download" size={15} />Export {annotations.length || ''} labels</button></div>
      <div className="annotation-boundary"><Icon name="lock" size={16} /><span>One annotator per session. Suggestions and model predictions are hidden. Labels exist only in memory; export before closing the app. The interface cannot certify annotator independence.</span></div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}{message ? <p className="small muted" role="status">{message}</p> : null}
      {!candidates.length ? <div className="annotation-import"><label className="form-label">Annotator ID<input value={annotator} maxLength={128} onChange={event => setAnnotator(event.target.value)} placeholder="Your independent rater ID" /></label><label className="file-drop"><Icon name="file" size={26} /><strong>Choose annotation candidates</strong><span>AnnotationCandidate JSONL · real_history only · 1 MiB maximum</span><input type="file" accept=".jsonl,.ndjson,application/x-ndjson" aria-label="Choose annotation candidate JSONL" disabled={!annotator.trim()} onChange={event => {
        const file = event.target.files?.[0]; if (!file) return;
        if (file.size > MAX_IMPORT_BYTES) { setError('Choose a candidate file smaller than 1 MiB.'); return; }
        void file.text().then(text => { try { setCandidates(parseCandidates(text)); setError(''); } catch (failure) { setError(failure instanceof Error ? failure.message : 'Invalid candidate JSONL.'); } });
      }} /></label></div> : candidate ? <>
        <div className="annotation-heading"><div><span className="eyebrow">CANDIDATE {annotations.length + 1} OF {candidates.length}</span><h3>{candidate.tool_name}</h3><p>{candidate.repository_id} · {candidate.old_version_id.slice(0, 12)} → {candidate.new_version_id.slice(0, 12)}</p></div><span className="badge">Rater: {annotator}</span></div>
        <DefinitionDiff oldTool={candidate.old_tool} newTool={candidate.new_tool} />
        <fieldset className="class-picker"><legend>Your classification</legend>{(['C0', 'C1', 'C2', 'C3'] as ChangeClass[]).map(value => <label key={value} className={label === value ? 'selected' : ''}><input type="radio" name="annotation-class" value={value} checked={label === value} onChange={() => setLabel(value)} /><strong>{value}</strong><span>{classLabels[value]}</span></label>)}</fieldset>
        <label className="form-label">Rationale<textarea rows={3} value={rationale} maxLength={10000} onChange={event => setRationale(event.target.value)} placeholder="Explain the observed evidence and uncertainty in your own words." /></label>
        <div className="annotation-actions"><label className="checkbox-label"><input type="checkbox" checked={secondReview} onChange={event => setSecondReview(event.target.checked)} />Request a second review</label><button className="button primary" disabled={!label || !rationale.trim()} onClick={finish}>Record human label <Icon name="arrow" size={15} /></button></div>
      </> : <div className="inline-empty"><Icon name="check" size={32} /><h3>All session candidates reviewed</h3><p>Export your labels and provide them for independent comparison and adjudication. Exporting does not make them ground truth.</p><button className="button primary" onClick={() => setExportOpen(true)}>Export human annotations</button></div>}
    </section>
    {exportOpen ? <Dialog title="Export human annotation JSONL" wide onClose={() => setExportOpen(false)}><p className="dialog-copy">These are your own session decisions. Rationale text is included; review it before sharing. No model suggestions or tool definitions are exported. Confirm the download completed before closing.</p><textarea className="export-preview" aria-label="Human annotation JSONL preview" readOnly value={annotationsJsonl(annotations)} /><div className="dialog-actions"><button className="button subtle" onClick={() => setExportOpen(false)}>Close</button><button className="button primary" onClick={() => { downloadText('driftguard-human-annotations.jsonl', annotationsJsonl(annotations), 'application/x-ndjson'); setExportedCount(annotations.length); }}>Download JSONL</button></div></Dialog> : null}
  </>;
}
