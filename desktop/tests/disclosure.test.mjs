import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
import { resolve } from 'node:path';

const built = await build({
  stdin: { contents: `
    import { renderToStaticMarkup } from 'react-dom/server.node';
    import { Disclosure } from './src/Disclosure';
    import { HarnessConnections } from './src/HarnessConnections';
    import { ReviewPanel } from './src/ReviewPanel';
    export const row = () => renderToStaticMarkup(<Disclosure title="Codex MCP catalog"><p>Private details</p><button>Fetch definitions</button></Disclosure>);
    export const harness = () => renderToStaticMarkup(<HarnessConnections native={false} onCollected={() => {}} />);
    export const review = () => renderToStaticMarkup(<ReviewPanel review={{ server_id:'source', tool_name:'read_notes', sha256:'a'.repeat(64), status:'pending', old_tool:null, new_tool:{name:'read_notes',inputSchema:{type:'object'}}, reasons:['Review required'] }} onDecision={() => {}} onTimeline={() => {}} busy={false} />);
  `, resolveDir: process.cwd(), loader: 'tsx' },
  bundle: true, platform: 'node', format: 'esm', write: false, jsx: 'automatic',
  banner: { js: `import { createRequire } from 'node:module'; const require = createRequire(${JSON.stringify(resolve('package.json'))});` },
});
const ui = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));
const summaries = html => [...html.matchAll(/<summary>([\s\S]*?)<\/summary>/g)].map(match => match[1]);

test('a collapsed source exposes only its name and keeps actions inside the body', () => {
  const html = ui.row();
  assert.ok(!/<details[^>]*\sopen(?:[=\s>])/.test(html));
  const [summary] = summaries(html);
  assert.equal(summary.replace(/<[^>]*>/g, ''), 'Codex MCP catalog');
  assert.ok(!summary.includes('Private details') && !summary.includes('Fetch definitions'));
  assert.ok(html.indexOf('Fetch definitions') > html.indexOf('</summary>'));
});

test('connection controls remain in the closed setup body and browser access stays disabled', () => {
  const html = ui.harness();
  assert.ok(summaries(html).some(summary => summary.includes('Connect your coding harness')));
  assert.ok(summaries(html).every(summary => !summary.includes('<button') && !summary.includes('<p>')));
  assert.match(html, /<button[^>]*disabled=""[^>]*>Find harness connections<\/button>/);
  assert.ok(!/<details[^>]*\sopen(?:[=\s>])/.test(html));
});

test('security evidence and contracts collapse while approval actions remain explicit', () => {
  const html = ui.review();
  const text = summaries(html).map(summary => summary.replace(/<[^>]*>/g, ''));
  assert.ok(text.includes('Review evidence') && text.includes('Input contract'));
  assert.ok(html.includes('Approve version') && html.includes('Decision binds to this exact definition.'));
  assert.ok(!summaries(html).some(summary => summary.includes('Approve version')));
});
