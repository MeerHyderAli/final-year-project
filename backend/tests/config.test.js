import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const BACKEND_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function timeoutWith(env) {
  const output = execFileSync(
    process.execPath,
    ['--input-type=module', '-e', "import config from './src/config.js'; process.stdout.write(String(config.aiTimeoutMs));"],
    {
      cwd: BACKEND_DIR,
      env: { ...process.env, AI_TIMEOUT_MS: '', ...env },
      encoding: 'utf8',
    },
  );
  return Number(output);
}

test('default Node timeout covers two 30-second provider attempts plus backoff', () => {
  assert.equal(timeoutWith({ VISION_TIMEOUT: '', VISION_RETRIES: '' }), 66500);
});

test('a 120-second provider timeout is not cut off by the old 20-second Node cap', () => {
  assert.equal(timeoutWith({ VISION_TIMEOUT: '120', VISION_RETRIES: '2' }), 246500);
});

test('an explicit Node timeout remains an override', () => {
  assert.equal(timeoutWith({ VISION_TIMEOUT: '120', VISION_RETRIES: '2', AI_TIMEOUT_MS: '90000' }), 90000);
});
