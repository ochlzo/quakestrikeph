import assert from 'node:assert/strict';
import test from 'node:test';
import { createClient } from 'redis';
import { RedisSyntheticScenarioReader } from '../../src/infrastructure/redis/syntheticScenarios.js';
import { submittedFixture, eventId, sessionId } from '../fixtures/submittedScenario.js';
import { observations, publicWorkflow } from '../fixtures/publicScenarioWorkflow.js';

test('disposable submitted scenario: closure gate, expiry, cleanup, replacement, corruption and Redis outage',
  { skip: !process.env.TEST_REDIS_URL }, async () => {
    if (new URL(process.env.TEST_REDIS_URL!).hostname !== 'redis-test') throw new Error('Requires isolated Compose redis-test');
    const redis = createClient({ url: process.env.TEST_REDIS_URL, disableOfflineQueue: true });
    redis.on('error', () => {});
    await redis.connect();
    const control = 'quakestrike:alert-testing:session';
    const key = `quakestrike:alert-testing:${sessionId}:scenario:${eventId}`;
    const unrelated = 'ticket60:unrelated';
    const deadline = Date.now() + 3600000, fixture = submittedFixture(deadline);
    const activate = async () => {
      await redis.hSet(control, { session_id: sessionId, lifecycle: 'active', expires_at_ms: String(deadline) });
      await redis.set(key, JSON.stringify(fixture), { expiration: { type: 'PXAT', value: deadline } });
    };
    let ownsFixture = false;
    try {
      assert.equal(await redis.exists(control), 0, 'Requires a disposable Redis without another active session');
      ownsFixture = true;
      await redis.set(unrelated, 'keep');
      await publicWorkflow(new RedisSyntheticScenarioReader(redis), async base => {
        const url = `${base}/${eventId}?test=true`;
        assert.equal((await fetch(url)).status, 404);
        await activate();
        const previewKey = `quakestrike:alert-testing:${sessionId}:preview:${eventId}`;
        await redis.del(key);
        await redis.set(previewKey, JSON.stringify({ ...fixture, submitted: false, preview: true, saved_at_ms: fixture.submitted_at_ms }),
          { expiration: { type: 'PXAT', value: deadline } });
        assert.equal((await fetch(url)).status, 200, 'Persisted preview is readable before submission');
        await redis.hSet(control, { lifecycle: 'closed' });
        assert.equal((await fetch(url)).status, 404, 'Preview obeys session closure');
        await redis.del(previewKey);
        await activate();
        const first = await (await fetch(url)).json() as { item: unknown };
        assert.deepEqual((await (await fetch(url)).json() as { item: unknown }).item, first.item);
        const start = fixture.scenario.forecast.window_start_ms;
        const response = await observations(base, start, start + 86400000);
        const page = await response.json() as { nextCursor: string; items: unknown[] };
        assert.ok(page.nextCursor);
        assert.equal((await observations(base, start, start + 86400000, page.nextCursor)).status, 200);
        assert.doesNotMatch(JSON.stringify(first), /private|testers|deliveries/);
        await redis.hSet(control, { lifecycle: 'closed', cleanup: 'failed' });
        assert.equal(await redis.exists(key), 1, 'Closed access before physical cleanup');
        assert.equal((await fetch(url)).status, 404);
        assert.equal((await observations(base, start, start + 10000, page.nextCursor)).status, 404);
        await redis.unlink(key);
        assert.equal((await fetch(url)).status, 404);
        assert.equal(await redis.get(unrelated), 'keep');
        await activate();
        await redis.hSet(control, { expires_at_ms: String(Date.now() - 1) });
        assert.equal((await fetch(url)).status, 404, 'Expiry gate does not wait for cleanup');
        await activate();
        await redis.hSet(control, { session_id: eventId });
        assert.equal((await fetch(url)).status, 404, 'Replacement does not read old session keys');
        await activate();
        await redis.set(key, JSON.stringify({ ...fixture, submitted: false }));
        assert.equal((await fetch(url)).status, 404, 'Unsubmitted data is never public');
        await redis.set(key, '{corrupt');
        assert.equal((await fetch(url)).status, 503, 'Corruption cannot establish absence');
        await redis.del([control, key, unrelated]);
        redis.destroy();
        assert.equal((await fetch(url)).status, 503);
        assert.equal((await observations(base, start, start + 10000)).status, 503);
      });
    } finally {
      if (ownsFixture && redis.isReady) await redis.del([control, key, unrelated]);
      if (redis.isOpen) redis.destroy();
    }
  });
