import { isRecord, MAX_IMPORT_BYTES } from './review-utils';
import type { ChangeClass, ToolDefinition } from './types';

export interface Candidate {
  candidate_id: string; repository_id: string; tool_name: string; server_id: string;
  old_version_id: string; new_version_id: string; old_tool: ToolDefinition; new_tool: ToolDefinition;
}
export interface HumanAnnotation {
  annotation_id: string; candidate_id: string; annotator_id: string; label: ChangeClass;
  evidence: string[]; rationale: string; requires_second_review: boolean;
}

/** Copy only blinded source fields; model predictions and suggested labels never enter session state. */
export function parseCandidates(text: string): Candidate[] {
  if (new TextEncoder().encode(text).byteLength > MAX_IMPORT_BYTES) throw new Error('Choose a candidate file smaller than 1 MiB.');
  const lines = text.split('\n').filter(line => line.trim());
  if (!lines.length || lines.length > 500) throw new Error('Choose 1–500 candidates in JSONL format.');
  const ids = new Set<string>();
  return lines.map((line, index) => {
    const row: unknown = JSON.parse(line);
    if (!isRecord(row) || row.provenance !== 'real_history') throw new Error(`Line ${index + 1}: expected a real_history annotation candidate.`);
    const names = ['candidate_id', 'repository_id', 'server_id', 'tool_name', 'old_version_id', 'new_version_id'] as const;
    for (const name of names) if (typeof row[name] !== 'string' || !(row[name] as string).trim()) throw new Error(`Line ${index + 1}: missing ${name}.`);
    if (ids.has(row.candidate_id as string)) throw new Error(`Duplicate candidate ID at line ${index + 1}.`);
    ids.add(row.candidate_id as string);
    if (!isRecord(row.old_tool) || !isRecord(row.new_tool) || typeof row.old_tool.name !== 'string' || typeof row.new_tool.name !== 'string') throw new Error(`Line ${index + 1}: invalid old/new definitions.`);
    return Object.fromEntries([...names.map(name => [name, row[name]]), ['old_tool', row.old_tool], ['new_tool', row.new_tool]]) as unknown as Candidate;
  });
}

export function makeAnnotation(candidate: Candidate, annotator: string, label: ChangeClass | '', rationale: string, secondReview: boolean): HumanAnnotation {
  if (!annotator.trim() || !rationale.trim() || !['C0', 'C1', 'C2', 'C3'].includes(label)) throw new Error('Choose a class and provide your annotator ID and rationale.');
  return {
    annotation_id: `${annotator.trim()}:${candidate.candidate_id}:${crypto.randomUUID()}`,
    candidate_id: candidate.candidate_id, annotator_id: annotator.trim(), label: label as ChangeClass,
    evidence: [], rationale: rationale.trim(), requires_second_review: secondReview,
  };
}

export const annotationsJsonl = (annotations: HumanAnnotation[]): string => annotations.map(annotation => JSON.stringify(annotation)).join('\n') + (annotations.length ? '\n' : '');
