import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createApp } from '../../src/interface/http/app.js';
import type { SyntheticScenarioReader } from '../../src/ports/syntheticScenarioReader.js';
import type { EarthquakeReader } from '../../src/ports/earthquakeReader.js';
import { eventId } from './submittedScenario.js';

export async function publicWorkflow(reader: SyntheticScenarioReader | undefined, run: (base: string) => Promise<void>) {
  let productionReads = 0;
  const production: EarthquakeReader = {
    search: async () => { productionReads++; return []; },
    findById: async () => { productionReads++; return null; }, check: async () => {},
  };
  const server = createApp(production, () => new Date(), undefined, undefined, reader).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No test address');
  const base = `http://127.0.0.1:${address.port}/api/v1/earthquakes`;
  try {
    await run(base);
    assert.equal(productionReads, 0, 'Synthetic workflows never call production');
    assert.equal((await fetch(`${base}/${eventId}`)).status, 404);
    const list = await fetch(`${base}/search`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
    assert.deepEqual((await list.json() as { items: unknown[] }).items, []);
    assert.equal(productionReads, 2, 'Production remains usable independently');
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
}

export function observations(base: string, from: number, to: number, cursor?: string, limit = 1) {
  return fetch(`${base}/${eventId}/observations?test=true`, { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ dateFrom: new Date(from).toISOString(), dateTo: new Date(to).toISOString(), limit,
      ...(cursor ? { cursor } : {}) }) });
}
