#!/usr/bin/env node
/**
 * Validate and import a catalogue directory into MongoDB.
 *
 *   npm run import:catalogue -- --check-only --dir ../data
 *   MONGODB_URI=mongodb://127.0.0.1:27017 npm run import:catalogue -- --dir ../data
 *
 * Input files are vehicles.json, parts.json, vendors.json and offers.json.
 * Upserts by each document's stable `id`; it never deletes existing records.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { DATA_DIR, config } from '../src/config.js';
import { assertCatalogue, COLLECTIONS } from '../src/store/validateCatalogue.js';

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
}

const directory = path.resolve(option('--dir') || DATA_DIR);
const checkOnly = process.argv.includes('--check-only');

try {
  const records = {};
  for (const collection of COLLECTIONS) {
    const file = path.join(directory, `${collection}.json`);
    records[collection] = JSON.parse(await fs.readFile(file, 'utf8'));
  }

  assertCatalogue(records);
  console.log(`Catalogue valid: ${COLLECTIONS.map((name) => `${name}=${records[name].length}`).join(' ')}`);

  if (checkOnly) process.exit(0);
  if (!config.mongoUri) {
    throw new Error('MONGODB_URI is required for import. Use --check-only to validate without a database.');
  }

  const { MongoClient } = await import('mongodb');
  const client = new MongoClient(config.mongoUri, { serverSelectionTimeoutMS: 5000 });
  try {
    await client.connect();
    const db = client.db(config.mongoDbName);
    for (const collection of COLLECTIONS) {
      const rows = records[collection];
      if (!rows.length) continue;
      const result = await db.collection(collection).bulkWrite(
        rows.map((doc) => ({
          updateOne: { filter: { id: doc.id }, update: { $set: doc }, upsert: true },
        })),
        { ordered: false },
      );
      console.log(
        `${collection}: ${result.upsertedCount} inserted, ${result.modifiedCount} updated, ${result.matchedCount} existing`,
      );
    }
    console.log(`Imported catalogue into MongoDB database "${config.mongoDbName}".`);
  } finally {
    await client.close();
  }
} catch (error) {
  console.error(`Catalogue import failed: ${error.message}`);
  process.exitCode = 1;
}
