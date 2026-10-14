// Disposable cross-runtime fixture. It has no provider adapter or account routes.
import { Pool } from 'pg';
import { createClient } from 'redis';
import { createApp } from '../../src/interface/http/app.js';
import { PostgresEarthquakeReader } from '../../src/infrastructure/postgres/earthquakeQueries.js';
import { PostgresBrevoReconciler } from '../../src/infrastructure/postgres/brevo.js';
import { RedisSyntheticScenarioReader } from '../../src/infrastructure/redis/syntheticScenarios.js';
import { RedisTestBrevoReconciler } from '../../src/infrastructure/redis/testBrevo.js';

const databaseUrl = process.env.TEST_DATABASE_URL!;
const redisUrl = process.env.TEST_REDIS_URL!;
if (new URL(databaseUrl).hostname !== 'postgres-test' || new URL(databaseUrl).pathname !== '/quakestrike_test'
    || new URL(redisUrl).hostname !== 'redis-test') throw new Error('Requires the disposable Compose services');
const pool = new Pool({ connectionString: databaseUrl, max: 1, connectionTimeoutMillis: 2000, statement_timeout: 3000 });
const redis = createClient({ url: redisUrl, disableOfflineQueue: true });
redis.on('error', () => {});
await redis.connect();
const reader = new PostgresEarthquakeReader(pool, 'a7f2286b-13a2-4708-a04d-4139281a4e1f');
const server = createApp(reader, () => new Date(), undefined,
  { token: 'TEST_ONLY_CALLBACK_TOKEN_FOR_WORKFLOW', reconciler: new PostgresBrevoReconciler(pool),
    testReconciler: new RedisTestBrevoReconciler(redis) }, new RedisSyntheticScenarioReader(redis)).listen(3000, '0.0.0.0');
process.on('SIGTERM', () => server.close(() => { redis.destroy(); void pool.end(); }));
