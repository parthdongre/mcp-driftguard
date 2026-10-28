export type Page = 'overview' | 'connections' | 'review' | 'timeline' | 'activity' | 'research' | 'settings';
export type ChangeClass = 'C0' | 'C1' | 'C2' | 'C3';
export interface ToolDefinition {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  annotations?: Record<string, unknown>;
  [field: string]: unknown;
}
export interface ToolRecord {
  server_id: string; tool_name: string; sha256: string; status: string;
  description?: string; classification?: ChangeClass | 'unreviewed' | null; reasons?: string[];
  observed_at?: string; revision?: number;
}
export interface TemporalEvidence {
  step_risk?: number; baseline_risk?: number; cusum_score?: number;
  alerted?: boolean; reasons?: string[]; versions_seen?: number;
}
export interface Review extends ToolRecord {
  old_tool: ToolDefinition | null; new_tool: ToolDefinition;
  capability_delta?: Record<string, unknown> | null; temporal?: TemporalEvidence | null;
}
export interface HistoryVersion extends ToolRecord {
  raw_tool?: ToolDefinition; step_risk?: number; baseline_risk?: number; cusum_score?: number;
}
export interface AuditEvent {
  id?: string | number; event: string; server_id?: string; tool_name?: string;
  timestamp?: string; detail?: unknown;
}
export interface Overview {
  protection_status: 'review_only' | 'gateway_ready'; servers: number; tools: number;
  pending: number; approved: number; quarantined: number; last_verification: string | null; scope: string;
  server_list?: { server_id: string }[];
  gateway_health?: { server_id: string; heartbeat_at: string; active: number }[];
}
export interface Workspace {
  overview: Overview; tools: ToolRecord[]; activity: AuditEvent[];
}
export type BridgeAction = 'harness_scan' | 'harness_fetch' | 'store_http_credential' | 'remove_http_credential' | 'runtime_info' | 'overview' | 'list_tools' | 'review' | 'history' | 'activity' |
  'import_definitions' | 'approve' | 'deny' | 'quarantine';
export interface BridgeRequest {
  action: BridgeAction; server_id?: string; tool_name?: string; expected_sha256?: string; expected_revision?: number;
  identity?: string; tools?: ToolDefinition[]; url?: string; secret?: string;
  project_dir?: string; source_id?: string; config_digest?: string;
}
export interface DemoFixture { overview: Overview; tools: ToolRecord[]; reviews: Review[]; history: HistoryVersion[]; activity: AuditEvent[]; }
