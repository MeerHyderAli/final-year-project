import { Router } from 'express';
import { checkFitment } from '../services/fitmentService.js';
import { quoteForPart } from '../services/priceService.js';
import { nearbyVendors } from '../services/nearbyService.js';
import { byId, findPartByNumber } from '../store/index.js';
import { categoryLabel, isSafetyCritical } from '../taxonomy.js';
import { isObviousPartName, partNameInputMessage, partNumberOrNull } from '../services/partNumber.js';

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
    visiblePartNumber: rawVisiblePartNumber, // text the vision model read OFF the part
    vehicleId, make, model, year, engine,
    lat, lng, radiusKm = 15,
    condition,
  } = req.body || {};

  if (isObviousPartName(partNumber)) {
    return res.status(400).json({
      error: 'part_name_not_part_number',
      detail: partNameInputMessage(partNumber),
    });
  }

  // A model can mistake a part name for an identifier. Do not let that text
  // become an exact-match attempt or an "unknown part number" verdict.
  const visiblePartNumber = partNumberOrNull(rawVisiblePartNumber);
  const rejectedVisiblePartName = isObviousPartName(rawVisiblePartNumber)
    ? String(rawVisiblePartNumber).trim()
    : null;

  const aiUsed = Boolean(prediction?.predictions?.length);
  const top = aiUsed ? prediction.predictions[0] : null;

  // Guard rail: a low-confidence vision result must not drive a fitment claim.
  const minConfidence = Number(process.env.MIN_CONFIDENCE || 0.55);
  const aiUncertain = aiUsed && top.confidence < minConfidence;

  const effectiveCategory = category || partId ? byId('parts', partId)?.category ?? category : top?.category ?? category;

  // 1. Resolve the part.
  //    Priority matters. A part number read off the physical part is the strongest
  //    evidence available from an image, so it outranks a user-supplied candidate
  //    and always outranks a category guess.
  let resolvedPartId = partId || null;
  let resolutionPath = resolvedPartId ? 'explicit_part_id' : null;

  if (!resolvedPartId && partNumber) {
    const hit = findPartByNumber(partNumber);
    if (hit) {
      resolvedPartId = hit.id;
      resolutionPath = 'user_part_number';
    }
  }
  if (!resolvedPartId && visiblePartNumber) {
    const hit = findPartByNumber(visiblePartNumber);
    if (hit) {
      resolvedPartId = hit.id;
      resolutionPath = 'part_number_read_from_photo';
    }
  }
  if (!resolvedPartId && top?.cataloguePartId) {
    resolvedPartId = top.cataloguePartId;
    resolutionPath = 'prediction_suggested_part';
  }
  // A category-only prediction leaves resolvedPartId null on purpose: the catalogue
  // cannot pick a specific part from a category, and guessing one would be inventing
  // evidence. The UI offers candidates instead.

  // 2. Fitment verdict. Feed the catalogue-matched number through so the verdict can
  //    reach `confirmed` — the only verdict that asserts compatibility.
  const effectivePartNumber =
    partNumber ||
    (resolutionPath === 'part_number_read_from_photo' && visiblePartNumber ? visiblePartNumber : undefined);

  const fitment = checkFitment({
    partId: resolvedPartId,
    partNumber: effectivePartNumber,
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
  if (rejectedVisiblePartName) {
    warnings.push({
      code: 'part_name_not_part_number',
      message:
        `The vision model returned "${rejectedVisiblePartName}" as text, but that is a part name, ` +
        'not a stamped part number. No exact part-number lookup was made; confirm the code physically.',
      severity: 'medium',
    });
  }
  if (aiUncertain) {
    warnings.push({
      code: 'low_confidence',
      message:
        `The vision model returned ${(top.confidence * 100).toFixed(0)}% confidence, below the ${(minConfidence * 100).toFixed(0)}% threshold. ` +
        'Confirm the part number or vehicle details.',
    });
  }
  if (visiblePartNumber && resolutionPath === 'part_number_read_from_photo') {
    warnings.push({
      code: 'part_number_read_from_photo',
      message:
        `Part number "${visiblePartNumber}" was read from your photo and matched the catalogue. ` +
        'OCR of stamped codes is not infallible — confirm it against the physical label.',
    });
  }
  if (visiblePartNumber && !resolutionPath?.includes('from_photo') && resolutionPath !== 'user_part_number') {
    warnings.push({
      code: 'part_number_not_matched',
      message:
        `Your photo appears to show part number "${visiblePartNumber}", which is not in the catalogue. ` +
        'Check it against the printed label — 0/O, 1/I and 8/B are commonly mis-read.',
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
    resolution: {
      path: resolutionPath,
      partNumberUsed: effectivePartNumber ?? null,
      partNumberFromPhoto: visiblePartNumber ?? null,
      explanation: {
        explicit_part_id: 'You chose this part from the catalogue.',
        user_part_number: 'You supplied the part number.',
        part_number_read_from_photo: 'The part number was read from your photo and matched a catalogue record.',
        prediction_suggested_part: 'The vision model suggested this catalogue part.',
      }[resolutionPath] ?? 'No catalogue part was resolved — only a category is known.',
    },
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
