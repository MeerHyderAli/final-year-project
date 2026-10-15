import { Router } from 'express';
import { nearbyVendors } from '../services/nearbyService.js';
import { byId } from '../store/index.js';

const router = Router();

router.get('/', (req, res) => {
  const { lat, lng, radiusKm, category, partId, limit } = req.query;
  const hasOrigin = lat != null && lng != null;

  if (hasOrigin && (Number.isNaN(Number(lat)) || Number.isNaN(Number(lng)))) {
    return res.status(400).json({ error: 'invalid_coordinates' });
  }
  if (partId && !byId('parts', partId)) {
    return res.status(404).json({ error: 'part_not_found', partId });
  }

  const out = nearbyVendors({
    lat: hasOrigin ? Number(lat) : undefined,
    lng: hasOrigin ? Number(lng) : undefined,
    radiusKm: radiusKm ? Number(radiusKm) : undefined,
    category,
    partId,
    limit: limit ? Number(limit) : undefined,
  });

  if (!hasOrigin) {
    out.originNote = 'No coordinates supplied — results are unranked by distance and sorted by availability evidence and vendor trust.';
  }
  res.json(out);
});

router.get('/:id', (req, res) => {
  const vendor = byId('vendors', req.params.id);
  if (!vendor) return res.status(404).json({ error: 'vendor_not_found', id: req.params.id });
  res.json({ vendor });
});

export default router;
