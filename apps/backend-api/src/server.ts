import { Pool } from 'pg';
import { loadSettings } from './config/settings.js';
import { PostgresEarthquakeReader } from './infrastructure/postgres/earthquakeQueries.js';
import { createApp } from './interface/http/app.js';
import { createClient } from 'redis';
import { AccountService } from './application/accounts/service.js';
import { PostgresAccounts } from './infrastructure/postgres/accounts.js';
import { RedisPhoneAttempts } from './infrastructure/redis/phoneAttempts.js';
import { clerkIdentity } from './infrastructure/clerk/identity.js';
import { Iprog } from './infrastructure/sms/iprog.js';
import { PostgresBrevoReconciler } from './infrastructure/postgres/brevo.js';
import { RedisSyntheticScenarioReader } from './infrastructure/redis/syntheticScenarios.js';

const settings = loadSettings();
const pool = new Pool({ connectionString: settings.databaseUrl, max: settings.poolSize,
  connectionTimeoutMillis: 2000, statement_timeout: settings.queryTimeoutMs });
pool.on('error', () => console.error(JSON.stringify({ service: 'backend-api', event: 'database_pool_error' })));
const reader = new PostgresEarthquakeReader(pool, settings.modelReleaseId);
await reader.check();

const redis = createClient({ url: process.env.ACCOUNT_REDIS_URL ?? 'redis://localhost:6379/0',
  disableOfflineQueue: true, socket: { connectTimeout: 2000,
    reconnectStrategy: retries => Math.min(250 * 2 ** Math.min(retries, 4), 5000) } });
redis.on('error', () => console.error(JSON.stringify({ service: 'backend-api', event: 'account_redis_unavailable' })));
// Public reading remains usable during an account-provider or Redis outage.
if (process.env.ACCOUNT_REDIS_URL) void redis.connect().catch(() => {});
const accounts = { service: new AccountService(new PostgresAccounts(pool), new RedisPhoneAttempts(redis), new Iprog(process.env.IPROG_API_TOKEN)),
  authenticate: clerkIdentity(process.env.CLERK_SECRET_KEY, (process.env.CLERK_AUTHORIZED_PARTIES ?? '').split(',').map(x => x.trim()).filter(Boolean), process.env.CLERK_PUBLISHABLE_KEY) };
const syntheticRedis = process.env.ALERT_TEST_REDIS_URL ? createClient({ url: process.env.ALERT_TEST_REDIS_URL,
  disableOfflineQueue: true, socket: { connectTimeout: 2000,
    reconnectStrategy: retries => Math.min(250 * 2 ** Math.min(retries, 4), 5000) } }) : undefined;
syntheticRedis?.on('error', () => console.error(JSON.stringify({ service: 'backend-api', event: 'synthetic_redis_unavailable' })));
if (syntheticRedis) void syntheticRedis.connect().catch(() => {});
const server = createApp(reader, () => new Date(), accounts,
  { token: settings.brevoCallbackToken, reconciler: new PostgresBrevoReconciler(pool) },
  syntheticRedis ? new RedisSyntheticScenarioReader(syntheticRedis) : undefined).listen(settings.port, '0.0.0.0', () => {
  console.info(JSON.stringify({ service: 'backend-api', event: 'listening', port: settings.port }));
});

process.on('SIGTERM', () => {
  server.close(() => { if (redis.isOpen) redis.destroy(); if (syntheticRedis?.isOpen) syntheticRedis.destroy(); void pool.end(); });
});
