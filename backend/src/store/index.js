import fs from 'node:fs/promises';
import path from 'node:path';
import { DATA_DIR, config } from '../config.js';

/**
 * Catalogue store.
 *
 * Two drivers behind one interface:
 *   - `json`  (default) reads data/*.json into memory. Zero infrastructure, works offline.
 *   - `mongo` mirrors the same documents into MongoDB when MONGODB_URI is set.
 *
 * The JSON driver is not a toy: it is the same document shape the Mongo collections
 * use, so switching is a config change, not a rewrite.
 */

const COLLECTIONS = ['vehicles', 'parts', 'vendors', 'offers'];

const state = {
  driver: 'json',
  mongoReady: false,
  loadedAt: null,
  counts: {},
};

const tables = Object.fromEntries(COLLECTIONS.map((c) => [c, []]));

async function readJson(name) {
  const file = path.join(DATA_DIR, `${name}.json`);
  const raw = await fs.readFile(file, 'utf8');
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) throw new Error(`${name}.json must contain a JSON array`);
  return parsed;
}

async function tryMongoMirror(records) {
  if (!config.mongoUri) return;
  try {
    const { MongoClient } = await import('mongodb');
    const client = new MongoClient(config.mongoUri, { serverSelectionTimeoutMS: 4000 });
    await client.connect();
    const db = client.db(config.mongoDbName);
    for (const name of COLLECTIONS) {
      const col = db.collection(name);
      await col.createIndex({ id: 1 }, { unique: true });
      if (records[name].length) {
        await col.bulkWrite(
          records[name].map((doc) => ({
            updateOne: { filter: { id: doc.id }, update: { $set: doc }, upsert: true },
          })),
          { ordered: false },
        );
      }
    }
    state.driver = 'json+mongo';
    state.mongoReady = true;
    await client.close();
    console.log(`[store] mirrored catalogue into MongoDB (${config.mongoDbName})`);
  } catch (err) {
    console.warn(`[store] MongoDB mirror skipped: ${err.message}`);
  }
}

export async function loadStore() {
  const records = {};
  for (const name of COLLECTIONS) {
    records[name] = await readJson(name);
    tables[name] = records[name];
    state.counts[name] = records[name].length;
  }
  state.loadedAt = new Date().toISOString();
  await tryMongoMirror(records);
  console.log(
    `[store] driver=${state.driver} ` +
      COLLECTIONS.map((c) => `${c}=${state.counts[c]}`).join(' '),
  );
  return state;
}

export function storeInfo() {
  return { ...state, collections: { ...state.counts } };
}

/* ------------------------------------------------------------------ queries */

export const all = (name) => tables[name];
export const byId = (name, id) => tables[name].find((r) => r.id === id);
export const byIds = (name, ids = []) => ids.map((id) => byId(name, id)).filter(Boolean);

export function findParts({ category, vehicleId, q, limit } = {}) {
  let rows = tables.parts;
  if (category) rows = rows.filter((p) => p.category === category);
  if (vehicleId) rows = rows.filter((p) => p.fitsVehicleIds?.includes(vehicleId));
  if (q) {
    const needle = String(q).toLowerCase().trim();
    rows = rows.filter((p) =>
      [p.name, p.brand, p.partNumber, p.category, ...(p.vehicleClass || [])]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    );
  }
  rows = [...rows].sort((a, b) => a.name.localeCompare(b.name));
  return typeof limit === 'number' ? rows.slice(0, limit) : rows;
}

export function findPartByNumber(partNumber) {
  if (!partNumber) return null;
  const norm = normalizePartNumber(partNumber);
  return (
    tables.parts.find((p) => normalizePartNumber(p.partNumber) === norm) ??
    tables.parts.find((p) => normalizePartNumber(p.partNumber).endsWith(norm) && norm.length >= 6) ??
    null
  );
}

/** Part numbers are written with dashes, dots, slashes and spaces inconsistently. */
export function normalizePartNumber(s) {
  return String(s || '')
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '');
}

export function offersForPart(partId) {
  return tables.offers
    .filter((o) => o.partId === partId)
    .map((o) => ({ ...o, vendor: byId('vendors', o.vendorId) }))
    .filter((o) => o.vendor);
}

export function vehiclesForPart(partId) {
  const part = byId('parts', partId);
  if (!part) return [];
  return byIds('vehicles', part.fitsVehicleIds || []);
}

export function categoryCounts() {
  const counts = {};
  for (const p of tables.parts) counts[p.category] = (counts[p.category] || 0) + 1;
  return counts;
}
