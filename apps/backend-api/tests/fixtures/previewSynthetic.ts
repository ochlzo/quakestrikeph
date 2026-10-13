// Disposable browser acceptance harness. Never imported by src or the production build entry point.
import { createClient } from 'redis';
import { createApp } from '../../src/interface/http/app.js';
import { RedisSyntheticScenarioReader } from '../../src/infrastructure/redis/syntheticScenarios.js';
import { eventId, sessionId, submittedFixture } from './submittedScenario.js';

const url = process.env.TEST_REDIS_URL;
if (url !== 'redis://127.0.0.1:6387/0') throw new Error('Preview requires the documented disposable Redis on port 6387');
const redis = createClient({ url, disableOfflineQueue: true, socket: { reconnectStrategy: false } });
redis.on('error', () => console.error('Disposable Redis unavailable'));
await redis.connect();
const control = 'quakestrike:alert-testing:session';
const key = `quakestrike:alert-testing:${sessionId}:scenario:${eventId}`;
if (await redis.exists(control)) { redis.destroy(); throw new Error('Preview refuses an existing session'); }
const deadline = Date.now() + 4 * 3600000;
const fixture = submittedFixture(deadline);
const start = Date.now() - 3600000;
fixture.scenario.event.event_time_ms = start;
fixture.scenario.forecast.window_start_ms = start;
fixture.scenario.forecast.window_end_ms = start + 86400000;
fixture.scenario.observations.forEach((observation, index) => { observation.event_time_ms = start + (index + 1) * 600000; });
await redis.hSet(control, { session_id: sessionId, lifecycle: 'active', expires_at_ms: String(deadline) });
await redis.pExpireAt(control, deadline + 86400000);
await redis.set(key, JSON.stringify(fixture), { expiration: { type: 'PXAT', value: deadline } });
const server = createApp({ findById: async () => null, search: async () => [], check: async () => {} },
  () => new Date(), undefined, undefined, new RedisSyntheticScenarioReader(redis)).listen(4312, '127.0.0.1');
console.log(`Fixture API: http://127.0.0.1:4312/api/v1/earthquakes/${eventId}?test=true`);
console.log(`Bulletin: http://127.0.0.1:4321/forecasts/${eventId}?test=true`);
console.log('Normal fixture lists are empty. This harness sends no messages.');
const stop = () => server.close(() => {
  void (async () => {
    if (redis.isReady) await redis.del([control, key]);
    if (redis.isOpen) redis.destroy();
  })();
});
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
