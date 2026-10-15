import { byId, findPartByNumber, vehiclesForPart } from '../store/index.js';
import { categoryLabel, isSafetyCritical } from '../taxonomy.js';
import config from '../config.js';

/**
 * Fitment verdict engine.
 *
 * The project's core safety principle lives here: an image prediction narrows the
 * CATEGORY only. Exact fitment is asserted exclusively from catalogue evidence —
 * a part number match, or a make/model/year/engine match against `fitsVehicleIds`.
 *
 * Verdict ladder (strongest evidence first):
 *   confirmed          part number matched a catalogue record
 *   compatible         vehicle matched the catalogue fitment list
 *   needs_part_number  vehicle matched but part is safety-critical -> human check
 *   needs_vehicle_info category known, but nothing to verify fitment against
 *   incompatible       vehicle supplied and it is provably not in the fitment list
 *   unknown_part_number part number supplied but absent from the catalogue
 */

const VERDICT_RANK = {
  confirmed: 6,
  compatible: 5,
  needs_part_number: 4,
  needs_vehicle_info: 3,
  unknown_part_number: 2,
  incompatible: 1,
};

export function checkFitment(input = {}) {
  const { partId, partNumber, category, vehicleId, make, model, year, engine } = input;

  const evidence = [];
  const verifications = [];

  /* ---------------------------------------------------- resolve the part */
  let part = null;
  let matchPath = null;

  if (partNumber) {
    part = findPartByNumber(partNumber);
    if (part) {
      matchPath = 'part_number';
      evidence.push({
        type: 'part_number',
        strength: 'strong',
        detail: `Part number "${partNumber}" matched catalogue record ${part.partNumber} (${part.brand}).`,
        source: 'catalogue',
      });
    } else {
      evidence.push({
        type: 'part_number',
        strength: 'none',
        detail: `Part number "${partNumber}" is not present in the catalogue.`,
        source: 'catalogue',
      });
    }
  } else if (partId) {
    part = byId('parts', partId);
    if (part) {
      matchPath = 'user_selected_part';
      evidence.push({
        type: 'part_selection',
        strength: 'medium',
        detail: `Candidate part chosen from catalogue: ${part.name} (${part.brand} ${part.partNumber}).`,
        source: 'catalogue',
      });
    }
  }

  const effectiveCategory = part?.category || category || null;
  const safetyCritical = isSafetyCritical(effectiveCategory);

  /* --------------------------------------------- resolve the vehicle */
  let vehicle = null;
  let vehicleMatch = null; // 'exact' | 'family' | 'none' | 'unknown'

  if (vehicleId) {
    vehicle = byId('vehicles', vehicleId) || null;
    if (vehicle) vehicleMatch = 'exact';
  } else if (make && model) {
    const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    const nm = norm(make);
    const nmodel = norm(model);
    const all = allVehicles();
    vehicle =
      all.find((v) => norm(v.make) === nm && norm(v.model) === nmodel) ||
      all.find((v) => norm(v.make) === nm && norm(v.model).includes(nmodel)) ||
      all.find((v) => (v.aliases || []).some((a) => norm(a) === nmodel)) ||
      null;
    vehicleMatch = vehicle ? 'family' : 'none';
  }

  if (vehicle) {
    evidence.push({
      type: 'vehicle',
      strength: vehicleMatch === 'exact' ? 'strong' : 'medium',
      detail: `Vehicle resolved to ${vehicle.make} ${vehicle.model} ${vehicle.yearFrom}-${vehicle.yearTo} (${vehicle.engine}).`,
      source: 'vehicle_database',
    });

    if (year != null && year !== '') {
      const y = Number(year);
      const inRange = y >= vehicle.yearFrom && y <= vehicle.yearTo;
      evidence.push({
        type: 'year',
        strength: inRange ? 'strong' : 'negative',
        detail: inRange
          ? `Model year ${y} falls inside the supported range ${vehicle.yearFrom}-${vehicle.yearTo}.`
          : `Model year ${y} is OUTSIDE the supported range ${vehicle.yearFrom}-${vehicle.yearTo}.`,
        source: 'vehicle_database',
      });
      if (!inRange) vehicleMatch = 'none';
    }

    if (engine) {
      const hit = String(vehicle.engine).toLowerCase().includes(String(engine).toLowerCase());
      evidence.push({
        type: 'engine',
        strength: hit ? 'strong' : 'negative',
        detail: hit
          ? `Engine "${engine}" matches catalogue engine "${vehicle.engine}".`
          : `Engine "${engine}" does not match catalogue engine "${vehicle.engine}".`,
        source: 'vehicle_database',
      });
      if (!hit) vehicleMatch = 'none';
    }
  }

  /* ------------------------------------------------------- the verdict */

  if (matchPath === 'part_number' && part && vehicle && vehicleMatch !== 'none') {
    return finish('confirmed', part, vehicle, evidence, verifications, {
      category: effectiveCategory,
      safetyCritical,
      summary: `Part number verified and ${vehicle.make} ${vehicle.model} is listed as compatible.`,
    });
  }

  if (matchPath === 'part_number' && part && !vehicle) {
    const fits = vehiclesForPart(part.id);
    return finish('confirmed', part, null, evidence, verifications, {
      category: effectiveCategory,
      safetyCritical,
      summary:
        `Part number verified against the catalogue. ` +
        `Confirm your vehicle is one of the ${fits.length} listed fitments before purchase.`,
      listedFitments: fits.map((v) => `${v.make} ${v.model} (${v.yearFrom}-${v.yearTo})`),
    });
  }

  if (partNumber && !part) {
    return finish('unknown_part_number', null, vehicle, evidence, verifications, {
      category: effectiveCategory,
      safetyCritical,
      summary:
        'That part number is not in the catalogue. Cross-check the stamped code, or identify by vehicle instead.',
    });
  }

  if (part && vehicle && vehicleMatch !== 'none') {
    const fitsThisVehicle = (part.fitsVehicleIds || []).includes(vehicle.id);
    if (fitsThisVehicle) {
      if (safetyCritical) {
        verifications.push({
          reason: 'safety_critical',
          message:
            `${categoryLabel(effectiveCategory)} is safety-critical. Catalogue fitment is necessary but not sufficient — ` +
            'confirm the part number stamped on the old component or with a qualified mechanic.',
        });
      }
      return finish(safetyCritical ? 'needs_part_number' : 'compatible', part, vehicle, evidence, verifications, {
        category: effectiveCategory,
        safetyCritical,
        summary: safetyCritical
          ? `Catalogue lists this part for ${vehicle.make} ${vehicle.model}. Safety-critical: verify the stamped part number too.`
          : `Catalogue fitment confirms this part is used on ${vehicle.make} ${vehicle.model}.`,
      });
    }

    return finish('incompatible', part, vehicle, evidence, verifications, {
      category: effectiveCategory,
      safetyCritical,
      summary:
        `This part is NOT listed for ${vehicle.make} ${vehicle.model} ${vehicle.yearFrom}-${vehicle.yearTo}. ` +
        'Do not purchase without a physical comparison.',
      // Tell the user what *would* fit instead.
      alternatives: vehiclesForPart(part.id).map((v) => `${v.make} ${v.model} (${v.yearFrom}-${v.yearTo})`),
    });
  }

  if (vehicle && vehicleMatch === 'none') {
    return finish('needs_vehicle_info', part, null, evidence, verifications, {
      category: effectiveCategory,
      safetyCritical,
      summary:
        'That vehicle was not found in the catalogue. Enter the exact variant or search by part number.',
    });
  }

  return finish('needs_vehicle_info', part, vehicle, evidence, verifications, {
    category: effectiveCategory,
    safetyCritical,
    summary: part
      ? `Part identified as ${part.name}. Add your vehicle details or the stamped part number to confirm fitment.`
      : 'Add a part number or full vehicle details before we can assert compatibility.',
  });
}

/* -------------------------------------------------------------- helpers */

function allVehicles() {
  // Imported lazily to keep the module graph acyclic during store boot.
  return vehicleIndex;
}

let vehicleIndex = [];
export function primeVehicleIndex(vehicles) {
  vehicleIndex = vehicles;
}

function finish(verdict, part, vehicle, evidence, verifications, extra = {}) {
  const rank = VERDICT_RANK[verdict] ?? 0;
  return {
    verdict,
    verdictRank: rank,
    confidence: extra.confidence ?? confidenceFor(verdict),
    part: part
      ? {
          id: part.id,
          name: part.name,
          brand: part.brand,
          partNumber: part.partNumber,
          category: part.category,
          condition: part.condition,
          specs: part.specs,
        }
      : null,
    vehicle: vehicle
      ? {
          id: vehicle.id,
          make: vehicle.make,
          model: vehicle.model,
          yearFrom: vehicle.yearFrom,
          yearTo: vehicle.yearTo,
          engine: vehicle.engine,
          vehicleClass: vehicle.vehicleClass,
        }
      : null,
    category: extra.category ?? null,
    categoryLabel: extra.category ? categoryLabel(extra.category) : null,
    safetyCritical: Boolean(extra.safetyCritical),
    evidence,
    verifications,
    summary: extra.summary ?? '',
    listedFitments: extra.listedFitments ?? null,
    alternatives: extra.alternatives ?? null,
    // The UI shows this banner whenever a human should double-check.
    requiresHumanCheck:
      Boolean(extra.safetyCritical) || ['needs_part_number', 'needs_vehicle_info', 'unknown_part_number', 'incompatible'].includes(verdict),
  };
}

function confidenceFor(verdict) {
  switch (verdict) {
    case 'confirmed': return 0.97;
    case 'compatible': return 0.82;
    case 'needs_part_number': return 0.6;
    case 'needs_vehicle_info': return 0.3;
    case 'unknown_part_number': return 0.2;
    case 'incompatible': return 0.1;
    default: return 0.2;
  }
}

export const FITMENT_MIN_CONFIDENCE = config.minConfidence;
