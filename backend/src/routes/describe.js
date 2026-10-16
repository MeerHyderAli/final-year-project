import { Router } from 'express';
import { AiUnavailableError } from '../services/aiClient.js';
import { describePart, aiHealth } from '../services/aiClient.js';
import { findPartByNumber, findParts } from '../store/index.js';
import { categoryLabel, isSafetyCritical } from '../taxonomy.js';
import config from '../config.js';

const router = Router();

/**
 * POST /api/describe   { description: "round black filter under the engine" }
 *
 * Text-instead-of-photo path. Useful when the user cannot get a usable picture:
 * poorly lit engine bays, a part still fitted, or a farmer describing a tractor part
 * over the phone.
 *
 * It is deliberately treated as WEAKER evidence than a photo: the response carries
 * the same confidence floor, and the message tells the user to confirm with a part
 * number or vehicle. A description is a starting point, never an identification.
 */
router.post('/', async (req, res) => {
  const description = String(req.body?.description ?? '').trim();

  if (!description) {
    return res.status(400).json({
      error: 'description_required',
      detail: 'Send {"description": "<what the part looks like or does>"}.',
    });
  }
  if (description.length < 4) {
    return res.status(400).json({
      error: 'description_too_short',
      detail: 'Give at least a few words — "broken part" cannot be narrowed down.',
    });
  }

  let raw;
  try {
    raw = await describePart(description);
  } catch (err) {
    const status = err instanceof AiUnavailableError ? 503 : 502;
    return res.status(status).json({
      error: 'describe_unavailable',
      detail: err.message,
      fallback: {
        route: '/api/catalog/parts/lookup?partNumber=...',
        ui: 'Ask the user for the stamped part number, or to pick their vehicle instead.',
      },
    });
  }

  const minConfidence = config.minConfidence;
  const predictions = (raw.predictions || []).map((p) => ({
    ...p,
    categoryLabel: categoryLabel(p.category),
    safetyCritical: isSafetyCritical(p.category),
    catalogueCandidates: findParts({ category: p.category, limit: 5 }).map((c) => ({
      id: c.id,
      name: c.name,
      brand: c.brand,
      partNumber: c.partNumber,
      condition: c.condition,
    })),
  }));

  const top = predictions[0] ?? null;
  const uncertain = !top || top.confidence < minConfidence;

  const visiblePartNumber = raw.visiblePartNumber ?? null;
  const matched = visiblePartNumber ? findPartByNumber(visiblePartNumber) : null;

  res.json({
    input: { description },
    modelVersion: raw.modelVersion ?? 'unknown',
    backend: raw.backend ?? null,
    latencyMs: raw.latencyMs ?? null,
    confidenceSource: raw.confidenceSource ?? null,
    predictions,
    top1: top,
    confidenceThreshold: minConfidence,
    decision: uncertain ? 'ask_for_more_info' : 'accept_category',
    detected: {
      partNumber: visiblePartNumber,
      brand: raw.visibleBrand ?? null,
      catalogueMatch: matched
        ? { id: matched.id, name: matched.name, brand: matched.brand, partNumber: matched.partNumber,
            category: matched.category, condition: matched.condition }
        : null,
    },
    reasoning: raw.reasoning ?? null,
    message: uncertain
      ? 'That description is not specific enough to name the part. Add the part number, or a detail like where it sits or what it is made of.'
      : `Best guess from your description: ${categoryLabel(top.category)}. Category only — fitment is not yet confirmed.`,
    evidenceStrength: 'weaker_than_photo',
    caveat:
      'A description is weaker evidence than a photograph or a part number. It narrows the search; it does not identify the part.',
    nextSteps: ['Confirm fitment with your vehicle details', 'Compare prices from verified sellers'],
  });
});

export default router;

export { aiHealth };
