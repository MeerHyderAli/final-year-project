import { Router } from 'express';
import multer from 'multer';
import { AiUnavailableError, predictImage } from '../services/aiClient.js';
import { findParts } from '../store/index.js';
import { categoryLabel, isSafetyCritical } from '../taxonomy.js';
import config from '../config.js';

const router = Router();

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

  // Domain-shift advisory from the vision service. NOTE: measured detection rate on
  // real photos is only ~35%, so a silent (low) result is NOT a clean bill of health.
  // See ai-service/app/ood.py.
  const ood = raw.outOfDistribution ?? null;
  const domainShift = Boolean(raw.validity?.measuredCrossDomainAccuracy != null
    && raw.validity.measuredCrossDomainAccuracy < 0.6);

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
  if (domainShift) {
    warnings.push({
      code: 'model_domain_gap',
      message:
        `This checkpoint scores ${(raw.validity.measuredCrossDomainAccuracy * 100).toFixed(1)}% on real photographs ` +
        '(it was trained on rendered images). Treat the category as a hint, not an identification.',
      severity: 'high',
    });
  }

  res.json({
    modelVersion: raw.modelVersion ?? 'unknown',
    backend: raw.backend ?? null,
    latencyMs: raw.latencyMs ?? null,
    warnings,
    validity: raw.validity ?? null,
    outOfDistribution: ood,
    image: { filename: req.file.originalname, bytes: req.file.size, mimetype: req.file.mimetype },
    predictions,
    top1: top,
    confidenceThreshold: minConfidence,
    decision: uncertain ? 'ask_for_more_info' : 'accept_category',
    // The single most important sentence in the response.
    message: uncertain
      ? 'Not confident enough to name the part. Please add the part number or your vehicle details.'
      : `Best guess: ${top.categoryLabel}. Category only — fitment is not yet confirmed.`,
    nextSteps: ['Confirm fitment with vehicle details or a part number', 'Compare prices from verified sellers'],
  });
});

export default router;
