export interface FetchResult {
  tools: number; servers: number; warnings?: string[]; status?: 'complete' | 'partial' | 'empty';
}

export function collectionSummary(result: FetchResult): { message: string; tone: 'success' | 'warning' | 'neutral' } {
  if (result.tools === 0) return { message: 'No tool definitions returned.', tone: 'neutral' };
  const count = `${result.tools} ${result.tools === 1 ? 'definition' : 'definitions'} · ${result.servers} ${result.servers === 1 ? 'source' : 'sources'}`;
  if (result.status === 'partial' || result.warnings?.length) return { message: `${count} · Partial discovery`, tone: 'warning' };
  return { message: count, tone: 'success' };
}
