import { CATEGORY_KEYS } from '../taxonomy.js';

export const STOCK_STATUSES = ['confirmed', 'likely', 'unconfirmed', 'out_of_stock'];
export const SOURCE_TYPES = ['supplier_feed', 'shop_submitted', 'authorised_catalogue', 'manual_verified'];
export const COLLECTIONS = ['vehicles', 'parts', 'vendors', 'offers'];

/**
 * Validate the catalogue before it becomes the source of truth.
 * Returns human-readable errors rather than silently dropping bad records.
 */
export function validateCatalogue(records) {
  const errors = [];
  const ids = {};

  for (const collection of COLLECTIONS) {
    const rows = records?.[collection];
    if (!Array.isArray(rows)) {
      errors.push(`${collection}: expected a JSON array`);
      continue;
    }
    ids[collection] = new Set();
    rows.forEach((row, index) => {
      if (!row || typeof row !== 'object' || Array.isArray(row)) {
        errors.push(`${collection}[${index}]: expected an object`);
        return;
      }
      if (!row.id || typeof row.id !== 'string') {
        errors.push(`${collection}[${index}]: string id is required`);
      } else if (ids[collection].has(row.id)) {
        errors.push(`${collection}[${index}]: duplicate id ${row.id}`);
      } else {
        ids[collection].add(row.id);
      }
    });
  }

  for (const [index, part] of (records?.parts || []).entries()) {
    if (!part || typeof part !== 'object') continue;
    for (const field of ['name', 'brand', 'partNumber', 'category']) {
      if (!part[field]) errors.push(`parts[${index}]: ${field} is required`);
    }
    if (part.category && !CATEGORY_KEYS.includes(part.category)) {
      errors.push(`parts[${index}]: unknown category ${part.category}; update the shared taxonomy first`);
    }
    if (!Array.isArray(part.fitsVehicleIds)) {
      errors.push(`parts[${index}] (${part.id || 'no id'}): fitsVehicleIds must be an array`);
    } else {
      for (const vehicleId of part.fitsVehicleIds) {
        if (!ids.vehicles?.has(vehicleId)) {
          errors.push(`parts[${index}] (${part.id || 'no id'}): unknown vehicle ${vehicleId}`);
        }
      }
    }
  }

  for (const [index, vehicle] of (records?.vehicles || []).entries()) {
    if (!vehicle || typeof vehicle !== 'object') continue;
    for (const field of ['make', 'model', 'engine']) {
      if (!vehicle[field]) errors.push(`vehicles[${index}]: ${field} is required`);
    }
    if (!Number.isInteger(vehicle.yearFrom) || !Number.isInteger(vehicle.yearTo) || vehicle.yearFrom > vehicle.yearTo) {
      errors.push(`vehicles[${index}] (${vehicle.id || 'no id'}): invalid yearFrom/yearTo`);
    }
  }

  for (const [index, vendor] of (records?.vendors || []).entries()) {
    if (!vendor || typeof vendor !== 'object') continue;
    for (const field of ['name', 'city']) {
      if (!vendor[field]) errors.push(`vendors[${index}]: ${field} is required`);
    }
    if (!Number.isFinite(vendor.lat) || !Number.isFinite(vendor.lng)) {
      errors.push(`vendors[${index}] (${vendor.id || 'no id'}): finite lat/lng are required for nearby search`);
    }
  }

  for (const [index, offer] of (records?.offers || []).entries()) {
    if (!offer || typeof offer !== 'object') continue;
    if (!ids.parts?.has(offer.partId)) errors.push(`offers[${index}]: unknown partId ${offer.partId}`);
    if (!ids.vendors?.has(offer.vendorId)) errors.push(`offers[${index}]: unknown vendorId ${offer.vendorId}`);
    if (!Number.isFinite(offer.price) || offer.price < 0) errors.push(`offers[${index}]: price must be a non-negative number`);
    if (!STOCK_STATUSES.includes(offer.stockStatus)) errors.push(`offers[${index}]: invalid stockStatus ${offer.stockStatus}`);
    if (!SOURCE_TYPES.includes(offer.sourceType)) errors.push(`offers[${index}]: invalid sourceType ${offer.sourceType}`);
    if (!offer.sourceName) errors.push(`offers[${index}]: sourceName is required`);
    if (!offer.updatedAt || !Number.isFinite(Date.parse(offer.updatedAt))) {
      errors.push(`offers[${index}]: updatedAt must be an ISO date/time`);
    }
  }

  return errors;
}

export function assertCatalogue(records) {
  const errors = validateCatalogue(records);
  if (errors.length) {
    const shown = errors.slice(0, 30).join('\n');
    const more = errors.length > 30 ? `\n… and ${errors.length - 30} more` : '';
    throw new Error(`Catalogue validation failed (${errors.length} errors):\n${shown}${more}`);
  }
  return records;
}
