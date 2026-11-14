export type Page = 'overview' | 'connections' | 'graph' | 'review' | 'activity' | 'research' | 'settings';
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
  blocked?: boolean;
  description?: string; classification?: ChangeClass | 'unreviewed' | null; reasons?: string[];
  observed_at?: string; revision?: number;
  catalog?: { operations: string[]; resources: string[] };
  connection?: { id: string; label: string };
}
export interface GraphTool {
  tool_name: string;
  status: string;
  version_count: number | null;
  connection?: ToolRecord['connection'];
}
export interface GraphRoute {
  source_id: string;
  server_id: string;
  kind: 'gateway' | 'review';
  client_id: string | null;
  client_label: string | null;
  active: boolean;
  stopped?: boolean;
  connection_state?: string;
  last_checked?: string | null;
  tools: GraphTool[];
  connection?: ToolRecord['connection'];
}
export interface TemporalEvidence {
  step_risk?: number; baseline_risk?: number; cusum_score?: number;
  alerted?: boolean; reasons?: string[]; versions_seen?: number;
}
export interface Review extends ToolRecord {
  baseline_kind?: 'observed' | 'approved' | null;
  route_blocked?: boolean;
  shared_blocked?: boolean;
  old_tool: ToolDefinition | null; new_tool: ToolDefinition;
  quarantine_active?: boolean;
  model_decision?: { id: string; action: string; score: number };
  capability_delta?: Record<string, unknown> | null; temporal?: TemporalEvidence | null;
}
export interface HistoryVersion extends ToolRecord {
  raw_tool?: ToolDefinition; step_risk?: number; baseline_risk?: number; cusum_score?: number;
}
export interface AuditEvent {
  id?: string | number; event: string; server_id?: string; tool_name?: string;
  timestamp?: string; detail?: unknown;
}
export interface DefinitionAlerts {
  unread: number;
  catalog_revision?: number;
  new_mcp_count?: number;
  new_mcp?: { id: number; server_id: string; detail: { name?: string } } | null;
  latest: { id: number; tool_name: string; server_id: string;
    detail: { changed_fields?: string[] } } | null;
}
export interface CatalogSync {
  servers: { harness: string; name: string | null; state: 'observed' | 'unavailable'; sign_in?: boolean; tools?: number; message?: string }[];
}
export interface Overview {
  protection_status: 'review_only' | 'gateway_ready' | 'gateway_active'; servers: number; tools: number;
  pending: number; approved: number; quarantined: number; last_verification: string | null; scope: string;
  server_list?: { server_id: string; display_name?: string }[];
  gateway_health?: { server_id: string; heartbeat_at: string; active: number | boolean }[];
}
export interface Workspace {
  overview: Overview; tools: ToolRecord[]; activity: AuditEvent[];
}
export type BridgeAction = 'live_connect' | 'live_status' | 'live_verify' | 'live_disconnect' | 'live_run_codex' | 'live_cancel_codex' | 'host_catalog_import' | 'host_catalog_list' | 'harness_scan' | 'harness_fetch' | 'store_http_credential' | 'remove_http_credential' | 'runtime_info' | 'overview' | 'list_tools' | 'review' | 'history' | 'activity' |
  'gateway_servers' | 'register_codex_hosted' | 'launch_gateway_only_codex' | 'save_gateway_server' | 'remove_gateway_server' | 'link_gateway_server_codex' | 'link_gateway_server' | 'check_gateway_server' | 'codex_mcp_sign_in' |
  'approval_mode' | 'set_approval_mode' | 'route_codex_mcps' | 'restore_codex_mcps' |
  'connection_graph' | 'mcp_activity' | 'monitoring_settings' | 'set_monitoring_settings' | 'sync_harness_catalogs' | 'harness_helpers' | 'tool_activity' | 'definition_alerts' | 'dismiss_definition_alerts' |
  'sentinel_calls' | 'sentinel_evidence' | 'sentinel_stop' | 'sentinel_resume' | 'sentinel_clear' |
  'import_definitions' | 'approve' | 'deny' | 'quarantine' | 'release_quarantine' | 'block_tool' | 'unblock_tool' |
  'block_tool_all' | 'unblock_tool_all';
export type ReviewAction = 'approve' | 'deny' | 'quarantine' | 'release_quarantine' |
  'block_tool' | 'unblock_tool' | 'block_tool_all' | 'unblock_tool_all';
export interface BridgeRequest {
  action: BridgeAction; server_id?: string; tool_name?: string; expected_sha256?: string; expected_revision?: number;
  harness?: string;
  identity?: string; tools?: ToolDefinition[]; url?: string; secret?: string;
  project_dir?: string; source_id?: string; config_digest?: string;
  summary?: boolean;
  through_id?: number;
  before_id?: number;
  settings?: MonitoringSettings;
  include_checks?: boolean;
  call_id?: number;
  mode?: ApprovalMode;
  open_terminal?: boolean;
  transport?: 'stdio' | 'http';
  use_os_vault?: boolean;
  argv?: string[];
  cwd?: string;
  pass_env?: string[];
  source?: import('./host-catalog-utils').HostSource;
}
export interface DemoFixture { overview: Overview; tools: ToolRecord[]; reviews: Review[]; history: HistoryVersion[]; activity: AuditEvent[]; }

export interface MonitoringSettings {
  idle_seconds: number;
  active_seconds: number;
  active_window_seconds: number;
  discovery_seconds: number;
  discovery_enabled: boolean;
}

export interface McpActivityEvent extends Omit<AuditEvent, 'tool_name'> {
  id: number;
  server_id: string;
  tool_name: string | null;
  timestamp: string;
  detail: Record<string, unknown>;
}

export type ApprovalMode = 'manual' | 'read_only' | 'all_first_seen';
