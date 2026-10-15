import express from 'express';
import cors from 'cors';
import config from './config.js';
import { loadStore, storeInfo } from './store/index.js';
import { primeVehicleIndex } from './services/fitmentService.js';
import { aiHealth } from './services/aiClient.js';
import { all } from './store/index.js';

import catalogRoutes from './routes/catalog.js';
import identifyRoutes from './routes/identify.js';
import ocrRoutes from './routes/ocr.js';
import fitmentRoutes from './routes/fitment.js';
import priceRoutes from './routes/price.js';
import nearbyRoutes from './routes/nearby.js';
import { errorHandler, notFound } from './middleware/errors.js';

export async function createApp() {
  await loadStore();
  primeVehicleIndex(all('vehicles'));

  const app = express();
  app.disable('x-powered-by');
  app.use(cors());
  app.use(express.json({ limit: '1mb' }));

  app.get('/api/health', async (_req, res) => {
    const ai = await aiHealth();
    res.json({
      status: 'ok',
      service: 'autoparts-ai-backend',
      version: '0.1.0',
      uptimeSeconds: Math.round(process.uptime()),
      catalogue: storeInfo(),
      aiService: { url: config.aiServiceUrl, ...ai },
      // Explicitly advertise what the system will NOT do.
      guarantees: [
        'Fitment is asserted only from a part-number or vehicle-catalogue match.',
        'Every price carries a source and an updated timestamp.',
        'The API says "unknown" rather than guessing.',
      ],
    });
  });

  // Route index — makes the API self-documenting for the report appendix.
  app.get('/api', (_req, res) => {
    res.json({
      service: 'AutoParts AI API',
      endpoints: [
        { method: 'GET', path: '/api/health', purpose: 'Liveness + AI service reachability + data guarantees' },
        { method: 'GET', path: '/api/catalog/meta', purpose: 'Taxonomy, category counts, store driver' },
        { method: 'GET', path: '/api/catalog/vehicles', purpose: 'Vehicle master (filter by class/make/q)' },
        { method: 'GET', path: '/api/catalog/vehicles/:id', purpose: 'Vehicle detail + all compatible parts' },
        { method: 'GET', path: '/api/catalog/parts', purpose: 'Catalogue search (category/vehicleId/q/limit)' },
        { method: 'GET', path: '/api/catalog/parts/lookup?partNumber=', purpose: 'Exact part-number match (OCR path)' },
        { method: 'GET', path: '/api/catalog/parts/:id', purpose: 'Part detail + fitments' },
        { method: 'POST', path: '/api/identify', purpose: 'Image -> category prediction + catalogue candidates' },
        { method: 'POST', path: '/api/ocr', purpose: 'Label photo or raw text -> part-number candidates -> catalogue match' },
        { method: 'POST', path: '/api/fitment/analyse', purpose: 'Full pipeline: identify + fitment + price + nearby' },
        { method: 'GET', path: '/api/price/policy', purpose: 'Transparency rules for pricing' },
        { method: 'GET', path: '/api/price/compare?partId=', purpose: 'Vendor quotes, stats, same-category alternatives' },
        { method: 'GET', path: '/api/nearby?lat=&lng=&partId=', purpose: 'Distance + evidence weighted vendor ranking' },
      ],
    });
  });

  app.use('/api/catalog', catalogRoutes);
  app.use('/api/identify', identifyRoutes);
  app.use('/api/ocr', ocrRoutes);
  app.use('/api/fitment', fitmentRoutes);
  app.use('/api/price', priceRoutes);
  app.use('/api/nearby', nearbyRoutes);

  app.use('/api', notFound);
  app.use(errorHandler);

  return app;
}
