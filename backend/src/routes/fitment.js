import { Router } from 'express';
import { checkFitment } from '../services/fitmentService.js';
import { quoteForPart } from '../services/priceService.js';
import { nearbyVendors } from '../services/nearbyService.js';
import { byId, findPartByNumber } from '../store/index.js';
import { categoryLabel, isSafetyCritical } from '../taxonomy.js';

const router = Router();

/**
 * The single endpoint the whole product is built around: photo -> part -> fitment
 * -> price -> nearby. Each stage is independently addressable too, so a partial
 * answer is still useful when the vision service is down.
 */
router.post('/analyse', (req, res) => {
  const {
    partId,
    partNumber,
    category,
    prediction,          // raw output of POST /predict on the AI service
    vehicleId, make, model, year, engine,
    lat, lng, radiusKm = 15,
    condition,
  } = req.body || {};

  const aiUsed = Boolean(prediction?.predictions?.length);
  const top = aiUsed ? prediction.predictions[0] : null;

  // Guard rail: a low-confidence vision result must not drive a fitment claim.
  const minConfidence = Number(process.env.MIN_CONFIDENCE || 0.55);
  const aiUncertain = aiUsed && top.confidence < minConfidence;

  const effectiveCategory = category || partId ? byId('parts', partId)?.category ?? category : top?.category ?? category;

  // 1. Resolve the part.
  let resolvedPartId = partId || null;
  if (!resolvedPartId && partNumber) {
    resolvedPartId = findPartByNumber(partNumber)?.id ?? null;
  }
  if (!resolvedPartId && top?.cataloguePartId) {
    resolvedPartId = top.cataloguePartId;
  }
  if (!resolvedPartId && top?.category) {
    // Category-only prediction: offer the catalogue parts in that category as candidates.
    resolvedPartId = null;
  }

  // 2. Fitment verdict.
  const fitment = checkFitment({
    partId: resolvedPartId,
    partNumber,
    category: effectiveCategory,
    vehicleId,
    make,
    model,
    year,
    engine,
  });

  // 3. Price + 4. nearby — only when we actually have a catalogue part.
  const price = resolvedPartId ? quoteForPart(resolvedPartId, { vehicleId, condition }) : null;
  const nearby = nearbyVendors({
    lat, lng, radiusKm,
    partId: resolvedPartId,
    category: effectiveCategory,
  });

  const categorySafety = isSafetyCritical(effectiveCategory);

  const warnings = [];
  if (aiUncertain) {
    warnings.push({
      code: 'low_confidence',
      message:
        `The vision model returned ${(top.confidence * 100).toFixed(0)}% confidence, below the ${(minConfidence * 100).toFixed(0)}% threshold. ` +
        'Confirm the part number or vehicle details.',
    });
  }
  if (categorySafety) {
    warnings.push({
      code: 'safety_critical_category',
      message:
        `${categoryLabel(effectiveCategory)} affects braking/drivetrain safety. ` +
        'Image similarity is never sufficient — verify the stamped part number.',
    });
  }
  if (price && price.stats.count === 0) {
    warnings.push({
      code: 'no_price_data',
      message: 'No seller price is on record for this part. We have not estimated one.',
    });
  }

  res.json({
    input: { partId, partNumber, category, vehicleId, make, model, year, engine, lat, lng, radiusKm },
    stage1_identify: {
      source: aiUsed ? 'vision_model' : resolvedPartId ? 'catalogue_selection' : 'none',
      prediction: top,
      allPredictions: prediction?.predictions ?? [],
      modelVersion: prediction?.modelVersion ?? null,
      uncertainty: aiUncertain ? 'low_confidence' : aiUsed ? 'accepted' : 'not_used',
      predictedCategoryLabel: top?.category ? categoryLabel(top.category) : null,
    },
    stage2_fitment: fitment,
    stage3_price: price,
    stage4_nearby: nearby,
    warnings,
    /** Rendered as the persistent footer of every result card. */
    policy:
      'AI suggests; catalogue and seller data verify. Fitment is asserted only from a part-number or vehicle-catalogue match.',
    generatedAt: new Date().toISOString(),
  });
});

export default router;
