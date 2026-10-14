import assert from 'node:assert/strict';
import test from 'node:test';
import { DataUnavailable } from '../../src/application/information/errors.js';
import { projectSubmittedScenario } from '../../src/domain/submittedScenario.js';
import { submittedFixture, eventId, sessionId } from '../fixtures/submittedScenario.js';
import { observations, publicWorkflow } from '../fixtures/publicScenarioWorkflow.js';

test('submitted public projection, stable pagination, privacy, absence, validation and outage isolation', async () => {
  const deadline = Date.now() + 3600000, fixture = submittedFixture(deadline);
  const scenario = projectSubmittedScenario(fixture, sessionId, deadline, eventId)!;
  let state = 'active';
  await publicWorkflow({ findSubmitted: async id => {
    if (state === 'outage') throw new DataUnavailable('private credentials');
    return state === 'active' && id === eventId ? scenario : null;
  } }, async base => {
    const url = `${base}/${eventId}?test=true`;
    const first = await fetch(url);
    assert.equal(first.headers.get('cache-control'), 'no-store');
    const detail = await first.json() as { item: { source: { url: string }; forecast: { forecastId: string } }; expiresAt: string };
    assert.equal(detail.item.source.url, 'https://earthquake.phivolcs.dost.gov.ph/');
    assert.equal(detail.item.forecast.forecastId, fixture.forecast_id);
    assert.equal(detail.expiresAt, new Date(deadline).toISOString());
    assert.doesNotMatch(JSON.stringify(detail), /private|testers|deliveries|replay|submitted/);
    assert.deepEqual((await (await fetch(url)).json() as typeof detail).item, detail.item);
    const start = fixture.scenario.forecast.window_start_ms;
    let cursor: string | undefined;
    const ids: string[] = [];
    do {
      const response = await observations(base, start, start + 86400000, cursor);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get('cache-control'), 'no-store');
      const page = await response.json() as { items: { eventId: string }[]; nextCursor: string | null; hasMore: boolean };
      ids.push(...page.items.map(item => item.eventId));
      assert.equal(page.items.length, 1);
      cursor = page.hasMore ? page.nextCursor! : undefined;
    } while (cursor);
    assert.deepEqual(ids, fixture.scenario.observations.map(item => item.event_id).reverse());
    const narrow = await (await observations(base, start + 2000, start + 3000, undefined, 100)).json() as { items: { eventId: string }[] };
    assert.deepEqual(narrow.items.map(item => item.eventId), [fixture.scenario.observations[1]!.event_id]);
    assert.equal((await observations(base, start, start + 86400001)).status, 400);
    state = 'absent';
    assert.equal((await fetch(url)).status, 404);
    assert.equal((await observations(base, start, start + 10000)).status, 404);
    state = 'outage';
    const failure = await fetch(url);
    assert.equal(failure.status, 503);
    assert.doesNotMatch(JSON.stringify(await failure.json()), /credentials/);
    assert.equal((await observations(base, start, start + 10000)).status, 503);
  });
});

test('submitted-record validation rejects inconsistent ownership and corrupt data without exposing private fields', () => {
  const deadline = Date.now() + 3600000;
  const fixture = submittedFixture(deadline);
  assert.equal(projectSubmittedScenario({ ...fixture, submitted: false }, sessionId, deadline, eventId), null);
  assert.throws(() => projectSubmittedScenario(fixture, eventId, deadline, eventId));
  assert.throws(() => projectSubmittedScenario(fixture, sessionId, deadline + 1, eventId));
  for (const change of [
    { p1: NaN }, { p5: .9 }, { radius_km: 0 }, { quantiles: [4, 1, 2] }, { window_end_ms: 0 },
  ]) {
    assert.throws(() => projectSubmittedScenario({ ...fixture, scenario: { ...fixture.scenario,
      forecast: { ...fixture.scenario.forecast, ...change } } }, sessionId, deadline, eventId));
  }
  const duplicate = { ...fixture, scenario: { ...fixture.scenario,
    observations: [fixture.scenario.observations[0], fixture.scenario.observations[0]] } };
  assert.throws(() => projectSubmittedScenario(duplicate, sessionId, deadline, eventId));
});

test('missing synthetic dependency is unavailable while production reads remain available', async () => {
  await publicWorkflow(undefined, async base => {
    const result = await fetch(`${base}/${eventId}?test=true`);
    assert.equal(result.status, 503);
    assert.equal(result.headers.get('cache-control'), 'no-store');
    const malformed = await fetch(`${base}/${eventId}/observations?test=true`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: '{bad',
    });
    assert.equal(malformed.status, 400);
    assert.equal(malformed.headers.get('cache-control'), 'no-store');
    assert.equal((await fetch(`${base}/${eventId}?test=true&test=true`)).status, 400);
  });
});
