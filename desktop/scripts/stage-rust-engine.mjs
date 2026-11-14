import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const target = fileURLToPath(new URL('../../rust-version/target/', import.meta.url));
const manifest = fileURLToPath(new URL('../../rust-version/Cargo.toml', import.meta.url));
const build = spawnSync('cargo', [
  'build', '--locked', '--release', '--manifest-path', manifest, '--target-dir', target,
], { stdio: 'inherit' });
if (build.error) throw build.error;
if (build.status !== 0) process.exit(build.status ?? 1);

const name = process.platform === 'win32' ? 'driftguard-rust.exe' : 'driftguard-rust';
const directory = new URL('../build/rust-engine/', import.meta.url);
mkdirSync(directory, { recursive: true });
copyFileSync(new URL(`../../rust-version/target/release/${name}`, import.meta.url), new URL(name, directory));
