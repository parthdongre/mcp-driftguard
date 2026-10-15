import type { AuditEvent, ToolDefinition } from './types';

export const MAX_IMPORT_BYTES = 1_048_576;

export function parseDefinitions(text: string): ToolDefinition[] {
  if (new TextEncoder().encode(text).byteLength > MAX_IMPORT_BYTES) throw new Error('Choose a JSON file smaller than 1 MiB.');
  const value: unknown = JSON.parse(text);
  const candidate = Array.isArray(value) ? value : (isRecord(value) ? value.tools : null);
  if (!Array.isArray(candidate) || candidate.length === 0 || candidate.length > 200) {
    throw new Error('Expected 1–200 tool definitions, as an array or a tools/list result with a tools array.');
  }
  const seen = new Set<string>();
  for (const item of candidate) {
    if (!isRecord(item) || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 200) throw new Error('Every tool needs a nonempty name of at most 200 characters.');
    if (seen.has(item.name)) throw new Error(`Duplicate tool name: ${item.name}`);
    seen.add(item.name);
    if (!isRecord(item.inputSchema)) throw new Error(`Tool ${item.name} needs an inputSchema object.`);
    if (item.description !== undefined && typeof item.description !== 'string') throw new Error(`Tool ${item.name} has an invalid description.`);
  }
  return candidate as ToolDefinition[];
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function displayValue(value: unknown): string {
  if (value === undefined) return 'Not declared';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

/** Default audit exports intentionally omit raw definitions, arguments, reasons, and detail. */
export function safeAuditExport(events: AuditEvent[], demo: boolean): string {
  return JSON.stringify({
    format: 'driftguard.audit-summary.v1',
    fixture_mode: demo,
    exported_at: new Date().toISOString(),
    omitted_fields: ['detail', 'definitions', 'arguments', 'reasons'],
    events: events.map(({ event, timestamp }) => ({ event, timestamp })),
  }, null, 2);
}

export function formatTime(value?: string | null): string {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function downloadText(name: string, text: string, type = 'application/json'): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
