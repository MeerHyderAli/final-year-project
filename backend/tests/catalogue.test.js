import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { validateCatalogue } from '../src/store/validateCatalogue.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const read = (name) => JSON.parse(fs.readFileSync(path.join(root, 'data', `${name}.json`), 'utf8'));

test('the seed catalogue satisfies the same validation used for imports', () => {
  const records = Object.fromEntries(['vehicles', 'parts', 'vendors', 'offers'].map((name) => [name, read(name)]));
  assert.deepEqual(validateCatalogue(records), []);
});

test('dangling references and unprovenanced prices are rejected', () => {
  const records = { vehicles: [], parts: [], vendors: [], offers: [{
    id: 'offer-bad', partId: 'missing-part', vendorId: 'missing-vendor', price: 100,
    stockStatus: 'confirmed', sourceType: 'supplier_feed', sourceName: '', updatedAt: 'not-a-date',
  }] };
  const errors = validateCatalogue(records);
  assert.ok(errors.some((error) => error.includes('unknown partId')));
  assert.ok(errors.some((error) => error.includes('unknown vendorId')));
  assert.ok(errors.some((error) => error.includes('sourceName')));
  assert.ok(errors.some((error) => error.includes('updatedAt')));
});
