import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { resolve, sep } from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

let base = process.env.DRIFTGUARD_PREVIEW_URL;
let server;
if (!base) {
  const dist = fileURLToPath(new URL('../dist/', import.meta.url));
  server = createServer(async (request, response) => {
    try {
      const route = new URL(request.url, 'http://localhost').pathname;
      const file = resolve(dist, '.' + (route === '/' ? '/index.html' : decodeURIComponent(route)));
      if (!file.startsWith(dist.endsWith(sep) ? dist : dist + sep)) { response.writeHead(403).end(); return; }
      response.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.html') ? 'text/html' : 'application/octet-stream');
      response.end(await readFile(file));
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  base = `http://127.0.0.1:${server.address().port}`;
}
const output = new URL('../verification/', import.meta.url);
await mkdir(output, { recursive: true });
const executablePath = process.env.DRIFTGUARD_BROWSER_EXECUTABLE;
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
const page = await browser.newPage({ viewport: { width: 1380, height: 900 }, reducedMotion: 'reduce' });
const errors = [];
const external = [];
page.on('pageerror', error => errors.push(error.message));
page.on('request', request => { if (!request.url().startsWith(base) && !request.url().startsWith('data:')) external.push(request.url()); });
const checks = [];
const accessibility = [];
const check = (name, condition) => { assert.ok(condition, name); checks.push(name); };
async function auditAccessibility(name) {
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const findings = await page.evaluate(async () => {
    const result = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } });
    return result.violations.map(violation => ({ id: violation.id, impact: violation.impact, description: violation.description, nodes: violation.nodes.map(node => ({ target: node.target, failureSummary: node.failureSummary })) }));
  });
  accessibility.push({ name, violations: findings });
}
try {
  await page.goto(base);
  await page.getByRole('heading', { name: 'Overview', exact: true }).waitFor();
  check('Browser preview explicitly has no protected connections', await page.getByText(/Native gateway unavailable/).isVisible());
  await page.screenshot({ path: new URL('overview-empty.png', output).pathname, fullPage: true });
  await page.getByRole('button', { name: /Explore guided demo/ }).first().click();
  await page.getByRole('button', { name: /export_report/ }).first().waitFor();
  check('Guided fixture is explicitly isolated', await page.getByText(/Isolated research fixture/).isVisible());
  await page.screenshot({ path: new URL('overview-fixture.png', output).pathname, fullPage: true });
  await page.getByRole('button', { name: /export_report/ }).first().click();
  await page.getByRole('heading', { name: 'export_report', exact: true }).waitFor();
  check('Reviewable benign fixture allows review', await page.getByRole('button', { name: 'Approve version', exact: true }).isEnabled());
  await page.screenshot({ path: new URL('security-review.png', output).pathname, fullPage: true });
  await auditAccessibility('security-review-light');
  await page.getByRole('button', { name: 'Approve version', exact: true }).click();
  await page.getByRole('dialog').waitFor();
  check('Approval requires an explicit exact-version confirmation', await page.getByRole('heading', { name: 'Approve this exact version?' }).isVisible());
  await page.keyboard.press('Escape');
  check('Escape closes modal', await page.getByRole('dialog').count() === 0);
  await page.getByRole('button', { name: 'Quarantine', exact: true }).click();
  await page.getByRole('button', { name: 'Quarantine', exact: true }).waitFor({ state: 'visible' });
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('Approve version') && button.disabled));
  check('Quarantined exact version cannot be approved', await page.getByRole('button', { name: 'Approve version', exact: true }).isDisabled());
  await page.getByRole('button', { name: 'Tool evolution', exact: true }).click();
  await page.getByRole('button', { name: /search_repository/ }).click();
  await page.getByRole('img', { name: /CUSUM over/ }).waitFor();
  check('Temporal evidence chart renders actual recorded metrics', await page.getByRole('img', { name: /CUSUM over/ }).isVisible());
  await page.screenshot({ path: new URL('tool-evolution.png', output).pathname, fullPage: true });
  await auditAccessibility('tool-evolution-light');
  await page.getByRole('button', { name: 'Research laboratory', exact: true }).click();
  await page.getByRole('textbox', { name: 'Annotator ID', exact: true }).fill('qa-fixture-rater');
  const definition = { name: 'qa_fixture', description: 'Read local files', inputSchema: { type: 'object' } };
  const candidate = { candidate_id: 'qa-fixture-1', repository_id: 'qa/fixture', server_id: 'qa', tool_name: 'qa_fixture', old_version_id: 'v0', new_version_id: 'v1', old_tool: definition, new_tool: { ...definition, description: 'Read selected local files' }, provenance: 'real_history', suggested_evidence: ['HIDDEN_MODEL_HINT'] };
  const candidates = [candidate, { ...candidate, candidate_id: 'qa-fixture-2' }];
  await page.getByLabel('Choose annotation candidate JSONL').setInputFiles({ name: 'qa-fixtures.jsonl', mimeType: 'application/x-ndjson', buffer: Buffer.from(candidates.map(row => JSON.stringify(row)).join('\n')) });
  check('Model hints are absent from annotation UI', !(await page.locator('body').innerText()).includes('HIDDEN_MODEL_HINT'));
  await page.getByRole('radio', { name: /C1/ }).check();
  await page.getByRole('textbox', { name: 'Rationale', exact: true }).fill('Automated UI test fixture only; not a human research label.');
  await page.getByRole('button', { name: /Record human label/ }).click();
  await page.getByText('CANDIDATE 2 OF 2').waitFor();
  await page.getByRole('button', { name: 'Overview', exact: true }).click();
  await page.getByRole('button', { name: 'Research laboratory', exact: true }).click();
  check('Annotation session survives navigation', await page.getByText('CANDIDATE 2 OF 2').isVisible());
  await page.getByRole('button', { name: 'Export 1 labels', exact: true }).click();
  const exported = JSON.parse(await page.getByRole('textbox', { name: 'Human annotation JSONL preview' }).inputValue());
  check('Annotation export preserves candidate and explicit label', exported.candidate_id === 'qa-fixture-1' && exported.label === 'C1');
  await auditAccessibility('annotation-export-dialog');
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download JSONL', exact: true }).click()]);
  const downloaded = JSON.parse(await readFile(await download.path(), 'utf8'));
  check('Annotation download contains the reviewed session record', downloaded.candidate_id === 'qa-fixture-1');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Control+,');
  await page.getByRole('heading', { name: 'Settings', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Dark', exact: true }).click();
  await page.screenshot({ path: new URL('settings-dark.png', output).pathname, fullPage: true });
  await auditAccessibility('settings-dark');
  await page.getByRole('button', { name: 'Light', exact: true }).click();
  await page.setViewportSize({ width: 900, height: 740 });
  await page.getByRole('button', { name: 'Overview', exact: true }).click();
  check('Minimum-width layout has no document overflow', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: new URL('overview-narrow-light.png', output).pathname, fullPage: true });
  await auditAccessibility('overview-narrow-light');
  // Exercise source setup without starting a server or fabricating a connection.
  await page.getByRole('button', { name: 'Exit demo', exact: true }).click();
  await page.getByRole('button', { name: 'MCP connections', exact: true }).click();
  await page.getByLabel('Source identifier', { exact: true }).fill('qa-configured-source');
  await page.getByLabel('Working directory', { exact: true }).fill('/tmp/driftguard-source');
  await page.getByLabel('Server command as JSON', { exact: false }).fill('["/usr/bin/python3","/tmp/server.py"]');
  await page.getByRole('button', { name: 'Prepare source profile', exact: true }).click();
  const [profileDownload] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download source profile', exact: true }).click()]);
  const profile = JSON.parse(await readFile(await profileDownload.path(), 'utf8'));
  check('Guided source setup preserves argument boundaries', profile.argv[1] === '/tmp/server.py');
  await page.getByLabel('Connection transport', { exact: true }).selectOption('http');
  await page.getByLabel('HTTPS endpoint', { exact: true }).fill('https://fixture.invalid/mcp');
  await page.getByLabel('HTTP authentication', { exact: true }).selectOption('environment');
  await page.getByLabel('Bearer environment variable', { exact: false }).fill('FIXTURE_MCP_TOKEN');
  await page.getByRole('button', { name: 'Prepare source profile', exact: true }).click();
  const [httpDownload] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download source profile', exact: true }).click()]);
  const httpProfile = JSON.parse(await readFile(await httpDownload.path(), 'utf8'));
  check('HTTP setup exports a credential name without a credential value', httpProfile.auth_token_env === 'FIXTURE_MCP_TOKEN' && httpProfile.transport === 'http');
  await page.getByLabel('HTTP authentication', { exact: true }).selectOption('vault');
  check('Browser preview cannot store native credentials', await page.getByRole('button', { name: 'Save to OS credential store', exact: true }).isDisabled());
  await auditAccessibility('connection-setup');
  // Test-only IPC stand-in: renderer -> actual Python module -> temporary SQLite.
  // This does not exercise native Rust IPC or establish a real MCP connection.
  const temporary = await mkdtemp(resolve(tmpdir(), 'driftguard-ui-'));
  const statePath = resolve(temporary, 'guard.sqlite3');
  let queue = Promise.resolve();
  const runPython = payload => {
    const operation = queue.then(async () => {
      const child = execFile(process.env.DRIFTGUARD_TEST_PYTHON ?? 'python', ['-m', 'driftguard.desktop_bridge', '--db', statePath], { maxBuffer: 16 * 1024 * 1024, timeout: 20000 });
      child.stdin.end(JSON.stringify(payload));
      let output = '';
      for await (const chunk of child.stdout) output += chunk;
      return JSON.parse(output);
    });
    queue = operation.catch(() => {});
    return operation;
  };
  const connected = await browser.newPage({ viewport: { width: 1380, height: 900 }, reducedMotion: 'reduce' });
  connected.on('pageerror', error => errors.push(error.message));
  try {
    await connected.exposeFunction('__qa_python_bridge', (command, args) => {
      assert.equal(command, 'driftguard_request');
      return runPython(args.request);
    });
    await connected.addInitScript(() => { window.__TAURI_INTERNALS__ = { invoke: (command, args) => window.__qa_python_bridge(command, args) }; });
    await connected.goto(base);
    const importFile = async description => {
      await connected.getByRole('button', { name: 'Import definitions', exact: true }).first().click();
      await connected.getByRole('textbox', { name: 'Source name', exact: true }).fill('qa-source');
      await connected.getByRole('textbox', { name: /Server identity binding/ }).fill('qa-review-binding');
      await connected.getByLabel('Choose tool definitions JSON').setInputFiles({ name: 'qa-definitions.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ tools: [{ ...definition, name: 'qa_import', description }] })) });
      await connected.getByRole('button', { name: 'Import for review', exact: true }).click();
      await connected.getByRole('heading', { name: 'qa_import', exact: true }).waitFor();
    };
    await importFile('Read selected local files');
    await connected.getByRole('button', { name: 'Approve version', exact: true }).click();
    await connected.getByRole('button', { name: 'Approve reviewed version', exact: true }).click();
    await connected.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('Approve version') && button.disabled));
    const approved = await runPython({ action: 'overview' });
    check('Renderer approval persists in actual Python SQLite store', approved.ok && approved.data.approved === 1);
    await connected.getByRole('button', { name: 'Tool evolution', exact: true }).click();
    await connected.getByText('Approved reference', { exact: true }).waitFor();
    check('Actual Python history renders approved reference without missing-status errors', await connected.getByText('Approved reference', { exact: true }).isVisible());
    await connected.getByRole('button', { name: 'MCP connections', exact: true }).click();
    await importFile('Read selected local files with clarified instructions');
    const changed = await runPython({ action: 'overview' });
    check('A changed definition invalidates prior exact-version approval', changed.data.approved === 0 && changed.data.pending === 1);
    const stored = await runPython({ action: 'list_tools' });
    check('Imported approvals remain isolated from live gateway identities', stored.data[0].server_id === 'import:qa-source');
    check('Real-data review has no runtime errors', errors.length === 0);
  } finally { await connected.close(); await rm(temporary, { recursive: true, force: true }); }
  check('No browser runtime errors', errors.length === 0);
  check('No remote requests made', external.length === 0);
  const sampledAccessibilityPassed = accessibility.every(screen => screen.violations.length === 0);
  if (sampledAccessibilityPassed) checks.push('No automated WCAG A/AA violations in sampled screens');
  const result = { passed: sampledAccessibilityPassed, checks, errors, accessibility, external_requests: external, native_app_tested: false, python_bridge_via_test_ipc: true, browser_version: browser.version(), viewport_sizes: ['1380x900', '900x740'], fixture_mode: true };
  await writeFile(new URL('browser-check.json', output), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  assert.ok(sampledAccessibilityPassed, 'No automated WCAG A/AA violations in sampled screens');
} catch (failure) {
  await writeFile(new URL('browser-check.json', output), JSON.stringify({ passed: false, checks, errors, accessibility, failure: String(failure), native_app_tested: false }, null, 2) + '\n');
  throw failure;
} finally { await browser.close(); await new Promise(done => server ? server.close(done) : done()); }
