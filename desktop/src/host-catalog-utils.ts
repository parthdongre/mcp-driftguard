export interface HostTool { name: string; description: string }
export interface HostSource {
  source_id: string; name: string; description: string; tools: HostTool[];
  captured_at: string; visibility: 'session_tools' | 'skills_only' | 'not_exposed';
}
