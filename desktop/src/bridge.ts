import type { BridgeRequest, DemoFixture, HistoryVersion, Overview, Review, ToolRecord } from './types';
import fixture from './demo.json';

export const hasNativeBridge = (): boolean => '__TAURI_INTERNALS__' in window;

export const emptyOverview: Overview = {
  protection_status: 'review_only', servers: 0, tools: 0, pending: 0, approved: 0,
  quarantined: 0, last_verification: null,
  scope: 'Only explicitly routed gateway clients are protected. Imported definitions are for review.',
};

export async function request<T>(payload: BridgeRequest): Promise<T> {
  if (!hasNativeBridge()) throw new Error('The local bridge is available inside the native desktop app. Browser preview does not protect MCP connections.');
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const response = await invoke<{ ok: boolean; data?: T; error?: { code: string; message: string } }>('driftguard_request', { request: payload });
    if (!response.ok || response.data === undefined) throw new Error(response.error?.message ?? 'The gateway could not complete this request.');
    return response.data;
  } catch (failure) {
    // Rust Result<_, String> rejections arrive as strings, not Error instances.
    // Preserve the native diagnostic so the UI can explain missing/stale engines.
    if (failure instanceof Error) throw failure;
    if (typeof failure === 'string' && failure.trim()) throw new Error(failure);
    throw new Error('The native bridge failed without a diagnostic. Restart the desktop app and check its terminal output.');
  }
}

/** Deliberately isolated from the native bridge and browser storage. */
export class DemoWorkspace {
  private fixture: DemoFixture = structuredClone(fixture) as DemoFixture;
  private quarantined = new Set(this.fixture.tools.filter(tool => tool.status === 'quarantined' || tool.classification === 'C3').map(tool => `${toolKey(tool)}:${tool.sha256}`));

  async request<T>(payload: BridgeRequest): Promise<T> {
    const data = this.fixture;
    const tool = data.tools.find(t => t.server_id === payload.server_id && t.tool_name === payload.tool_name);
    let result: unknown;
    switch (payload.action) {
      case 'overview': result = data.overview; break;
      case 'list_tools': result = data.tools; break;
      case 'activity': result = data.activity; break;
      case 'history': result = data.history.filter(t => t.server_id === payload.server_id && t.tool_name === payload.tool_name); break;
      case 'review': result = data.reviews.find(t => t.server_id === payload.server_id && t.tool_name === payload.tool_name); break;
      case 'approve': case 'deny': case 'quarantine': {
        if (!tool || tool.sha256 !== payload.expected_sha256 || tool.revision !== payload.expected_revision) throw new Error('This version has changed. Refresh the evidence before deciding.');
        const identity = `${toolKey(tool)}:${tool.sha256}`;
        if (payload.action === 'approve' && this.quarantined.has(identity)) throw new Error('Quarantined definitions cannot be approved. Correct the source and observe a safe version.');
        if (payload.action === 'quarantine') this.quarantined.add(identity);
        tool.revision = (tool.revision ?? 0) + 1;
        tool.status = payload.action === 'approve' ? 'approved' : payload.action === 'deny' ? 'denied' : 'quarantined';
        const review = data.reviews.find(t => t.server_id === tool.server_id && t.tool_name === tool.tool_name);
        if (review) { review.status = tool.status; review.revision = tool.revision; }
        data.overview.pending = data.tools.filter(t => ['pending', 'unreviewed', 'review_required'].includes(t.status)).length;
        data.overview.approved = data.tools.filter(t => t.status === 'approved').length;
        data.overview.quarantined = data.tools.filter(t => t.status === 'quarantined').length;
        data.activity.unshift({ event: `fixture_${payload.action}`, tool_name: tool.tool_name, server_id: tool.server_id, timestamp: new Date().toISOString() });
        result = tool; break;
      }
      case 'import_definitions': throw new Error('Exit the guided demo to import definitions into your local workspace.');
      default: throw new Error('Unsupported action.');
    }
    if (result === undefined) throw new Error('No evidence is available for this tool.');
    return structuredClone(result) as T;
  }
}

export function toolKey(tool: Pick<ToolRecord, 'server_id' | 'tool_name'>): string {
  return JSON.stringify([tool.server_id, tool.tool_name]);
}
export const statusLabel = (status: string = 'observed'): string => ({
  approved: 'Approved', quarantined: 'Quarantined', denied: 'Denied', pending: 'Needs review',
  approved_reference: 'Approved reference', observed: 'Observed', revoked: 'Revoked',
  unreviewed: 'Needs review', review_required: 'Needs review',
}[status] ?? status.replaceAll('_', ' '));
export const isPending = (tool: ToolRecord): boolean => ['pending', 'unreviewed', 'review_required'].includes(tool.status);
export type { HistoryVersion, Review };
