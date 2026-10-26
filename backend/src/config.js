import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Absolute path to the repo-root `data/` directory that holds the seed catalogue. */
export const DATA_DIR = process.env.DATA_DIR
  ? path.resolve(process.env.DATA_DIR)
  : path.resolve(__dirname, '..', '..', 'data');

function positiveEnvNumber(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

// The Node client must not give up before the Python provider client. Mirror the
// latter's worst-case budget: each attempt gets VISION_TIMEOUT seconds, with the
// same exponential backoff used by cloud_vision.py, plus a small HTTP margin.
// AI_TIMEOUT_MS remains an explicit override for deployments that need a hard cap.
const visionTimeoutSeconds = positiveEnvNumber('VISION_TIMEOUT', 30);
const visionAttempts = Math.max(1, Math.floor(positiveEnvNumber('VISION_RETRIES', 2)));
const retryBackoffSeconds = 1.5 * (2 ** (visionAttempts - 1) - 1);
const providerBudgetMs = Math.ceil(
  (visionTimeoutSeconds * visionAttempts + retryBackoffSeconds + 5) * 1000,
);

export const config = {
  port: Number(process.env.PORT || 4000),
  host: process.env.HOST || '0.0.0.0',

  /** Python FastAPI vision service. See ai-service/README.md */
  aiServiceUrl: process.env.AI_SERVICE_URL || 'http://127.0.0.1:8000',
  aiTimeoutMs: positiveEnvNumber('AI_TIMEOUT_MS', providerBudgetMs),

  /**
   * Optional persistent MongoDB catalogue. With no URI the API is explicitly a
   * JSON demo; with a URI MongoDB is the source of truth and must be reachable.
   */
  mongoUri: process.env.MONGODB_URI || '',
  mongoDbName: process.env.MONGODB_DB || 'autoparts_ai',
  // Explicit opt-in for putting the illustrative fixtures into an empty Mongo
  // database. Never seed a deployment merely because it has no records yet.
  seedDemoData: process.env.SEED_DEMO_DATA === 'true',

  uploadMaxBytes: Number(process.env.UPLOAD_MAX_BYTES || 8 * 1024 * 1024),

  /**
   * Below this top-1 confidence the API refuses to assert a part and asks the user
   * for more information. See docs/DATASET-AND-MODEL.md §"uncertain" behaviour.
   */
  minConfidence: Number(process.env.MIN_CONFIDENCE || 0.55),

  /** Categories where an automated verdict is never treated as final. */
  safetyCriticalCategories: ['brake_pad', 'clutch_plate'],
};

export default config;
