export interface HostTool { name: string; description: string }
export interface HostSource {
  source_id: string; name: string; description: string; tools: HostTool[];
  captured_at: string; visibility: 'session_tools' | 'skills_only' | 'not_exposed';
}
export const MAX_HOST_CATALOG_BYTES = 16 * 1024 * 1024;

export function parseHostCatalog(text: string): HostSource[] {
  if (new TextEncoder().encode(text).length > MAX_HOST_CATALOG_BYTES) throw new Error('Choose a hosted catalog smaller than 16 MiB.');
  let data;
  try { data = JSON.parse(text); } catch { throw new Error('The catalog is not valid JSON.'); }
  if (!data || data.format !== 'driftguard-host-catalog-v1' || !Array.isArray(data.sources) || data.sources.length > 200) throw new Error('Choose a DriftGuard hosted-app catalog export.');
  const ids = new Set<string>();
  return data.sources.map((source: HostSource) => {
    if (!source || typeof source.source_id !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(source.source_id) || ids.has(source.source_id) ||
      typeof source.name !== 'string' || !source.name || source.name.length > 200 ||
      typeof source.description !== 'string' || source.description.length > 16000 ||
      typeof source.captured_at !== 'string' || source.captured_at.length > 64 ||
      !['session_tools', 'skills_only', 'not_exposed'].includes(source.visibility) ||
      !Array.isArray(source.tools) || source.tools.length > 500 || (source.visibility !== 'session_tools' && source.tools.length > 0)) throw new Error('The catalog contains an invalid or duplicate app entry.');
    ids.add(source.source_id);
    const names = new Set<string>();
    const tools = source.tools.map(tool => {
      if (!tool || typeof tool.name !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(tool.name) || names.has(tool.name) || typeof tool.description !== 'string' || new TextEncoder().encode(tool.description).length > 60000) throw new Error('The catalog contains an invalid or duplicate tool.');
      names.add(tool.name);
      return { name: tool.name, description: tool.description };
    });
    const parsed = { source_id: source.source_id, name: source.name, description: source.description,
      captured_at: source.captured_at, visibility: source.visibility, tools };
    if (new TextEncoder().encode(JSON.stringify(parsed)).length > 1000000) throw new Error('One app exceeds the per-import size limit.');
    return parsed;
  });
}
