import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';

const directory = new URL('../../.github/workflows/', import.meta.url);
const workflows = readdirSync(directory).filter(name => /\.ya?ml$/.test(name))
  .map(name => [name, readFileSync(new URL(name, directory), 'utf8')]);

test('every workflow declares an explicit top-level token permission block', () => {
  assert.ok(workflows.length > 0);
  for (const [name, text] of workflows) {
    assert.match(text, /^permissions:/m, `${name} must not inherit the repository default GITHUB_TOKEN scope`);
  }
});

test('third-party actions are pinned to a full commit SHA', () => {
  for (const [name, text] of workflows) {
    for (const [, action] of text.matchAll(/uses:\s*([^\s#]+)/g)) {
      if (action.startsWith('actions/') || action.startsWith('./')) continue;
      assert.match(action, /@[0-9a-f]{40}$/, `${name}: ${action} must be pinned to a commit SHA`);
    }
  }
});

test('workflows avoid privileged pull_request_target triggers', () => {
  for (const [name, text] of workflows) assert.doesNotMatch(text, /pull_request_target|workflow_run/, name);
});
