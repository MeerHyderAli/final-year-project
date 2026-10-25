import { Router } from 'express';
import {
  all,
  byId,
  categoryCounts,
  findPartByNumber,
  findParts,
  offersForPart,
  storeInfo,
  vehiclesForPart,
} from '../store/index.js';
import { CATEGORIES, VEHICLE_CLASSES } from '../taxonomy.js';
import { isObviousPartName, partNameInputMessage } from '../services/partNumber.js';

const router = Router();

router.get('/meta', (_req, res) => {
  res.json({
    taxonomy: { categories: CATEGORIES, vehicleClasses: VEHICLE_CLASSES },
    categoryCounts: categoryCounts(),
    store: storeInfo(),
  });
});

router.get('/vehicles', (req, res) => {
  let rows = all('vehicles');
  const { q, vehicleClass, make } = req.query;
  if (vehicleClass) rows = rows.filter((v) => v.vehicleClass === vehicleClass);
  if (make) rows = rows.filter((v) => v.make.toLowerCase() === String(make).toLowerCase());
  if (q) {
    const n = String(q).toLowerCase();
    rows = rows.filter((v) =>
      [v.make, v.model, v.engine, ...(v.aliases || [])].join(' ').toLowerCase().includes(n),
    );
  }
  res.json({
    count: rows.length,
    makes: [...new Set(all('vehicles').map((v) => v.make))].sort(),
    results: rows,
  });
});

router.get('/vehicles/:id', (req, res) => {
  const vehicle = byId('vehicles', req.params.id);
  if (!vehicle) return res.status(404).json({ error: 'vehicle_not_found', id: req.params.id });
  const parts = findParts({ vehicleId: vehicle.id });
  res.json({
    vehicle,
    compatibleParts: parts.map((p) => ({
      id: p.id,
      name: p.name,
      brand: p.brand,
      partNumber: p.partNumber,
      category: p.category,
      condition: p.condition,
    })),
    compatiblePartCount: parts.length,
  });
});

router.get('/parts', (req, res) => {
  const limit = req.query.limit ? Number(req.query.limit) : undefined;
  const rows = findParts({
    category: req.query.category,
    vehicleId: req.query.vehicleId,
    q: req.query.q,
    limit: Number.isFinite(limit) ? limit : undefined,
  });
  res.json({ count: rows.length, results: rows });
});

/** Exact-identifier lookup — the OCR / manual entry path. */
router.get('/parts/lookup', (req, res) => {
  const { partNumber } = req.query;
  if (!partNumber) return res.status(400).json({ error: 'partNumber_query_required' });
  if (isObviousPartName(partNumber)) {
    return res.status(400).json({
      error: 'part_name_not_part_number',
      query: partNumber,
      detail: partNameInputMessage(partNumber),
    });
  }
  const part = findPartByNumber(partNumber);
  if (!part) {
    return res.status(404).json({
      error: 'part_number_not_in_catalogue',
      query: partNumber,
      advice: 'Check the stamped code for OCR mis-reads (0/O, 1/I, 8/B).',
    });
  }
  res.json({ query: partNumber, match: 'exact_or_suffix', part });
});

router.get('/parts/:id', (req, res) => {
  const part = byId('parts', req.params.id);
  if (!part) return res.status(404).json({ error: 'part_not_found', id: req.params.id });
  res.json({
    part,
    fitments: vehiclesForPart(part.id),
    offerCount: offersForPart(part.id).length,
  });
});

export default router;
