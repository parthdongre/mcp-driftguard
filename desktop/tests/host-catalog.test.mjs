import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const bundled = await build({ entryPoints: ['src/host-catalog-utils.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
const { parseHostCatalog } = await import('data:text/javascript;base64,' + Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const app = { source_id: 'figma', name: 'Figma', description: 'Design tools', captured_at: '2026-10-28', visibility: 'session_tools', tools: [{ name: 'inspect', description: 'Read a design' }] };
const encode = sources => JSON.stringify({ format: 'driftguard-host-catalog-v1', sources });

test('host metadata keeps descriptions without inventing input schemas or connection state', () => {
  const [parsed] = parseHostCatalog(encode([app]));
  assert.deepEqual(parsed.tools, app.tools);
  assert.ok(!('inputSchema' in parsed.tools[0]));
  assert.equal(parseHostCatalog(encode([{ ...app, tools: [], visibility: 'skills_only' }]))[0].tools.length, 0);
});

test('host metadata rejects duplicate sources, duplicate tools and live-status claims', () => {
  assert.throws(() => parseHostCatalog(encode([app, app])), /duplicate/);
  assert.throws(() => parseHostCatalog(encode([{ ...app, tools: [app.tools[0], app.tools[0]] }])), /duplicate/);
  assert.throws(() => parseHostCatalog(encode([{ ...app, visibility: 'connected' }])), /invalid/);
  assert.throws(() => parseHostCatalog(encode([{ ...app, source_id: undefined }])), /invalid/);
  assert.throws(() => parseHostCatalog(encode([{ ...app, visibility: 'skills_only' }])), /invalid/);
});

const fetchBundle = await build({ entryPoints: ['src/fetch-utils.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
const { collectionSummary } = await import('data:text/javascript;base64,' + Buffer.from(fetchBundle.outputFiles[0].text).toString('base64'));
test('zero-tool and partial results cannot be displayed as successful collection', () => {
  assert.equal(collectionSummary({ tools: 0, servers: 1 }).tone, 'neutral');
  assert.equal(collectionSummary({ tools: 2, servers: 1, warnings: ['unavailable'] }).tone, 'warning');
  assert.equal(collectionSummary({ tools: 2, servers: 1 }).tone, 'success');
});
