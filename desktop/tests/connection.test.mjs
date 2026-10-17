import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';
const built = await build({ entryPoints: ['src/connection-utils.ts'], bundle: true, platform: 'node', format: 'esm', write: false });
const utils = await import('data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64'));

test('connection profile keeps literal arguments and only environment names', () => {
  const profile = utils.buildProfile('notes', JSON.stringify(['/opt/server', 'a b', '$(never-execute)']), '/opt/work', '2025-11-25', 'API_TOKEN, API_TOKEN');
  assert.deepEqual(profile.argv, ['/opt/server', 'a b', '$(never-execute)']);
  assert.deepEqual(profile.pass_env, ['API_TOKEN']);
  assert.throws(() => utils.buildProfile('notes', '["python"]', '/opt/work', '2025-11-25', 'TOKEN=secret'));
  assert.throws(() => utils.buildProfile('notes', '"python server.py"', '/opt/work', '2025-11-25', ''));
  assert.throws(() => utils.buildProfile('notes', '["python"]', 'relative', '2025-11-25', ''));
});

test('client setup binds the installed runtime and shared store without shell quoting', () => {
  const runtime = { engine_available: true, packaged: true, gateway_argv: ['C:\\Program Files\\DriftGuard\\engine.exe', 'gateway'], state_path: 'C:\\Users\\Parth\\guard.sqlite3' };
  const config = utils.buildClientConfig(runtime, 'C:\\Users\\Parth\\notes.json', 'notes').mcpServers.notes;
  assert.equal(config.command, runtime.gateway_argv[0]);
  assert.deepEqual(config.args, ['gateway', 'serve', '--config', 'C:\\Users\\Parth\\notes.json', '--state', runtime.state_path]);
  assert.throws(() => utils.buildClientConfig({ ...runtime, engine_available: false }, '/tmp/profile.json', 'notes'));
  assert.throws(() => utils.buildClientConfig(runtime, 'relative.json', 'notes'));
});
