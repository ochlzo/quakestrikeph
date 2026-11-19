import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { once } from 'node:events';
import type { AddressInfo } from 'node:net';
import test from 'node:test';
import { Pool, type PoolClient } from 'pg';
import { createClient } from 'redis';
import { SimulationGuestCookies } from '../../src/application/forecastSimulations.js';
import { PostgresEarthquakeReader } from '../../src/infrastructure/postgres/earthquakeQueries.js';
import { HttpForecastSimulator } from '../../src/infrastructure/simulator.js';
import { createApp } from '../../src/interface/http/app.js';

const databaseUrl = process.env.TEST_DATABASE_URL;
const backendUrl = process.env.TEST_BACKEND_DATABASE_URL;
const redisUrl = process.env.TEST_REDIS_URL;
const simulatorUrl = process.env.TEST_SIMULATION_SERVICE_URL;

const serviceToken = 'a1'.repeat(32);
const ingressKey = 'disposable-test-ingress';
const pageToken = 'disposable-test-page';
const quotaUser = 'forecast-simulator-test';
const modelStarted = 'forecast-simulation-test:model-started';
const modelRelease = 'forecast-simulation-test:model-release';
const catalogClock = 'forecast-simulation-test:catalog-now';
const runPath = '/api/v1/forecast-simulations';
const pagePath = '/internal/forecast-simulations/page';
const scenario = { latitude: 14.62, longitude: 120.91, magnitude: 5.24, depthKm: 18.5 };
const windowMs = 10 * 60_000;
const dayMs = 24 * 60 * 60_000;
const sevenWeeksMs = 49 * dayMs;
const cutoff = new Date('2026-11-19T12:00:00Z');
const initialCatalogTime = new Date(cutoff.getTime() + 60_000);
const utcTimestamp = (date: Date) => date.toISOString().replace('.000Z', 'Z');

function guestQuotaKey(cookie: string) {
  return `forecast-simulation:guest:${cookie.split('=')[1]!.split('.')[0]}`;
}

function ipQuotaKey(ip: string) {
  const bytes = Buffer.from(ip.split('.').map(Number));
  const hash = createHmac('sha256', Buffer.from(serviceToken, 'hex')).update(bytes).digest('hex');
  return `forecast-simulation:ip:${hash}`;
}

async function expectError(response: Response, status: number, code: string) {
  assert.equal(response.status, status);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const { error } = await response.json();
  assert.equal(error.code, code);
  return error;
}

test('forecast simulations through the public Backend HTTP route',
  { skip: !databaseUrl || !backendUrl || !redisUrl || !simulatorUrl, timeout: 60_000 }, async (t) => {
    assert(databaseUrl && backendUrl && redisUrl && simulatorUrl);
    for (const url of [databaseUrl, backendUrl].map((value) => new URL(value))) {
      assert.equal(url.hostname, 'postgres-test');
      assert.equal(url.pathname, '/quakestrike_test');
    }
    assert.equal(new URL(redisUrl).hostname, 'redis-test');
    const simulatorTarget = new URL(simulatorUrl);
    assert.equal(simulatorTarget.hostname, 'forecast-simulator-fixture');

    const db = new Pool({ connectionString: databaseUrl });
    const backendDb = new Pool({ connectionString: backendUrl });
    const redis = createClient({ url: redisUrl });
    const coverageRuns: string[] = [];
    const fixtureEvents: string[] = [];
    const quotaKeys = new Set<string>();
    t.after(async () => {
      // Each test uses its own guest IDs and documentation IP addresses.
      try {
        if (redis.isReady) await redis.del([...quotaKeys, modelStarted, modelRelease, catalogClock]);
        await db.query('DELETE FROM earthquake_event_revisions WHERE event_id = ANY($1::uuid[])', [fixtureEvents]);
        await db.query('DELETE FROM earthquake_events WHERE event_id = ANY($1::uuid[])', [fixtureEvents]);
        await db.query('DELETE FROM source_catalog_evidence WHERE run_id = ANY($1::uuid[])', [coverageRuns]);
        await db.query('DELETE FROM ingestion_runs WHERE run_id = ANY($1::uuid[])', [coverageRuns]);
      } finally {
        if (redis.isOpen) redis.destroy();
        await Promise.all([db.end(), backendDb.end()]);
      }
    });
    await redis.connect();
    const setCatalogClock = (time: Date) => redis.set(catalogClock, time.toISOString());
    await setCatalogClock(initialCatalogTime);
    const liveTables = [
      'earthquake_events', 'earthquake_event_revisions', 'prediction_jobs', 'prediction_attempts',
      'forecasts', 'job_dispatches', 'alert_jobs', 'alert_recipients', 'alert_delivery_attempts',
    ];
    const liveCounts = async () => (await db.query(
      `SELECT ${liveTables.map((table) => `(SELECT count(*) FROM ${table}) AS ${table}`).join(', ')}`,
    )).rows[0];
    const before = await liveCounts();

    let now = new Date();
    const guestKey = randomUUID();
    async function startBackend() {
      const reader = new PostgresEarthquakeReader(backendDb, randomUUID());
      const app = createApp(reader, () => now, undefined, undefined, undefined, {
        simulator: new HttpForecastSimulator(simulatorTarget, serviceToken),
        cookies: new SimulationGuestCookies(guestKey),
        pageToken,
        ingressKey,
      });
      const server = app.listen(0, '127.0.0.1');
      t.after(() => {
        server.close();
        server.closeAllConnections();
      });
      await once(server, 'listening');
      return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    }
    const [first, second] = await Promise.all([startBackend(), startBackend()]);

    async function issueCookie() {
      const response = await fetch(first + pagePath, { headers: { Authorization: `Bearer ${pageToken}` } });
      assert.equal(response.status, 200);
      assert.equal((await response.json()).guestCookieConfirmed, false);
      const issued = response.headers.get('Set-Cookie');
      assert(issued);
      assert.match(issued, /Max-Age=86400/);
      assert.match(issued, /HttpOnly; Secure; SameSite=Lax/);
      const cookie = issued.split(';')[0]!;
      quotaKeys.add(guestQuotaKey(cookie));
      return cookie;
    }

    async function confirmedPage(cookie: string) {
      const response = await fetch(second + pagePath + '?confirm=1', {
        headers: { Authorization: `Bearer ${pageToken}`, Cookie: cookie },
      });
      assert.equal(response.status, 200);
      assert.equal(response.headers.get('Set-Cookie'), null);
      return response.json();
    }

    function submit(base: string, cookie: string, ip: string, input = scenario, signal?: AbortSignal) {
      quotaKeys.add(ipQuotaKey(ip));
      return fetch(base + runPath, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json', Cookie: cookie,
          'X-Simulation-Ingress': ingressKey, 'CF-Connecting-IP': ip,
        },
        body: JSON.stringify(input),
        signal,
      });
    }

    async function quotaCounts(cookie: string, ip: string) {
      return Promise.all([redis.zCard(guestQuotaKey(cookie)), redis.zCard(ipQuotaKey(ip))]);
    }

    async function releaseModels(settled: Promise<unknown>) {
      await redis.rPush(modelRelease, ['release', 'release']);
      await settled;
      await redis.del([modelStarted, modelRelease]);
    }

    async function addCoverage(start: Date, end: Date, status: 'succeeded' | 'failed' = 'succeeded') {
      const runId = randomUUID();
      coverageRuns.push(runId);
      await db.query(`INSERT INTO ingestion_runs (run_id, trigger_type, status, started_at, finished_at, correlation_id)
        VALUES ($1, 'scheduled', $2, $3, $4, $5)`, [runId, status, start, end, randomUUID()]);
      await db.query(`INSERT INTO source_catalog_evidence
        (run_id, source_url, catalog_sha256, retrieved_at, coverage_start, coverage_end, accepted_rows)
        VALUES ($1, 'https://example.org/catalog', $2, $3, $4, $3, 1)`, [runId, 'b'.repeat(64), end, start]);
      return runId;
    }

    await t.test('rejects missing cookies, invalid scenarios and unavailable history before charging', async () => {
      const ip = '192.0.2.83';
      const cookie = await issueCookie();
      await expectError(await submit(first!, '', ip), 403, 'SIMULATION_GUEST_COOKIE_REQUIRED');
      const invalid = await expectError(
        await submit(first!, cookie, ip, { ...scenario, depthKm: 700.01 }), 400, 'INVALID_REQUEST',
      );
      assert.equal(invalid.field, 'depthKm');
      await expectError(await submit(first!, cookie, ip), 503, 'SIMULATION_HISTORY_INSUFFICIENT');
      assert.deepEqual(await quotaCounts(cookie, ip), [0, 0]);
    });

    const coverageStart = new Date(cutoff.getTime() - 7 * dayMs);
    const split = new Date(cutoff.getTime() - 3 * dayMs);
    const afterGap = new Date(split.getTime() + 1);
    await addCoverage(coverageStart, split);
    const observationRun = await addCoverage(afterGap, cutoff);
    await addCoverage(split, afterGap, 'failed');

    await t.test('rejects a gap even when a failed run claims the missing coverage', async () => {
      const ip = '192.0.2.88';
      const cookie = await issueCookie();
      await expectError(await submit(first, cookie, ip), 503, 'SIMULATION_HISTORY_INSUFFICIENT');
      assert.deepEqual(await quotaCounts(cookie, ip), [0, 0]);

      await addCoverage(split, afterGap);
      const response = await submit(second, cookie, ip);
      assert.equal(response.status, 200);
      assert.equal((await response.json()).catalogCutoff, utcTimestamp(cutoff));
      assert.deepEqual(await quotaCounts(cookie, ip), [1, 1]);
    });

    await t.test('returns the original scenario and a validated 24-hour forecast without live writes', async () => {
      const ip = '192.0.2.84';
      const cookie = await issueCookie();
      assert.deepEqual(await confirmedPage(cookie), {
        guestCookieConfirmed: true, catalog: { status: 'current', catalogCutoff: utcTimestamp(cutoff) },
      });
      const response = await submit(second!, cookie, ip);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get('Cache-Control'), 'no-store');
      assert.deepEqual(await response.json(), {
        scenario,
        catalogCutoff: utcTimestamp(cutoff),
        forecast: {
          windowStart: utcTimestamp(cutoff),
          windowEnd: utcTimestamp(new Date(cutoff.getTime() + dayMs)),
          probabilityM1Plus24h: 0.6, probabilityM4Plus24h: 0.24, probabilityM5Plus24h: 0.06,
          expectedM1PlusCount24h: 0, maximumMagnitudeQ05_24h: 4.74,
          maximumMagnitudeQ50_24h: 5.24, maximumMagnitudeQ95_24h: 5.74,
          activityRadiusMedianKm24h: 50,
        },
      });
      assert.deepEqual(await quotaCounts(cookie, ip), [1, 1]);
      const issuedAt = now;
      try {
        now = new Date(issuedAt.getTime() + dayMs);
        await expectError(await submit(first!, cookie, ip), 403, 'SIMULATION_GUEST_COOKIE_REQUIRED');
        assert.deepEqual(await quotaCounts(cookie, ip), [1, 1]);
      } finally {
        now = issuedAt;
      }
      assert.deepEqual(await liveCounts(), before);
    });

    await t.test('enforces the 24-hour warning and seven-week admission boundary', async () => {
      const ip = '192.0.2.89';
      const cookie = await issueCookie();
      const cases = [
        [dayMs - 1, 'current'], [dayMs, 'current'], [dayMs + 1, 'stale'],
        [sevenWeeksMs - 1, 'stale'], [sevenWeeksMs, 'stale'], [sevenWeeksMs + 1, 'too_old'],
      ] as const;
      try {
        for (const [ageMs, status] of cases) {
          await setCatalogClock(new Date(cutoff.getTime() + ageMs));
          assert.deepEqual(await confirmedPage(cookie), {
            guestCookieConfirmed: true, catalog: { status, catalogCutoff: utcTimestamp(cutoff) },
          }, `Catalog status at age ${ageMs} ms`);
          const response = await submit(second, cookie, ip);
          if (status === 'too_old') {
            const error = await expectError(response, 503, 'SIMULATION_HISTORY_TOO_OLD');
            assert.equal(error.catalogCutoff, utcTimestamp(cutoff));
          } else {
            assert.equal(response.status, 200, `Admission at age ${ageMs} ms`);
            assert.equal((await response.json()).catalogCutoff, utcTimestamp(cutoff));
          }
        }
        assert.deepEqual(await quotaCounts(cookie, ip), [5, 5]);
      } finally {
        await setCatalogClock(initialCatalogTime);
      }
    });

    await t.test('shares rolling guest and public IP quotas across Backend instances', async () => {
      const ip = '192.0.2.85';
      const guest = await issueCookie();
      const otherGuest = await issueCookie();
      for (const base of [first!, second!, first!, second!, first!]) {
        const accepted = await submit(base, guest, ip);
        assert.equal(accepted.status, 200);
        await accepted.json();
      }
      const guestOnly = await submit(second!, guest, ip);
      const guestLimit = await expectError(guestOnly, 429, 'SIMULATION_LIMIT_REACHED');
      assert.match(guestOnly.headers.get('Retry-After') ?? '', /^\d+$/);
      assert.deepEqual(await quotaCounts(guest, ip), [5, 5]);

      // Put the shared IP one start short of its limit with older simulated admissions.
      const ipScore = Date.now() - 60_000;
      await redis.zAdd(ipQuotaKey(ip), Array.from({ length: 114 }, (_, i) => ({
        score: ipScore, value: `older-start-${i}`,
      })));
      const accepted = await submit(second!, otherGuest, ip);
      assert.equal(accepted.status, 200);
      await accepted.json();
      const ipLimit = await expectError(await submit(first!, otherGuest, ip), 429, 'SIMULATION_LIMIT_REACHED');
      const both = await expectError(await submit(second!, guest, ip), 429, 'SIMULATION_LIMIT_REACHED');
      assert.equal(Date.parse(ipLimit.retryAt), ipScore + windowMs);
      assert.equal(both.retryAt, guestLimit.retryAt);
      assert(Date.parse(both.retryAt) > Date.parse(ipLimit.retryAt));
      assert.deepEqual(await quotaCounts(guest, ip), [5, 120]);
      assert.deepEqual(await quotaCounts(otherGuest, ip), [1, 120]);

      // Age the IP's older admissions out of the window without advancing wall time.
      await redis.zAdd(ipQuotaKey(ip), Array.from({ length: 114 }, (_, i) => ({
        score: Date.now() - windowMs - 1000, value: `older-start-${i}`,
      })));
      const afterExpiry = await submit(first!, otherGuest, ip);
      assert.equal(afterExpiry.status, 200);
      await afterExpiry.json();
      assert.deepEqual(await quotaCounts(otherGuest, ip), [2, 7]);
    });

    await t.test('admits one concurrent request for the last guest or shared IP allowance', async () => {
      async function raceLastAdmission(firstGuest: string, secondGuest: string, ip: string) {
        const heldScenario = { ...scenario, magnitude: 9.2 };
        const requests = [submit(first, firstGuest, ip, heldScenario), submit(second, secondGuest, ip, heldScenario)];
        const settled = Promise.allSettled(requests);
        try {
          assert(await redis.blPop(modelStarted, 5), 'One request should hold a model slot');
          // The winner stays in inference while the second request reaches the quota check.
          await expectError(await Promise.race(requests), 429, 'SIMULATION_LIMIT_REACHED');
        } finally {
          await releaseModels(settled);
        }
        const responses = await Promise.all(requests);
        assert.deepEqual(responses.map((response) => response.status).sort(), [200, 429]);
        await responses.find((response) => response.status === 200)!.json();
      }

      const guestIp = '192.0.2.90';
      const guest = await issueCookie();
      for (let start = 0; start < 4; start++) {
        const response = await submit(first, guest, guestIp);
        assert.equal(response.status, 200);
        await response.json();
      }
      await raceLastAdmission(guest, guest, guestIp);
      assert.deepEqual(await quotaCounts(guest, guestIp), [5, 5]);

      const sharedIp = '192.0.2.91';
      const guests = [await issueCookie(), await issueCookie()] as const;
      const score = Date.now() - 60_000;
      await redis.zAdd(ipQuotaKey(sharedIp), Array.from({ length: 119 }, (_, index) => ({
        score, value: `older-start-${index}`,
      })));
      await raceLastAdmission(...guests, sharedIp);
      const counts = await Promise.all(guests.map((cookie) => quotaCounts(cookie, sharedIp)));
      assert.deepEqual(counts.map(([guestCount]) => guestCount).sort(), [0, 1]);
      assert.deepEqual(counts.map(([, ipCount]) => ipCount), [120, 120]);
    });

    await t.test('distinguishes quota unavailability and model failure and charges only the latter', async () => {
      const ip = '192.0.2.86';
      const cookie = await issueCookie();
      await redis.sendCommand(['ACL', 'SETUSER', quotaUser, '-ping']);
      try {
        await expectError(await submit(first!, cookie, ip), 503, 'SIMULATION_QUOTA_UNAVAILABLE');
        assert.deepEqual(await quotaCounts(cookie, ip), [0, 0]);
      } finally {
        await redis.sendCommand(['ACL', 'SETUSER', quotaUser, '+ping']);
      }
      await expectError(
        await submit(second!, cookie, ip, { ...scenario, magnitude: 9.1 }), 500, 'SIMULATION_MODEL_FAILED',
      );
      assert.deepEqual(await quotaCounts(cookie, ip), [1, 1]);
      assert.deepEqual(await liveCounts(), before);
    });

    await t.test('holds model slots and keeps the charge after a public client disconnects', async () => {
      const ip = '192.0.2.87';
      const guest = await issueCookie();
      const otherGuest = await issueCookie();
      const waitingGuest = await issueCookie();
      const disconnect = new AbortController();
      const heldScenario = { ...scenario, magnitude: 9.2 };
      const abandoned = submit(first, guest, ip, heldScenario, disconnect.signal);
      const held = submit(second, otherGuest, ip, heldScenario);
      const settled = Promise.allSettled([abandoned, held]);
      try {
        for (let slot = 0; slot < 2; slot++) {
          assert(await redis.blPop(modelStarted, 5), 'Both model slots should be in use before disconnect');
        }
        disconnect.abort();
        await assert.rejects(abandoned, { name: 'AbortError' });
        await expectError(await submit(second, waitingGuest, ip), 503, 'SIMULATION_BUSY');
        assert.deepEqual(await quotaCounts(guest, ip), [1, 2]);
        assert.deepEqual(await quotaCounts(waitingGuest, ip), [0, 2]);
        assert.deepEqual(await liveCounts(), before);
      } finally {
        disconnect.abort();
        await releaseModels(settled);
      }
      const completed = await held;
      assert.equal(completed.status, 200);
      await completed.json();
    });

    await t.test('uses the latest committed correction and excludes observations at or after the cutoff', async () => {
      async function addRevision(
        connection: Pool | PoolClient, eventId: string, revision: number, eventTime: Date,
        magnitude: number, ingestedAt: Date,
      ) {
        await connection.query(`INSERT INTO earthquake_event_revisions
          (event_revision_id, event_id, revision_number, ingestion_run_id, source_event_group_id, source_url,
           source_time_precision, event_time, latitude, longitude, depth_km, magnitude, location_description, ingested_at)
          VALUES ($1, $2, $3, $4, $5, 'https://example.org/bulletin', 'second', $6, 14.62, 120.91, 18, $7,
            'Sanitized event', $8)`, [randomUUID(), eventId, revision, observationRun,
          `GROUP_${eventId.slice(0, 8).toUpperCase()}`, eventTime, magnitude, ingestedAt]);
      }

      const beforeCutoff = new Date(cutoff.getTime() - 3600_000);
      for (const eventTime of [beforeCutoff, cutoff, initialCatalogTime]) {
        const eventId = randomUUID();
        fixtureEvents.push(eventId);
        await db.query(`INSERT INTO earthquake_events (event_id, first_seen_run_id, last_seen_run_id)
          VALUES ($1, $2, $2)`, [eventId, observationRun]);
        await addRevision(db, eventId, 1, eventTime, 2, initialCatalogTime);
      }

      const ip = '192.0.2.92';
      const cookie = await issueCookie();
      async function expectHistoryCount(count: number) {
        const response = await submit(second, cookie, ip);
        assert.equal(response.status, 200);
        const result = await response.json();
        assert.equal(result.catalogCutoff, utcTimestamp(cutoff));
        // The controlled model returns the seven-day input count as its expected count.
        assert.equal(result.forecast.expectedM1PlusCount24h, count);
      }

      await expectHistoryCount(1);
      const connection = await db.connect();
      try {
        await connection.query('BEGIN');
        await addRevision(connection, fixtureEvents[0]!, 2, beforeCutoff, 0.8, initialCatalogTime);
        await expectHistoryCount(1);
        await connection.query('COMMIT');
      } catch (error) {
        await connection.query('ROLLBACK');
        throw error;
      } finally {
        connection.release();
      }
      await expectHistoryCount(0);
    });
  });
