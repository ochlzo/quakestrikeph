import assert from 'node:assert/strict';
import test from 'node:test';
import { encodeCursor, InvalidRequest, parseSearchRequest } from '../../src/interface/http/searchRequest.js';

test('search filters accept numeric range union, UTC-normalized dates and an opaque cursor', () => {
  const cursor = encodeCursor({ eventTime: '2026-09-27T02:00:00.000Z', eventId: '11111111-1111-4111-8111-111111111111' });
  assert.deepEqual(parseSearchRequest({
    magnitudeRanges: [{ below: 3 }, { from: 4, below: 5 }, { from: 5 }],
    dateFrom: '2026-09-27T10:00:00+08:00', location: '  DaVao  ', limit: 10, cursor,
  }), {
    magnitudeRanges: [{ below: 3 }, { from: 4, below: 5 }, { from: 5 }],
    dateFrom: '2026-09-27T02:00:00.000Z', dateTo: undefined, location: 'DaVao', limit: 10,
    cursor: { eventTime: '2026-09-27T02:00:00.000Z', eventId: '11111111-1111-4111-8111-111111111111' },
  });
  assert.equal(parseSearchRequest({}).limit, 25);
  assert.equal(parseSearchRequest({}).dateFrom, undefined);
});

test('reject invalid boundaries, dates, and cursors', () => {
  for (const body of [
    { magnitudeRanges: [{ from: 4, below: 4 }] },
    { magnitudeRanges: [{ from: 4, below: '5' }] },
    { magnitudeRanges: [{ from: 3, bogus: 4 }] },
    { dateFrom: '2026-02-30T00:00:00Z' },
    { dateFrom: '2026-09-27T00:00:00' },
    { dateFrom: '2026-09-28T00:00:00Z', dateTo: '2026-09-27T00:00:00Z' },
    { cursor: 'bad-cursor' },
    { limit: 101 },
    { location: '%' },
  ]) assert.throws(() => parseSearchRequest(body), InvalidRequest);
});
