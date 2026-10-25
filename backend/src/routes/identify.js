import { Router } from 'express';
import multer from 'multer';
import { AiUnavailableError, aiHealth, predictImage } from '../services/aiClient.js';
import { findPartByNumber, findParts } from '../store/index.js';
import { categoryLabel, isSafetyCritical } from '../taxonomy.js';
import config from '../config.js';
import { isObviousPartName, partNumberOrNull } from '../services/partNumber.js';

const router = Router();

/**
 * GET /api/identify/health
 *
 * Which identification engine will actually serve a request, and what the UI should
 * tell the user about it. The frontend calls this to show the provider banner — the
 * user deserves to know whether a real vision model is answering or a fallback is.
 */
router.get('/health', async (_req, res) => {
  const ai = await aiHealth();

  if (!ai.reachable) {
    return res.json({
      engine: 'unavailable',
      reachable: false,
      detail: ai.error ?? 'identification service unreachable',
      message:
        'The identification service is offline. The part-number and vehicle paths still work — ' +
        'only photo identification is affected.',
      requiresTraining: false,
      requiresDataset: false,
      warnings: ['Identification service unreachable.'],
    });
  }

  res.json({
    reachable: true,
    engine: ai.engine ?? 'unknown',
    engines: ai.engines ?? null,
    requiresTraining: Boolean(ai.requiresTraining),
    requiresDataset: Boolean(ai.requiresDataset),
    warnings: ai.warnings ?? [],
    classes: ai.classes ?? null,
    confidenceFloor: ai.confidenceFloor ?? null,
  });
});

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.uploadMaxBytes, files: 1 },
  fileFilter: (_req, file, cb) => {
    const ok = /^image\/(jpeg|png|webp|bmp|gif)$/.test(file.mimetype);
    cb(ok ? null : new Error('unsupported_image_type'), ok);
  },
});

/**
 * POST /api/identify
 * multipart/form-data: file=<image>
 *
 * Proxies to the Python vision service and *enriches* the raw class prediction with
 * catalogue candidates. If the AI service is down we return 503 with a machine
 * readable code — the UI must offer the part-number path rather than a fake answer.
 */
router.post('/', upload.single('file'), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: 'image_required', detail: 'Send multipart/form-data with field "file".' });
  }

  let raw;
  try {
    raw = await predictImage({
      buffer: req.file.buffer,
      filename: req.file.originalname,
      mimetype: req.file.mimetype,
    });
  } catch (err) {
    const status = err instanceof AiUnavailableError ? 503 : 500;
    return res.status(status).json({
      error: 'ai_service_unavailable',
      detail: err.message,
      // Do not fail the user's journey — send them to the deterministic path.
      fallback: {
        route: '/api/catalog/parts/lookup?partNumber=...',
        ui: 'Ask the user to enter the stamped part number or select their vehicle.',
      },
    });
  }

  const minConfidence = config.minConfidence;
  const predictions = (raw.predictions || []).map((p) => ({
    ...p,
    categoryLabel: categoryLabel(p.category),
    safetyCritical: isSafetyCritical(p.category),
    // What the user could actually buy, given the category.
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

  // Domain-shift advisory from the local model. Absent on the cloud path, because a
  // frontier model has no meaningful "training distribution" to compare against.
  const ood = raw.outOfDistribution ?? null;

  // The most valuable thing a photo can give us: a part number printed ON the part.
  // It converts an image guess into an exact catalogue lookup, which is the only
  // route to a `confirmed` fitment verdict.
  const rawVisiblePartNumber = raw.visiblePartNumber ?? null;
  const visiblePartNumber = partNumberOrNull(rawVisiblePartNumber);
  const rejectedVisiblePartName = isObviousPartName(rawVisiblePartNumber)
    ? String(rawVisiblePartNumber).trim()
    : null;
  const visibleBrand = raw.visibleBrand ?? null;
  let detectedPart = null;
  if (visiblePartNumber) {
    detectedPart = findPartByNumber(visiblePartNumber);
  }

  const warnings = [];
  if (uncertain) {
    warnings.push({
      code: 'low_confidence',
      message: `Vision confidence ${top ? (top.confidence * 100).toFixed(0) : 0}% is below the ${(minConfidence * 100).toFixed(0)}% threshold.`,
    });
  }
  if (ood && ood.level !== 'low') {
    warnings.push({ code: 'out_of_distribution', message: ood.note, severity: ood.level });
  }
  if (raw.backend === 'heuristic') {
    warnings.push({
      code: 'degraded_engine',
      message:
        'No cloud provider and no local model are available, so a rule-based guess answered. ' +
        'It cannot pass the confidence threshold — configure the AI provider or use a part number.',
      severity: 'high',
    });
  }
  if (raw.fallbackReason) {
    warnings.push({
      code: 'provider_fallback',
      message: `The AI provider could not be reached (${raw.fallbackReason}), so a local fallback answered.`,
      severity: 'high',
    });
  }
  if (rejectedVisiblePartName) {
    warnings.push({
      code: 'part_name_not_part_number',
      message:
        `The model returned "${rejectedVisiblePartName}" as text, but that is a part name, not a stamped part number. ` +
        'No exact part-number lookup was made. Confirm the printed code physically.',
      severity: 'medium',
    });
  }
  if (visiblePartNumber && !detectedPart) {
    warnings.push({
      code: 'read_part_number_not_in_catalogue',
      message:
        `The photo appears to show part number "${visiblePartNumber}", which is not in the catalogue. ` +
        'Check it against the printed label — 0/O, 1/I and 8/B are commonly mis-read.',
      severity: 'medium',
    });
  }
  if (visiblePartNumber && detectedPart) {
    warnings.push({
      code: 'part_number_read_from_photo',
      message:
        `Part number "${visiblePartNumber}" was read from the photo and matched catalogue record ` +
        `${detectedPart.partNumber}. Confirm it against the label before ordering.`,
      severity: 'info',
    });
  }

  res.json({
    modelVersion: raw.modelVersion ?? 'unknown',
    backend: raw.backend ?? null,
    latencyMs: raw.latencyMs ?? null,
    confidenceSource: raw.confidenceSource ?? null,
    warnings,
    validity: raw.validity ?? null,
    outOfDistribution: ood,
    reasoning: raw.reasoning ?? null,
    // Part number and brand read off the part itself, plus the catalogue match if any.
    detected: {
      partNumber: visiblePartNumber,
      brand: visibleBrand,
      catalogueMatch: detectedPart
        ? {
            id: detectedPart.id,
            name: detectedPart.name,
            brand: detectedPart.brand,
            partNumber: detectedPart.partNumber,
            category: detectedPart.category,
            condition: detectedPart.condition,
          }
        : null,
    },
    image: { filename: req.file.originalname, bytes: req.file.size, mimetype: req.file.mimetype },
    predictions,
    top1: top,
    confidenceThreshold: minConfidence,
    decision: uncertain ? 'ask_for_more_info' : 'accept_category',
    // The single most important sentence in the response.
    message: uncertain
      ? 'Not confident enough to name the part. Please add the part number or your vehicle details.'
      : `Best guess: ${top.categoryLabel}. Category only — fitment is not yet confirmed.`,
    nextSteps: detectedPart
      ? [`Confirm fitment for ${detectedPart.partNumber} with your vehicle details`, 'Compare prices from verified sellers']
      : ['Confirm fitment with vehicle details or a part number', 'Compare prices from verified sellers'],
  });
});

export default router;
