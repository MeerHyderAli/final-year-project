import { Router } from 'express';
import { byId, findParts } from '../store/index.js';
import { pricePolicy, quoteForPart } from '../services/priceService.js';

const router = Router();

router.get('/policy', (_req, res) => {
  res.json({
    currency: 'INR',
    failClosed: true,
    rules: [
      'No price is shown without a named source and an updated timestamp.',
      `Quotes older than ${pricePolicy.STALE_AFTER_DAYS} days are labelled stale.`,
      'A vendor is described as "in stock" only when the seller or their inventory system confirmed it.',
      'A map listing is never treated as evidence of stock.',
      'When no offer exists, the API says so instead of estimating.',
    ],
    sourceTrust: pricePolicy.SOURCE_TRUST,
  });
});

router.get('/compare', (req, res) => {
  const { partId, vehicleId, condition } = req.query;
  if (!partId) return res.status(400).json({ error: 'partId_required' });

  const part = byId('parts', partId);
  if (!part) return res.status(404).json({ error: 'part_not_found', partId });

  const quote = quoteForPart(part.id, { vehicleId, condition });

  // Same-category alternatives, so the user sees genuine vs aftermarket choices.
  const alternatives = findParts({ category: part.category })
    .filter((p) => p.id !== part.id)
    .map((p) => {
      const q = quoteForPart(p.id);
      return {
        id: p.id,
        name: p.name,
        brand: p.brand,
        partNumber: p.partNumber,
        condition: p.condition,
        fitsVehicleIds: p.fitsVehicleIds,
        lowestPrice: q.stats.min,
        offerCount: q.stats.count,
        confirmedCount: q.quotes.filter((x) => x.stockStatus === 'confirmed').length,
      };
    })
    .sort((a, b) => (a.lowestPrice ?? Infinity) - (b.lowestPrice ?? Infinity));

  res.json({
    part: { id: part.id, name: part.name, brand: part.brand, partNumber: part.partNumber, category: part.category, condition: part.condition },
    quote,
    alternatives,
    alternativesNote:
      'Alternatives are catalogue parts in the same category. They are NOT confirmed to fit your vehicle — run a fitment check before choosing one.',
  });
});

export default router;
