import { Router } from 'express';
import multer from 'multer';
import { fetchOcr } from '../services/ocrClient.js';
import { findPartByNumber, all } from '../store/index.js';
import { normalizePartNumber } from '../store/index.js';
import config from '../config.js';

const router = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.uploadMaxBytes, files: 1 },
});

/**
 * POST /api/ocr
 * multipart/form-data: file=<photo of a label / stamped code>
 * optional form fields: rawText=<client-side OCR text>
 *
 * OCR output is *never* trusted verbatim. Codes are normalised and then matched
 * against the catalogue; ambiguous glyphs (0/O, 1/I, 8/B, 5/S) are resolved by
 * checking which variant actually exists in the catalogue.
 */
router.post('/', upload.single('file'), async (req, res) => {
  const clientText = req.body?.rawText;
  let text = clientText ?? '';
  let engine = 'client_supplied';
  let serviceDetail = null;

  if (!text && req.file) {
    try {
      const out = await fetchOcr({ buffer: req.file.buffer, filename: req.file.originalname, mimetype: req.file.mimetype });
      text = out.text ?? '';
      engine = out.engine ?? 'unknown';
    } catch (err) {
      return res.status(503).json({
        error: 'ocr_service_unavailable',
        detail: err.message,
        fallback: { ui: 'Ask the user to type the part number from the label.' },
      });
    }
  }

  if (!req.file && !clientText) {
    return res.status(400).json({ error: 'image_or_rawText_required' });
  }

  const lines = String(text)
    .split(/[\n\r]+/)
    .map((l) => l.trim())
    .filter(Boolean);

  // Part-number-shaped tokens: >=6 chars, at least 2 digits, mixed alphanumerics.
  const candidates = extractCandidates(lines);

  const matches = candidates.map((c) => {
    const hit = findPartByNumber(c.value);
    const variants = ambiguousResolutions(c.value).filter((v) => findPartByNumber(v));
    return {
      raw: c.value,
      normalized: normalizePartNumber(c.value),
      line: c.line,
      confidence: c.confidence,
      catalogueMatch: hit
        ? { id: hit.id, name: hit.name, brand: hit.brand, partNumber: hit.partNumber, category: hit.category }
        : null,
      ambiguousVariantsInCatalogue: variants,
    };
  });

  const best = matches.find((m) => m.catalogueMatch) ?? null;

  res.json({
    engine,
    serviceDetail,
    rawText: text,
    lines,
    candidates: matches,
    match: best,
    decision: best ? 'exact_catalogue_match' : candidates.length ? 'unmatched_codes' : 'no_code_found',
    message: best
      ? `Matched ${best.catalogueMatch.partNumber} — ${best.catalogueMatch.name} (${best.catalogueMatch.brand}).`
      : candidates.length
        ? 'Read a code but it is not in the catalogue. Confirm it against the stamped text; 0/O, 1/I and 8/B are commonly mis-read.'
        : 'No part-number-shaped text found. Try a closer, well-lit photo of the label.',
    verifyHint: 'Always verify OCR reads against the physical label before ordering.',
  });
});

function extractCandidates(lines) {
  const out = [];
  for (const line of lines) {
    // Split a line into tokens and score each one.
    const tokens = line.split(/[^A-Za-z0-9\-./]+/).filter(Boolean);
    for (const token of tokens) {
      const norm = normalizePartNumber(token);
      if (norm.length < 5 || norm.length > 20) continue;
      const digits = (norm.match(/\d/g) || []).length;
      const letters = (norm.match(/[A-Z]/g) || []).length;
      if (digits === 0 || letters === 0) continue; // pure numbers are usually dates/serials
      let confidence = 0.4;
      if (digits >= 2) confidence += 0.15;
      if (letters >= 2) confidence += 0.15;
      if (/[-\/.]/.test(token)) confidence += 0.1; // real part numbers use separators
      if (norm.length >= 8) confidence += 0.1;
      out.push({ value: token, line, confidence: Math.min(0.95, Number(confidence.toFixed(2))) });
    }
  }
  return out.sort((a, b) => b.confidence - a.confidence).slice(0, 12);
}

/** Generate glyph-confusion variants and keep the ones that exist in the catalogue. */
function ambiguousResolutions(value) {
  const base = normalizePartNumber(value);
  const swaps = { '0': 'O', O: '0', '1': 'I', I: '1', '8': 'B', B: '8', '5': 'S', S: '5', '2': 'Z', Z: '2' };
  const variants = new Set();
  for (let i = 0; i < base.length; i += 1) {
    const ch = base[i];
    if (swaps[ch]) variants.add(base.slice(0, i) + swaps[ch] + base.slice(i + 1));
  }
  return [...variants].slice(0, 20);
}

export default router;
