import assert from 'node:assert/strict';
import test from 'node:test';
import { build } from 'esbuild';

const built = await build({
  entryPoints: ['src/harness-state.ts'],
  bundle: true,
  platform: 'node',
  format: 'esm',
  write: false,
});
const { harnessPresentation } = await import(
  'data:text/javascript;base64,' + Buffer.from(built.outputFiles[0].text).toString('base64')
);

test('newly detected harness offers Connect, not Disconnect', () => {
  const view = harnessPresentation({ detected: true, installed: false, configured: false, attached: 0 });
  assert.equal(view.canConnect, true);
  assert.equal(view.canDisconnect, false);
  assert.equal(view.badge, null);
});

test('valid managed harness offers Disconnect and reports configuration accurately', () => {
  const view = harnessPresentation({ detected: true, installed: true, configured: true, attached: 0 });
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, true);
  assert.equal(view.badge, 'Configured');
  assert.match(view.description, /new client session/);
});

test('stale managed entry remains disconnectable, never invites a failing reconnect', () => {
  const view = harnessPresentation({ detected: true, installed: true, configured: false, attached: 0 });
  assert.equal(view.needsRepair, true);
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, true);
  assert.match(view.description, /disconnect, then reconnect/);
});

test('disconnected harness with a lingering session does not claim protection', () => {
  const view = harnessPresentation({ detected: true, installed: false, configured: false, attached: 1 });
  assert.equal(view.connected, false);
  assert.equal(view.badge, null);
  assert.match(view.description, /restart the client/);
});

test('attached managed session is distinguished from configured but idle', () => {
  const view = harnessPresentation({ detected: true, installed: true, configured: true, attached: 2 });
  assert.equal(view.badge, 'Connected');
  assert.equal(view.description, 'MCP session attached');
});
