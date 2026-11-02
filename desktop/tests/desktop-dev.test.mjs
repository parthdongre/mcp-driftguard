import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { developmentPython } from '../scripts/desktop-dev.mjs';

test('native dev selects the project venv without resolving its executable symlink', () => {
  const root = mkdtempSync(resolve(tmpdir(), 'driftguard dev '));
  try {
    const bin = resolve(root, '.venv', 'bin');
    mkdirSync(bin, { recursive: true });
    const python = resolve(bin, 'python');
    // Windows symlink creation can require privileges; selection itself needs none.
    if (process.platform === 'win32') writeFileSync(python, 'selection fixture, never executed');
    else symlinkSync(process.execPath, python, 'file');
    assert.equal(developmentPython(root, {}, 'darwin'), python);
    assert.notEqual(python, process.execPath);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('native dev rejects missing or relative overrides before starting the app', () => {
  const root = mkdtempSync(resolve(tmpdir(), 'driftguard-engine-'));
  try {
    assert.throws(() => developmentPython(root, {}, 'darwin'), /python3 -m venv/);
    assert.throws(() => developmentPython(root, { DRIFTGUARD_PYTHON: '.venv/bin/python' }), /not absolute/);
    assert.throws(() => developmentPython(root, { DRIFTGUARD_PYTHON: root }), /missing/);
    const python = resolve(root, '.venv', 'Scripts', 'python.exe');
    mkdirSync(resolve(root, '.venv', 'Scripts'), { recursive: true });
    writeFileSync(python, 'selection fixture, never executed');
    assert.equal(developmentPython(root, {}, 'win32'), python);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
