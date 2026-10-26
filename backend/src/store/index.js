import fs from 'node:fs/promises';
import path from 'node:path';
import { DATA_DIR, config } from '../config.js';
import { assertCatalogue, COLLECTIONS } from './validateCatalogue.js';

/**
 * Catalogue store.
 *
 * There are deliberately two visibly different modes:
 *   - json-demo: read the illustrative fixtures in data/*.json. No setup, demo only.
 *   - mongo: read the catalogue from MongoDB. This is the persistent deployment mode.
 *
 * MongoDB is not a mirror for the JSON demo when MONGODB_URI is set: it is the
 * source of truth. If it is configured but unavailable, startup fails instead of
 * silently serving demo prices as though they were live data.
 */

export { COLLECTIONS };

const state = {
  driver: 'json-demo',
  persistent: false,
  mongoReady: false,
  demoData: true,
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

async function readAllJson() {
  const records = {};
  for (const name of COLLECTIONS) records[name] = await readJson(name);
  return records;
}

async function readMongo(seedRecords) {
  const { MongoClient } = await import('mongodb');
  const client = new MongoClient(config.mongoUri, { serverSelectionTimeoutMS: 4000 });
  let seededDemoData = false;

  try {
    await client.connect();
    const db = client.db(config.mongoDbName);
    const records = {};

    for (const name of COLLECTIONS) {
      const col = db.collection(name);
      await col.createIndex({ id: 1 }, { unique: true });

      // Seeding is opt-in. A production database is never populated with demo
      // records just because it happens to be empty.
      if (config.seedDemoData && (await col.countDocuments()) === 0 && seedRecords[name]?.length) {
        await col.insertMany(seedRecords[name]);
        seededDemoData = true;
      }

      // Do not leak Mongo's internal _id through the public catalogue API.
      records[name] = (await col.find({}).toArray()).map(({ _id, ...doc }) => doc);
    }

    state.driver = 'mongo';
    state.persistent = true;
    state.mongoReady = true;
    state.demoData = seededDemoData;
    return records;
  } catch (err) {
    state.driver = 'mongo-unavailable';
    state.persistent = false;
    state.mongoReady = false;
    throw new Error(
      `MongoDB is configured but the catalogue could not be loaded from database "${config.mongoDbName}". ` +
        'Check MONGODB_URI and MongoDB availability; demo JSON fallback is disabled in this mode.',
      { cause: err },
    );
  } finally {
    await client.close().catch(() => {});
  }
}

export async function loadStore() {
  state.driver = config.mongoUri ? 'mongo-unavailable' : 'json-demo';
  state.persistent = false;
  state.mongoReady = false;
  state.demoData = !config.mongoUri;

  // A Mongo-only deployment does not need the JSON fixtures at all. They are read
  // only for the JSON demo or when explicitly requested for first-time seeding.
  const seeds = !config.mongoUri || config.seedDemoData ? await readAllJson() : {};
  const records = config.mongoUri ? await readMongo(seeds) : seeds;
  assertCatalogue(records);

  for (const name of COLLECTIONS) {
    tables[name] = records[name] || [];
    state.counts[name] = tables[name].length;
  }
  state.loadedAt = new Date().toISOString();
  console.log(
    `[store] driver=${state.driver} persistent=${state.persistent} ` +
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
