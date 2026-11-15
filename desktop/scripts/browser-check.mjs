import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { execFile, spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { delimiter, resolve, sep } from 'node:path';
import { createInterface } from 'node:readline';
import { existsSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
// Prefer the repository virtual environment over whatever `python` is first on PATH.
const projectPython = fileURLToPath(new URL(process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python', import.meta.url));
const testPython = process.env.DRIFTGUARD_TEST_PYTHON ?? (existsSync(projectPython) ? projectPython : 'python');

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
async function auditAccessibility(name, target = page) {
  await target.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const findings = await target.evaluate(async () => {
    const result = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] } });
    return result.violations.map(violation => ({ id: violation.id, impact: violation.impact, description: violation.description, nodes: violation.nodes.map(node => ({ target: node.target, failureSummary: node.failureSummary })) }));
  });
  accessibility.push({ name, violations: findings });
}

async function checkRustConnection(engine) {
  const home = await mkdtemp(resolve(tmpdir(), 'driftguard-rust-ui-'));
  const db = resolve(home, 'review.sqlite3');
  // Detect Codex from a stand-in executable so the check does not depend on an installed CLI.
  const rustBin = resolve(home, 'bin');
  await mkdir(rustBin);
  if (process.platform === 'win32') await writeFile(resolve(rustBin, 'codex.cmd'), '@exit /b 1\r\n');
  else await symlink(process.execPath, resolve(rustBin, 'codex'));
  const environment = { ...process.env, DRIFTGUARD_HARNESS_HOME: home, PATH: rustBin + delimiter + process.env.PATH };
  delete environment.DRIFTGUARD_RUST_PROFILE;
  const bridge = payload => new Promise((done, reject) => {
    const child = execFile(engine, ['--db', db], { env: environment }, (error, stdout) => {
      try { done(JSON.parse(stdout)); } catch (failure) { reject(error ?? failure); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
  const tab = await browser.newPage({ viewport: { width: 1380, height: 900 } });
  tab.on('pageerror', error => errors.push(error.message));
  tab.on('request', request => { if (!request.url().startsWith(base) && !request.url().startsWith('data:')) external.push(request.url()); });
  const toolActivity = [];
  let gateway;
  try {
    assert.ok((await bridge({ action: 'set_approval_mode', mode: 'manual' })).ok);
    await tab.exposeFunction('__qa_rust_bridge', (command, args) => {
      assert.equal(command, 'driftguard_request');
      if (args.request.action === 'tool_activity') toolActivity.push(args.request);
      return bridge(args.request);
    });
    await tab.addInitScript(() => { window.__TAURI_INTERNALS__ = { invoke: (command, args) => window.__qa_rust_bridge(command, args) }; });
    await tab.goto(base);
    await tab.getByRole('heading', { name: 'MCP graph', exact: true }).waitFor();
    await tab.getByRole('region', { name: 'MCP activity log' }).waitFor();
    await tab.getByRole('button', { name: 'MCP connections', exact: true }).click();
    await tab.getByRole('button', { name: 'Connect Codex', exact: true }).click();
    await tab.getByText('Configured Codex. Open a new session to start its MCP gateway.').waitFor();
    const config = await readFile(resolve(home, '.codex/config.toml'), 'utf8');
    assert.match(config, /\[mcp_servers\.driftguard-rust\]/);
    await writeFile(resolve(home, '.codex/config.toml'), config
      + `\n[mcp_servers.notes]\ncommand = ${JSON.stringify(engine)}\nargs = ["sample-server"]\n`);
    await tab.reload();
    await tab.getByRole('heading', { name: 'MCP graph', exact: true }).waitFor();
    await tab.getByRole('button', { name: 'Codex · Review only', exact: true }).waitFor();
    await tab.getByRole('button', { name: 'notes · Review source', exact: true }).waitFor();
    assert.equal((await bridge({ action: 'live_status' })).data.clients, 0);
    check('The Rust desktop discovers existing MCPs at startup without a client session', true);
    await tab.getByRole('button', { name: 'MCP connections', exact: true }).click();
    await tab.getByRole('heading', { name: 'Harness helpers', exact: true }).waitFor();
    const skillDirectory = resolve(home, '.agents/skills/fixture-review');
    await mkdir(skillDirectory, { recursive: true });
    await writeFile(resolve(skillDirectory, 'SKILL.md'), 'Fixture-only helper instructions');
    await tab.getByRole('button', { name: 'Scan helpers', exact: true }).click();
    await tab.getByText('1 harness helper changed', { exact: true }).waitFor();
    await tab.getByRole('button', { name: 'Recent changes', exact: true }).click();
    await tab.getByText('fixture-review', { exact: true }).waitFor();
    await tab.getByText('added', { exact: true }).waitFor();
    assert.equal(await tab.getByText('Fixture-only helper instructions', { exact: true }).count(), 0);
    await tab.getByRole('button', { name: 'Dismiss harness helper notice', exact: true }).click();
    check('Rust desktop records helper changes and surfaces them without revealing file contents', true);
    gateway = spawn(engine, ['--db', db, 'serve', resolve(home, 'driftguard-rust-sample.json'), '--client', 'codex'],
      { env: environment, stdio: ['pipe', 'pipe', 'inherit'] });
    const ended = new Promise(done => gateway.once('close', done));
    const lines = createInterface({ input: gateway.stdout })[Symbol.asyncIterator]();
    const exchange = async message => {
      gateway.stdin.write(JSON.stringify({ jsonrpc: '2.0', ...message }) + '\n');
      if (!message.id) return;
      for (;;) {
        const next = await lines.next();
        assert.ok(!next.done, 'Gateway must stay open until disconnect');
        const reply = JSON.parse(next.value);
        if (reply.id === message.id) return reply;
      }
    };
    assert.ok((await exchange({ id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25' } })).result);
    await exchange({ method: 'notifications/initialized' });
    assert.deepEqual((await exchange({ id: 2, method: 'tools/list' })).result.tools, []);
    await tab.getByRole('button', { name: 'Review tools', exact: true }).click();
    await tab.getByRole('button', { name: 'read_sample · gateway:codex:driftguard-sample', exact: true }).click();
    await tab.getByRole('heading', { name: 'read_sample', exact: true }).waitFor();
    await tab.getByText('Initial baseline', { exact: true }).waitFor();
    await tab.getByRole('button', { name: 'Approve version', exact: true }).click();
    await tab.getByRole('button', { name: 'Approve reviewed version', exact: true }).click();
    await tab.getByText('Decision saved: Approved.').waitFor();
    await tab.getByRole('button', { name: 'Settings', exact: true }).click();
    await tab.getByText('MCP monitoring and graph', { exact: true }).click();
    await tab.getByRole('spinbutton', { name: 'Recently used gateway check interval (seconds)' }).fill('5');
    await tab.getByRole('button', { name: 'Save monitoring settings', exact: true }).click();
    await tab.getByText('Monitoring settings saved.', { exact: true }).waitFor();
    await auditAccessibility('mcp-monitoring-settings', tab);
    assert.equal((await bridge({ action: 'monitoring_settings' })).data.active_seconds, 5);

    assert.equal((await exchange({ id: 3, method: 'tools/call', params: { name: 'read_sample', arguments: {} } }))
      .result.content[0].text, 'DriftGuard live integration check\n');
    await tab.getByRole('button', { name: 'MCP graph', exact: true }).click();
    const log = tab.getByRole('region', { name: 'MCP activity log' });
    const graph = tab.getByRole('region', { name: 'Connection graph', exact: true });
    const catalogAfterCall = (await bridge({ action: 'mcp_activity' })).data
      .find(event => event.event === 'catalog_observed' && event.server_id === 'gateway:codex:driftguard-sample');
    await log.getByText('Call completed', { exact: true }).waitFor();
    await graph.locator('button[data-tone="completed"]').filter({ hasText: 'read_sample' }).waitFor();
    await graph.getByText(/Last catalog check .* · 5 s checks/).waitFor();
    await log.getByText('Catalog checked', { exact: true }).first().waitFor();
    await log.getByRole('checkbox', { name: 'Show successful checks' }).uncheck();
    await log.getByText('Call completed', { exact: true }).waitFor();
    assert.equal(await log.getByText('Catalog checked', { exact: true }).count(), 0);
    const refreshDeadline = Date.now() + 9000;
    let checkedAutomatically = false;
    while (Date.now() < refreshDeadline) {
      const { data: events } = await bridge({ action: 'mcp_activity' });
      if (events.some(event => event.event === 'catalog_observed' &&
        event.server_id === catalogAfterCall.server_id && event.id > catalogAfterCall.id)) {
        checkedAutomatically = true;
        break;
      }
      await new Promise(done => setTimeout(done, 250));
    }
    check('A live tool call highlights its graph route and the active gateway rereads the saved check interval', checkedAutomatically);
    await tab.getByRole('heading', { name: 'Sentinel · Time Machine', exact: true }).waitFor();
    await tab.getByRole('combobox', { name: 'Managed route' }).selectOption('gateway:codex:driftguard-sample');
    await tab.getByRole('button', { name: 'Stop managed server', exact: true }).click();
    await tab.getByRole('button', { name: 'Stop server', exact: true }).click();
    await tab.getByRole('button', { name: 'Resume managed server', exact: true }).waitFor();
    assert.deepEqual((await exchange({ id: 31, method: 'tools/list' })).result.tools, []);
    assert.equal((await exchange({ id: 32, method: 'tools/call', params: { name: 'read_sample', arguments: {} } }))
      .error.data.reason, 'server_stopped');
    await log.getByText('Call blocked', { exact: true }).waitFor();
    check('The MCP activity log keeps policy outcomes visible when successful checks are hidden', true);
    const recorder = tab.getByRole('region', { name: 'Sentinel · Time Machine' });
    await recorder.getByRole('button', { name: /read_sample.*blocked/ }).click();
    await recorder.getByText('The server was stopped across managed routes.', { exact: true }).waitFor();
    await recorder.getByText('Last successful call', { exact: false }).waitFor();
    await recorder.getByText('Policy comparison', { exact: true }).click();
    assert.equal(await recorder.getByText('The server was stopped across managed routes.', { exact: true }).count(), 2);
    await auditAccessibility('sentinel-time-machine', tab);
    await tab.screenshot({ path: fileURLToPath(new URL('sentinel-time-machine.png', output)), fullPage: true });
    await tab.getByRole('button', { name: 'Resume managed server', exact: true }).click();
    await tab.getByRole('button', { name: 'Resume server', exact: true }).click();
    await tab.getByRole('button', { name: 'Stop managed server', exact: true }).waitFor();
    assert.equal((await exchange({ id: 33, method: 'tools/list' })).result.tools.length, 1);
    check('Sentinel stops real gateway calls, records the cause, and restores eligible tools', true);
    await tab.getByRole('button', { name: 'Security review', exact: true }).click();
    await tab.getByRole('button', { name: 'read_sample · gateway:codex:driftguard-sample', exact: true }).click();
    await tab.getByRole('button', { name: 'Block across harnesses', exact: true }).click();
    await tab.getByRole('button', { name: 'Unblock all harnesses', exact: true }).waitFor();
    assert.deepEqual((await exchange({ id: 4, method: 'tools/list' })).result.tools, []);
    assert.ok((await exchange({ id: 5, method: 'tools/call', params: { name: 'read_sample', arguments: {} } })).error);
    await tab.getByRole('button', { name: 'MCP graph', exact: true }).click();
    await tab.getByRole('button', { name: 'Codex · Active', exact: true }).click();
    await tab.getByRole('button', { name: 'read_sample · Blocked · Codex', exact: true }).click();
    await tab.getByRole('heading', { name: 'read_sample', exact: true }).waitFor();
    await tab.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await tab.getByRole('button', { name: 'Reset zoom', exact: true }).click();
    await tab.getByRole('combobox', { name: 'Tool status', exact: true }).selectOption('needs_review');
    await tab.getByText('No tools match these filters.', { exact: true }).waitFor();
    await tab.getByRole('combobox', { name: 'Tool status', exact: true }).selectOption('blocked');
    await tab.getByRole('button', { name: 'read_sample · Blocked · Codex', exact: true }).click();
    await auditAccessibility('rust-mcp-graph', tab);
    await tab.screenshot({ path: fileURLToPath(new URL('mcp-graph-rust.png', output)) });
    await tab.getByRole('button', { name: 'View tool activity', exact: true }).click();
    await tab.getByText('read_sample · gateway:codex:driftguard-sample', { exact: true }).first().waitFor();
    await tab.getByRole('heading', { name: 'gateway call blocked', exact: true }).first().waitFor();
    for (let wait = 0; wait < 40 && !toolActivity.length; wait++) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert.ok(toolActivity.some(request => request.server_id === 'gateway:codex:driftguard-sample'
      && request.tool_name === 'read_sample'));
    await tab.getByRole('button', { name: 'Clear tool filter', exact: true }).click();
    await tab.getByRole('button', { name: 'MCP graph', exact: true }).click();
    await tab.getByRole('button', { name: 'read_sample · Blocked · Codex', exact: true }).click();
    await tab.getByRole('button', { name: 'View version history', exact: true }).click();
    await tab.getByRole('button', { name: 'Version history', exact: true, pressed: true }).waitFor();
    await tab.getByRole('button', { name: 'Current review', exact: true }).click();
    await tab.getByRole('button', { name: 'Unblock all harnesses', exact: true }).click();
    await tab.getByText('Tool unblocked. Review its current version.').waitFor();
    assert.deepEqual((await exchange({ id: 6, method: 'tools/list' })).result.tools, []);
    await tab.getByRole('button', { name: 'MCP connections', exact: true }).click();
    await auditAccessibility('rust-harness-setup', tab);
    await tab.getByRole('button', { name: 'Disconnect Codex', exact: true }).click();
    await tab.getByText(/Removed Codex's managed MCP configuration\./).waitFor();
    await ended;
    assert.equal((await bridge({ action: 'live_status' })).data.running, false);
    await tab.getByRole('button', { name: 'MCP graph', exact: true }).click();
    await tab.getByRole('button', { name: 'Codex · Offline', exact: true }).waitFor();
    assert.ok((await bridge({ action: 'import_definitions', server_id: 'large-catalog', identity: 'fixture',
      tools: Array.from({ length: 350 }, (_, index) => ({
        name: `read_record_${String(index).padStart(3, '0')}`, inputSchema: { type: 'object' },
      })),
    })).ok);
    await tab.getByRole('combobox', { name: 'Server', exact: true }).selectOption({ label: 'large-catalog (review source)' });
    await tab.getByText('350 tools', { exact: true }).waitFor();
    assert.equal(await tab.getByRole('button', { name: /read_record_.* · Needs review · Review only/ }).count(), 12);
    await tab.getByRole('button', { name: 'Next', exact: true }).click();
    await tab.getByRole('button', { name: 'read_record_012 · Needs review · Review only', exact: true }).waitFor();
    await tab.getByRole('searchbox', { name: 'Find a tool in this server', exact: true }).fill('349');
    await tab.getByRole('button', { name: 'read_record_349 · Needs review · Review only', exact: true }).waitFor();
    await tab.setViewportSize({ width: 800, height: 780 });
    assert.ok(await tab.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    check('The Rust graph searches a 350-tool catalog and keeps scrolling inside the graph', true);
    if (process.env.DRIFTGUARD_TEST_PYTHON) {
      const fixtures = [
        ['github.read_issue', 'GitHub'], ['canva.read_design', 'Canva'], ['plugin_creator.inspect', 'Plugin Creator'],
      ];
      await new Promise((done, reject) => execFile(process.env.DRIFTGUARD_TEST_PYTHON, ['-c', [
        'import hashlib,json,sqlite3,sys',
        'source="harness:codex:codex_apps"',
        'with sqlite3.connect(sys.argv[1]) as db:',
        ' db.execute("INSERT INTO sources VALUES (?,?)", (source,"fixture"))',
        ' for name,label in json.loads(sys.argv[2]):',
        '  definition=json.dumps({"name":name,"inputSchema":{"type":"object"},"_meta":{"connector_name":label}})',
        '  digest=hashlib.sha256(definition.encode()).hexdigest()',
        '  db.execute("INSERT INTO tools VALUES (?,?,?,?,1,?,CURRENT_TIMESTAMP,1)", (source,name,digest,definition,"pending"))',
      ].join('\n'), db, JSON.stringify(fixtures)], error => error ? reject(error) : done()));
      await tab.setViewportSize({ width: 1380, height: 900 });
      await tab.getByRole('button', { name: 'Refresh local workspace', exact: true }).click();
      await tab.getByRole('button', { name: 'MCP connections', exact: true }).click();
      await tab.getByRole('button', { name: 'Review Canva tools', exact: true }).waitFor();
      await tab.getByRole('button', { name: 'Review Plugin Creator tools', exact: true }).waitFor();
      await tab.getByRole('button', { name: 'Review GitHub tools', exact: true }).click();
      await tab.getByRole('region', { name: 'GitHub', exact: true }).waitFor();
      await tab.getByRole('heading', { name: 'github.read_issue', exact: true }).waitFor();
      assert.equal(await tab.getByRole('region', { name: 'Canva', exact: true }).count(), 0);
      await tab.getByRole('button', { name: 'MCP graph', exact: true }).click();
      await tab.getByRole('combobox', { name: 'Server', exact: true }).selectOption({ label: 'Canva (review source)' });
      await tab.getByRole('button', { name: 'canva.read_design · Needs review · Codex', exact: true }).click();
      await tab.getByRole('button', { name: 'Open security review', exact: true }).click();
      await tab.getByRole('heading', { name: 'canva.read_design', exact: true }).waitFor();
      check('Codex connector groups are named and link to their original tool in connections, review, and graph', true);
    }
    await tab.getByRole('button', { name: 'Settings', exact: true }).click();
    await tab.getByText('MCP monitoring and graph', { exact: true }).click();
    await tab.getByRole('combobox', { name: 'Startup view', exact: true }).selectOption('overview');
    await tab.reload();
    await tab.getByRole('heading', { name: 'Overview', exact: true }).waitFor();
    await tab.getByRole('button', { name: 'Settings', exact: true }).click();
    await tab.getByText('MCP monitoring and graph', { exact: true }).click();
    assert.equal(await tab.getByRole('combobox', { name: 'Startup view', exact: true }).inputValue(), 'overview');
    assert.equal(await tab.getByRole('spinbutton', { name: 'Recently used gateway check interval (seconds)' }).inputValue(), '5');
    check('Graph startup and engine check preferences persist across app reloads', true);
    check('Rust graph links blocked tools to exact-route activity and version history', true);
    check('Rust harness UI configures, approves, blocks, unblocks, and disconnects a live MCP session', true);
  } finally {
    gateway?.kill();
    await tab.close();
    await rm(home, { recursive: true, force: true });
  }
}
try {
  await page.goto(base);
  await page.getByRole('heading', { name: 'Overview', exact: true }).waitFor();
  check('Browser preview explicitly has no protected connections', await page.getByText(/Native gateway unavailable/).isVisible());
  await page.getByRole('button', { name: 'MCP graph', exact: true }).click();
  await page.getByRole('heading', { name: 'No MCP connections to map yet', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Explore guided demo', exact: true }).last().click();
  await page.getByText('Guided demo · recorded definitions', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Recorded definitions', exact: false }).first().waitFor();
  await page.getByRole('button', { name: 'Exit demo', exact: true }).click();
  await page.screenshot({ path: fileURLToPath(new URL('overview-empty.png', output)), fullPage: true });
  await page.getByRole('button', { name: /Explore guided demo/ }).first().click();
  await page.getByRole('button', { name: /export_report/ }).first().waitFor();
  check('Guided fixture is explicitly isolated', await page.getByText(/Isolated research fixture/).isVisible());
  await page.screenshot({ path: fileURLToPath(new URL('overview-fixture.png', output)), fullPage: true });
  await page.getByRole('button', { name: /export_report/ }).first().click();
  await page.getByRole('heading', { name: 'export_report', exact: true }).waitFor();
  check('Reviewable benign fixture allows review', await page.getByRole('button', { name: 'Approve version', exact: true }).isEnabled());
  await page.screenshot({ path: fileURLToPath(new URL('security-review.png', output)), fullPage: true });
  await auditAccessibility('security-review-light');
  await page.getByRole('button', { name: 'Approve version', exact: true }).click();
  await page.getByRole('dialog').waitFor();
  check('Approval requires an explicit exact-version confirmation', await page.getByRole('heading', { name: 'Approve this exact version?' }).isVisible());
  await page.keyboard.press('Escape');
  check('Escape closes modal', await page.getByRole('dialog').count() === 0);
  await page.getByRole('button', { name: 'Quarantine', exact: true }).click();
  await page.getByRole('button', { name: 'Release to review', exact: true }).waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('Approve version') && button.disabled));
  check('Quarantined exact version cannot be approved', await page.getByRole('button', { name: 'Approve version', exact: true }).isDisabled());
  await page.getByRole('button', { name: 'Release to review', exact: true }).click();
  await page.getByText('Quarantine released. This version needs review.').waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('Approve version') && !button.disabled));
  check('Releasing quarantine returns the tool to review', await page.getByRole('button', { name: 'Approve version', exact: true }).isEnabled());
  await page.getByRole('button', { name: /search_repository/ }).click();
  await page.getByRole('button', { name: 'Version history', exact: true }).click();
  await page.getByRole('heading', { name: 'Cumulative change signal', exact: true }).click();
  await page.getByRole('img', { name: /CUSUM over/ }).waitFor();
  check('Temporal evidence chart renders actual recorded metrics', await page.getByRole('img', { name: /CUSUM over/ }).isVisible());
  check('Version history stays in Security review with the same selected tool',
    await page.getByRole('heading', { name: 'Security review', exact: true }).isVisible()
    && await page.getByRole('button', { name: /search_repository/ }).getAttribute('aria-pressed') === 'true');
  await page.screenshot({ path: fileURLToPath(new URL('tool-evolution.png', output)), fullPage: true });
  await auditAccessibility('tool-evolution-light');
  await page.getByRole('button', { name: 'Current review', exact: true }).click();
  await page.getByRole('heading', { name: 'search_repository', exact: true }).waitFor();
  await page.getByRole('combobox', { name: 'Inferred capability' }).selectOption('operations:write');
  check('Capability filter selects matching tools from the catalog', await page.getByRole('button', { name: /export_report/ }).isVisible()
    && await page.getByRole('button', { name: /search_repository/ }).count() === 0);
  await page.getByRole('combobox', { name: 'Review status' }).selectOption('approved');
  await page.getByRole('heading', { name: 'No matching tools', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  check('Clear filters restores the catalog and its source groups',
    await page.getByRole('region', { name: 'fixture-repository' }).isVisible());
  await page.getByRole('button', { name: 'Research laboratory', exact: true }).click();
  await page.getByRole('heading', { name: 'Independent annotation workspace', exact: true }).click();
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
  await page.getByRole('heading', { name: 'Appearance', exact: true }).click();
  await page.getByRole('heading', { name: 'Color theme', exact: true }).click();
  await page.getByRole('button', { name: 'Dark', exact: true }).click();
  await page.screenshot({ path: fileURLToPath(new URL('settings-dark.png', output)), fullPage: true });
  await auditAccessibility('settings-dark');
  await page.getByRole('button', { name: 'Light', exact: true }).click();
  await page.setViewportSize({ width: 900, height: 740 });
  await page.getByRole('button', { name: 'Overview', exact: true }).click();
  check('Minimum-width layout has no document overflow', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: fileURLToPath(new URL('overview-narrow-light.png', output)), fullPage: true });
  await auditAccessibility('overview-narrow-light');
  await page.getByRole('button', { name: 'Exit demo', exact: true }).click();
  await page.getByRole('button', { name: 'MCP connections', exact: true }).click();
  check('Connections open directly to coding harnesses', await page.getByRole('heading', { name: 'Coding harnesses', exact: true }).isVisible());
  check('Browser preview explains why client configuration requires desktop', await page.getByText(/Open the desktop app to detect and connect coding harnesses/).isVisible());
  check('Hosted apps and manual setup controls are absent', await page.locator('main input:visible, main textarea:visible').count() === 0
    && await page.getByRole('button', { name: 'Import definitions', exact: true }).count() === 0);
  await auditAccessibility('connection-setup');
  await page.screenshot({ path: fileURLToPath(new URL('connections-preview.png', output)), fullPage: true });
  // Test-only IPC: renderer -> actual Python module -> disposable gateway and SQLite.
  const temporary = await mkdtemp(resolve(tmpdir(), 'driftguard-ui-'));
  const statePath = resolve(temporary, 'guard.sqlite3');
  const testBin = resolve(temporary, 'bin');
  await mkdir(testBin);
  if (process.platform === 'win32') {
    await writeFile(resolve(testBin, 'codex.cmd'), '@exit /b 1\r\n');
  } else {
    // This browser suite detects Codex but never runs a model. Vendor CLI smoke
    // tests independently exercise real Codex discovery and MCP transport.
    await symlink(process.execPath, resolve(testBin, 'codex'));
  }
  let queue = Promise.resolve();
  const runPython = payload => {
    const operation = queue.then(async () => {
      const child = execFile(testPython, ['-m', 'driftguard.desktop_bridge', '--db', statePath], { maxBuffer: 16 * 1024 * 1024, timeout: payload.action === 'live_connect' ? 180000 : 45000, env: { ...process.env, CODEX_HOME: resolve(temporary, 'codex-home'), PATH: testBin + delimiter + process.env.PATH } });
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
    await connected.getByRole('button', { name: 'Set up MCP', exact: true }).click();
    await connected.getByRole('button', { name: 'Connect Codex', exact: true }).waitFor();
    check('Detected Codex and all supported client names render automatically', await connected.getByText('Antigravity', { exact: true }).isVisible()
      && await connected.getByText('OpenCode', { exact: true }).isVisible()
      && await connected.getByText('Claude Code', { exact: true }).isVisible());
    await connected.getByRole('button', { name: 'Connect Codex', exact: true }).click();
    await connected.getByRole('button', { name: 'Review sample tool', exact: true }).waitFor({ timeout: 180000 });
    const prepared = await runPython({ action: 'live_status' });
    check('Connect starts a shared gateway and writes Codex TOML without extra input',
      prepared.ok && prepared.data.running && prepared.data.installed && !prepared.data.verified);
    const codexSettings = await readFile(resolve(temporary, 'codex-home/config.toml'), 'utf8');
    check('The managed TOML contains the fixed Filesystem connection', codexSettings.includes('[mcp_servers."driftguard-filesystem"]'));
    await connected.getByRole('button', { name: 'Review sample tool', exact: true }).click();
    await connected.getByRole('heading', { name: 'read_text_file', exact: true }).waitFor();
    await connected.getByRole('button', { name: 'Approve version', exact: true }).click();
    await connected.getByRole('button', { name: 'Approve reviewed version', exact: true }).click();
    await connected.getByRole('button', { name: 'MCP connections', exact: true }).click();
    await connected.getByText('Sample read verified', { exact: true }).waitFor({ timeout: 45000 });
    const verified = await runPython({ action: 'live_status' });
    check('Approval triggers an actual official Filesystem read without a second button', verified.ok && verified.data.verified);
    await auditAccessibility('managed-harness-setup', connected);
    await connected.screenshot({ path: fileURLToPath(new URL('managed-harness-setup.png', output)), fullPage: true });
    await connected.getByRole('button', { name: 'Security activity', exact: true }).click();
    await connected.getByRole('heading', { name: 'call completed', exact: true }).first().waitFor();
    check('Gateway calls appear automatically in Security activity', await connected.getByRole('heading', { name: 'call completed', exact: true }).first().isVisible());
    await connected.getByRole('button', { name: 'MCP connections', exact: true }).click();
    await connected.getByRole('button', { name: 'Disconnect Codex', exact: true }).click();
    await connected.getByText('Disconnected. Previous Codex settings restored.', { exact: true }).waitFor();
    const disconnected = await runPython({ action: 'live_status' });
    check('Disconnect removes the managed entry and stops the gateway', disconnected.ok && !disconnected.data.installed && !disconnected.data.running);

    for (const [name, offset] of [['sample-repositories', 0], ['sample-databases', 350]]) {
      const tools = Array.from({ length: 350 }, (_, index) => ({
        name: `read_record_${index + offset}`, description: `Read a record from ${name}.`, inputSchema: { type: 'object' },
      }));
      assert.ok((await runPython({ action: 'import_definitions', server_id: name, identity: name, tools })).ok);
    }
    await connected.getByRole('button', { name: 'Refresh local workspace' }).click();
    await connected.getByRole('button', { name: 'Security review', exact: true }).click();
    await connected.getByRole('region', { name: 'sample-databases' }).waitFor();
    await connected.getByRole('heading', { name: 'read_text_file', exact: true }).waitFor();
    const dimensions = () => connected.evaluate(() => {
      const catalog = document.querySelector('.catalog-scroll');
      const sidebar = document.querySelector('.review-sidebar');
      const review = document.querySelector('.review-workspace');
      return { catalog: sidebar.getBoundingClientRect().bottom, review: review.getBoundingClientRect().bottom,
        scrollTop: catalog.scrollTop, scrollHeight: catalog.scrollHeight, clientHeight: catalog.clientHeight,
        pageTop: window.scrollY, shellTop: document.querySelector('.main-shell').scrollTop };
    });
    await connected.locator('.catalog-scroll').hover({ position: { x: 50, y: 100 } });
    const before = await dimensions();
    check('700 tools keep the catalog and review panes aligned', Math.abs(before.catalog - before.review) < 1
      && before.scrollHeight > before.clientHeight * 10 && before.review <= 900);
    await connected.mouse.wheel(0, 600);
    await connected.waitForFunction(() => document.querySelector('.catalog-scroll').scrollTop > 0);
    const after = await dimensions();
    check('Scrolling the catalog does not move the review pane or page', Math.abs(after.pageTop - before.pageTop) < 1
      && Math.abs(after.shellTop - before.shellTop) < 1
      && Math.abs(after.review - before.review) < 1);
    await connected.screenshot({ path: fileURLToPath(new URL('review-catalog-700.png', output)), fullPage: true });
    await connected.getByRole('combobox', { name: 'MCP source' }).selectOption('import:sample-databases');
    check('Source filter narrows the catalog to one MCP server', await connected.getByRole('region', { name: 'sample-databases' }).isVisible()
      && await connected.getByRole('region', { name: 'sample-repositories' }).count() === 0);
    const search = connected.getByRole('textbox', { name: 'Search tools or sources' });
    await search.fill('sample-databases 699');
    await connected.getByRole('heading', { name: 'read_record_699', exact: true }).waitFor();
    check('Catalog search combines source and tool name', await connected.getByText(/1 of .* tools/).isVisible());
    const updatedCatalog = Array.from({ length: 350 }, (_, index) => ({
      name: `read_record_${index + 350}`,
      description: index === 349 ? 'Read a selected database record.' : 'Read a record from sample-databases.',
      inputSchema: { type: 'object' },
    }));
    assert.ok((await runPython({ action: 'import_definitions', server_id: 'sample-databases',
      identity: 'sample-databases', tools: updatedCatalog })).ok);
    await connected.getByRole('heading', { name: 'read_record_699', exact: true }).waitFor();
    await connected.getByRole('button', { name: 'Version history', exact: true }).click();
    await connected.getByRole('button', { name: 'Version 2', exact: true }).waitFor();
    assert.equal(await connected.getByText('Tool definition changed · read_record_699').count(), 0);
    check('A persisted description change appears in history without a notification',
      await connected.getByRole('button', { name: 'Version 2', exact: true }).isVisible());
    check('Real-data review has no runtime errors', errors.length === 0);
  } finally { await runPython({ action: 'live_disconnect' }).catch(() => {}); await connected.close(); await rm(temporary, { recursive: true, force: true }); }
  if (process.env.DRIFTGUARD_TEST_RUST_ENGINE) await checkRustConnection(process.env.DRIFTGUARD_TEST_RUST_ENGINE);
  check('No browser runtime errors', errors.length === 0);
  check('No remote requests made', external.length === 0);
  const sampledAccessibilityPassed = accessibility.every(screen => screen.violations.length === 0);
  if (sampledAccessibilityPassed) checks.push('No automated WCAG A/AA violations in sampled screens');
  const result = { passed: sampledAccessibilityPassed, checks, errors, accessibility, external_requests: external, native_app_tested: false, installed_harnesses_tested: false, python_bridge_via_test_ipc: true, rust_bridge_via_test_ipc: Boolean(process.env.DRIFTGUARD_TEST_RUST_ENGINE), browser_version: browser.version(), viewport_sizes: ['1380x900', '900x740'], fixture_mode: true };
  await writeFile(new URL('browser-check.json', output), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
  assert.ok(sampledAccessibilityPassed, 'No automated WCAG A/AA violations in sampled screens');
} catch (failure) {
  await writeFile(new URL('browser-check.json', output), JSON.stringify({ passed: false, checks, errors, accessibility, failure: String(failure), native_app_tested: false }, null, 2) + '\n');
  throw failure;
} finally { await browser.close(); await new Promise(done => server ? server.close(done) : done()); }
