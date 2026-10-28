/** Resolve and validate the source engine before opening the development app. */
import { existsSync, statSync } from 'node:fs';
import { dirname, isAbsolute, resolve } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const installHelp = 'Use Python 3.11 or newer. From the repository root run:\n  python3 -m venv .venv\n  .venv/bin/python -m pip install -e ".[dev]" -c requirements/core-constraints.txt';

export function developmentPython(root, environment = process.env, platform = process.platform) {
  const selected = environment.DRIFTGUARD_PYTHON || resolve(root, '.venv', platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (!isAbsolute(selected) || !existsSync(selected) || !statSync(selected).isFile()) {
    throw new Error(`The development Python engine is missing or its path is not absolute.\n${installHelp}\nOn Windows use py -3 and .venv\\Scripts\\python.exe instead.\nIf DRIFTGUARD_PYTHON is set, check that it points to this project's virtual environment.`);
  }
  // Do not realpath this executable: resolving a venv symlink loses its prefix.
  return selected;
}

export function verifyDevelopmentPython(python, root) {
  const environment = { ...process.env };
  delete environment.PYTHONHOME;
  delete environment.PYTHONPATH;
  const probe = spawnSync(python, ['-I', '-c',
    'import pathlib,sys,driftguard,driftguard.desktop_bridge,driftguard.harnesses; sys.exit(0 if pathlib.Path(driftguard.__file__).resolve().parent == (pathlib.Path(sys.argv[1])/"src"/"driftguard").resolve() else 3)', root],
    { cwd: root, env: environment, timeout: 15000, maxBuffer: 65536, stdio: 'pipe' });
  if (probe.error || probe.status !== 0) {
    throw new Error(`The selected Python cannot load the current DriftGuard source in isolated mode.\n${installHelp}\nSelected executable: ${python}`);
  }
}

function main() {
  const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const root = resolve(desktop, '..');
  const python = developmentPython(root);
  verifyDevelopmentPython(python, root);
  console.log(`DriftGuard development engine ready: ${python}`);
  if (process.argv.includes('--check')) return;
  const cli = resolve(desktop, 'node_modules/@tauri-apps/cli/tauri.js');
  const child = spawn(process.execPath, [cli, 'dev', ...process.argv.slice(2)], {
    cwd: desktop, stdio: 'inherit', env: { ...process.env, DRIFTGUARD_PYTHON: python },
  });
  child.on('error', () => { console.error('Could not start Tauri. Run npm ci in desktop/ and check the platform prerequisites.'); process.exitCode = 1; });
  child.on('exit', (code, signal) => { process.exitCode = code ?? (signal === 'SIGINT' ? 130 : 1); });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { child.kill(signal); });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
