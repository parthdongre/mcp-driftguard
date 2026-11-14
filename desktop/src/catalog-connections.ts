import type { ToolRecord } from './types';

type ToolSource = Pick<ToolRecord, 'server_id' | 'connection'>;

export const catalogSource = ({ server_id, connection }: ToolSource): string =>
  connection ? JSON.stringify([server_id, connection.id]) : server_id;

export const catalogLabel = (tool: ToolSource, sources: Map<string, string>): string =>
  tool.connection?.label || sources.get(tool.server_id) || tool.server_id;

export function groupCatalog<T extends ToolSource>(tools: T[], sources: Map<string, string>) {
  const groups = new Map<string, { id: string; label: string; tools: T[] }>();
  for (const tool of tools) {
    const id = catalogSource(tool);
    const group = groups.get(id);
    if (group) group.tools.push(tool);
    else groups.set(id, { id, label: catalogLabel(tool, sources), tools: [tool] });
  }
  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
}
