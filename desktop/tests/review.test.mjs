import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

async function sourceModule(file) {
  const result = await build({ entryPoints: [file], bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'silent' });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const utils = await sourceModule('src/review-utils.ts');
const annotations = await sourceModule('src/annotation-utils.ts');
const bridge = await sourceModule('src/bridge.ts');
const definition = { name: 'search', inputSchema: { type: 'object' } };
const candidate = { candidate_id: 'candidate-1', repository_id: 'example/server', server_id: 'local', tool_name: 'search', old_version_id: 'v0', new_version_id: 'v1', old_tool: definition, new_tool: { ...definition, description: 'Updated' }, provenance: 'real_history', suggested_label: 'C3', model_probability: 0.99, suggested_evidence: ['model_hint'] };

test('imports tools/list responses and rejects duplicate or invalid definitions', () => {
  assert.deepEqual(utils.parseDefinitions(JSON.stringify({ tools: [definition] })), [definition]);
  assert.throws(() => utils.parseDefinitions(JSON.stringify([definition, definition])), /Duplicate/);
  assert.throws(() => utils.parseDefinitions(JSON.stringify([{ name: 'invalid', inputSchema: [] }])));
  assert.throws(() => utils.parseDefinitions('x'.repeat(utils.MAX_IMPORT_BYTES + 1)), /1 MiB/);
});

test('annotation import blinds predictions and refuses duplicate candidate identities', () => {
  const parsed = annotations.parseCandidates(JSON.stringify(candidate));
  assert.equal(parsed.length, 1);
  assert.equal(parsed[0].candidate_id, candidate.candidate_id);
  assert.equal('suggested_evidence' in parsed[0], false);
  assert.equal('model_probability' in parsed[0], false);
  assert.equal('suggested_label' in parsed[0], false);
  assert.throws(() => annotations.parseCandidates(`${JSON.stringify(candidate)}\n${JSON.stringify(candidate)}`), /Duplicate/);
});

test('human labels require explicit class, annotator and rationale with compatible export', () => {
  assert.throws(() => annotations.makeAnnotation(candidate, 'rater-a', '', 'reason', false));
  assert.throws(() => annotations.makeAnnotation(candidate, '', 'C1', 'reason', false));
  assert.throws(() => annotations.makeAnnotation(candidate, 'rater-a', 'C1', '', false));
  const human = annotations.makeAnnotation(candidate, 'rater-a', 'C1', 'Clarified wording', true);
  assert.equal(JSON.parse(annotations.annotationsJsonl([human])).candidate_id, candidate.candidate_id);
  assert.equal(human.requires_second_review, true);
});

test('default audit export strips identities, tool definitions, arguments and details', () => {
  const result = utils.safeAuditExport([{ event: 'tool_approved', timestamp: '2026-10-15T00:00:00Z', tool_name: 'private-name', server_id: 'private-server', detail: { secret: 'sensitive-value' } }], false);
  assert.ok(!result.includes('private-name') && !result.includes('private-server') && !result.includes('sensitive-value'));
  assert.equal(JSON.parse(result).events[0].event, 'tool_approved');
});

test('denial filter covers both native and fixture event names', () => {
  assert.equal(utils.matchesActivityFilter('tool_denied', 'deny'), true);
  assert.equal(utils.matchesActivityFilter('fixture_deny', 'deny'), true);
  assert.equal(utils.matchesActivityFilter('tool_approved', 'deny'), false);
  assert.equal(utils.matchesActivityFilter('catalog_observed', 'observ'), true);
});

test('guided fixture cannot bypass quarantine through deny and approve, and rejects stale revisions', async () => {
  const workspace = new bridge.DemoWorkspace();
  const tools = await workspace.request({ action: 'list_tools' });
  assert.ok(tools.length >= 3, 'Generate the detector fixture before testing');
  const tool = tools.find(row => row.status === 'pending');
  assert.ok(tool, 'Fixture includes a reviewable update');
  const binding = { server_id: tool.server_id, tool_name: tool.tool_name, expected_sha256: tool.sha256, expected_revision: tool.revision };
  const quarantined = await workspace.request({ action: 'quarantine', ...binding });
  await assert.rejects(workspace.request({ action: 'approve', ...binding }), /version has changed/);
  const denied = await workspace.request({ action: 'deny', ...binding, expected_revision: quarantined.revision });
  await assert.rejects(workspace.request({ action: 'approve', ...binding, expected_revision: denied.revision }), /Quarantined/);
  const fresh = new bridge.DemoWorkspace();
  assert.equal((await fresh.request({ action: 'list_tools' })).find(row => row.tool_name === tool.tool_name).status, 'pending');
});
