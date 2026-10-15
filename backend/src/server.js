import { createApp } from './app.js';
import config from './config.js';

const app = await createApp();

const server = app.listen(config.port, config.host, () => {
  console.log(`[api] AutoParts AI backend listening on http://${config.host}:${config.port}`);
  console.log(`[api] AI service: ${config.aiServiceUrl}`);
  console.log(`[api] Route index: http://localhost:${config.port}/api`);
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    console.log(`[api] ${sig} received, shutting down`);
    server.close(() => process.exit(0));
  });
}
