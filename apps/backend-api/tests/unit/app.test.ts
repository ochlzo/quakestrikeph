import assert from 'node:assert/strict';
import test from 'node:test';
import type { Server } from 'node:http';
import { once } from 'node:events';
import type { Earthquake } from '../../src/domain/information.js';
import type { EarthquakeReader } from '../../src/ports/earthquakeReader.js';
import { createApp } from '../../src/interface/http/app.js';
import { DataUnavailable } from '../../src/application/information/errors.js';

const event: Earthquake = {
  eventId: '11111111-1111-4111-8111-111111111111',
  eventRevisionId: '22222222-2222-4222-8222-222222222222',
  eventTime: '2026-09-25T02:00:00.000Z',
  magnitude: 4.2, latitude: 7.1, longitude: 125.6, depthKm: 12,
  locationDescription: 'Davao', origin: 'TECTONIC', sourceUrl: 'https://example.org/bulletin',
  forecast: null,
};

async function withServer(reader: EarthquakeReader, run: (base: string) => Promise<void>): Promise<void> {
  const server: Server = createApp(reader, () => new Date('2026-09-27T00:00:00Z')).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No test address');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally { server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve())); }
}

test('search returns a bounded page and detail keeps missing forecast explicit', async () => {
  const reader: EarthquakeReader = {
    search: async () => [event, { ...event, eventId: '33333333-3333-4333-8333-333333333333' }],
    findById: async () => event,
    check: async () => {},
  };
  await withServer(reader, async (base) => {
    const search = await fetch(`${base}/api/v1/earthquakes/search`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ limit: 1 }),
    });
    assert.equal(search.status, 200);
    const page = await search.json() as { items: Array<{ forecast: unknown }>; hasMore: boolean; nextCursor: string };
    assert.equal(page.items.length, 1);
    assert.equal(page.items[0]?.forecast, null);
    assert.equal(page.hasMore, true);
    assert.ok(page.nextCursor);
    assert.ok(search.headers.get('x-request-id'));
    const detail = await fetch(`${base}/api/v1/earthquakes/${event.eventId}`);
    assert.equal(detail.status, 200);
    const data = await detail.json() as { item: { forecast: unknown; source: { provider: string } } };
    assert.equal(data.item.forecast, null);
    assert.equal(data.item.source.provider, 'PHIVOLCS');
  });
});

test('invalid input and database outage return status and short messages', async () => {
  const reader: EarthquakeReader = {
    search: async () => { throw new DataUnavailable('private connection details'); },
    findById: async () => null,
    check: async () => {},
  };
  await withServer(reader, async (base) => {
    const bad = await fetch(`${base}/api/v1/earthquakes/search`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ limit: 0 }),
    });
    assert.equal(bad.status, 400);
    assert.match(JSON.stringify(await bad.json()), /INVALID_REQUEST/);
    const outage = await fetch(`${base}/api/v1/earthquakes/search`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
    });
    assert.equal(outage.status, 503);
    assert.doesNotMatch(JSON.stringify(await outage.json()), /private connection details/);
  });
});
