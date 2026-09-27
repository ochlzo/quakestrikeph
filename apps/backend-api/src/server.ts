import { Pool } from 'pg';
import { loadSettings } from './config/settings.js';
import { PostgresEarthquakeReader } from './infrastructure/postgres/earthquakeQueries.js';
import { createApp } from './interface/http/app.js';

const settings = loadSettings();
const pool = new Pool({ connectionString: settings.databaseUrl, max: settings.poolSize,
  connectionTimeoutMillis: 2000, statement_timeout: settings.queryTimeoutMs });
pool.on('error', () => console.error(JSON.stringify({ service: 'backend-api', event: 'database_pool_error' })));
const reader = new PostgresEarthquakeReader(pool, settings.modelReleaseId);
await reader.check();

const server = createApp(reader).listen(settings.port, '0.0.0.0', () => {
  console.info(JSON.stringify({ service: 'backend-api', event: 'listening', port: settings.port }));
});

process.on('SIGTERM', () => {
  server.close(() => void pool.end());
});
