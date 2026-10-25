import test from 'node:test';
import assert from 'node:assert/strict';
import { isObviousPartName, partNumberOrNull } from '../src/services/partNumber.js';

test('obvious part names are not treated as stamped identifiers', () => {
  assert.equal(isObviousPartName('Front Suspension Arm'), true);
  assert.equal(isObviousPartName('oil filter'), true);
  assert.equal(partNumberOrNull('Front Suspension Arm'), null);
});

test('realistic code shapes remain eligible for catalogue lookup', () => {
  for (const code of ['16510-61A31', 'C 25 114', 'TVS-GP-SWFT-F', 'FR7DC+', '4PK690', '0450905273']) {
    assert.equal(isObviousPartName(code), false, code);
    assert.equal(partNumberOrNull(code), code, code);
  }
});

test('blank input is empty, while a single word is left to normal catalogue handling', () => {
  assert.equal(partNumberOrNull('  '), null);
  assert.equal(partNumberOrNull(null), null);
  assert.equal(isObviousPartName('Bosch'), false);
  assert.equal(partNumberOrNull('  BKR6E-11  '), 'BKR6E-11');
});
