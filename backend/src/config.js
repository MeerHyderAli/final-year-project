import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Absolute path to the repo-root `data/` directory that holds the seed catalogue. */
export const DATA_DIR = process.env.DATA_DIR
  ? path.resolve(process.env.DATA_DIR)
  : path.resolve(__dirname, '..', '..', 'data');

export const config = {
  port: Number(process.env.PORT || 4000),
  host: process.env.HOST || '0.0.0.0',

  /** Python FastAPI vision service. See ai-service/README.md */
  aiServiceUrl: process.env.AI_SERVICE_URL || 'http://127.0.0.1:8000',
  aiTimeoutMs: Number(process.env.AI_TIMEOUT_MS || 20000),

  /**
   * Optional MongoDB. When MONGODB_URI is unset the API runs fully offline on the
   * JSON seed catalogue in `data/` — this is the default for demos and CI.
   */
  mongoUri: process.env.MONGODB_URI || '',
  mongoDbName: process.env.MONGODB_DB || 'autoparts_ai',

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
