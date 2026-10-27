import assert from 'node:assert/strict';
import test from 'node:test';
import { EventResults } from '../src/features/event-results/results.ts';
import { prepareEventResults } from '../src/features/event-results/server.ts';
import { eventSearch } from '../src/features/event-results/search.ts';
import { readEarthquakeCache, writeEarthquakeCache } from '../src/lib/earthquake-cache.ts';

const state = (patch = {}) => ({ query: '', date: { value: 'all' }, magnitudes: [], selectedId: null, ...patch });
const event = (index, patch = {}) => ({
  eventId: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  eventTime: '2026-10-05T04:00:00.000Z', magnitude: 3.5, depthKm: 10,
  latitude: 13, longitude: 123, locationDescription: `Test location ${index}`, forecast: null, ...patch,
});
const page = (items, nextCursor = null) => ({ items, nextCursor, hasMore: Boolean(nextCursor), fetchedAt: '2026-10-05T05:00:00.000Z' });
const detail = item => ({ ...item, eventRevisionId: item.eventId, origin: null,
  source: { provider: 'PHIVOLCS', url: 'https://earthquake.phivolcs.dost.gov.ph/' },
  forecastAvailability: { status: 'unavailable', reason: 'unknown' } });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const settle = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

function setup(t, { initial = null, filters = state(), saved = null, unavailable = false } = {}) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const searches = [], details = [], notices = [], entries = new Map();
  let reads = 0;
  const storage = {
    getItem(key) {
      reads++;
      if (unavailable) throw new Error('Storage unavailable');
      return entries.get(key) ?? null;
    },
    setItem(key, value) {
      if (unavailable) throw new Error('Storage unavailable');
      entries.set(key, value);
    },
  };
  if (saved) writeEarthquakeCache(eventSearch(filters), saved, storage);
  const results = new EventResults(filters, initial, {
    search: (request, signal) => {
      const pending = { request, signal, ...deferred() };
      searches.push(pending);
      return pending.promise;
    },
    detail: (eventId, signal) => {
      const pending = { eventId, signal, ...deferred() };
      details.push(pending);
      return pending.promise;
    },
    readCache: request => readEarthquakeCache(request, storage),
    writeCache: (request, data) => writeEarthquakeCache(request, data, storage),
    refreshFailed: () => notices.push('Refresh failed'),
  });
  t.after(() => results.stop());
  const advance = async (milliseconds = 300) => { t.mock.timers.tick(milliseconds); await settle(); };
  return { results, searches, details, notices, storage, entries, reads: () => reads, advance };
}

test('server preparation shares criteria, bounds rows, and permits browser fallback', async () => {
  const filters = state({ query: ' Test ', date: { value: 'custom', from: '2026-10-01T00:00:00Z', to: '2026-10-06T00:00:00Z' }, magnitudes: ['mag-3'] });
  const response = page(Array.from({ length: 40 }, (_, index) => event(index)), 'server-cursor');
  const initial = await prepareEventResults(filters, async (request, signal) => {
    assert.deepEqual(request, { limit: 30, location: 'Test', dateFrom: filters.date.from,
      dateTo: filters.date.to, magnitudeRanges: [{ from: 3, below: 4 }] });
    assert(signal instanceof AbortSignal);
    return response;
  });
  assert.equal(initial.items.length, 30);
  assert.equal(initial.nextCursor, 'server-cursor');
  const shortQuery = await prepareEventResults(state({ query: ' a ' }), async request => {
    assert.equal(request.location, undefined);
    return page([event(1)]);
  });
  assert.equal(shortQuery.items.length, 1);
  assert.equal(await prepareEventResults(state(), async () => { throw new Error('Unavailable'); }), null);
});

test('construction is inert; server rows take precedence and pagination waits for browser refresh', async t => {
  const seed = page([event(1)], 'server-cursor');
  const f = setup(t, { initial: seed, saved: page([event(9)]) });
  const initialSnapshot = f.results.getSnapshot();
  assert.equal(f.results.getSnapshot(), initialSnapshot);
  assert.equal(f.results.getServerSnapshot(), initialSnapshot);
  assert.equal(f.reads(), 0);
  assert.equal(f.searches.length, 0);
  assert.equal(f.results.getSnapshot().canLoadMore, false);
  const snapshots = [];
  const unsubscribe = f.results.subscribe(() => snapshots.push(f.results.getSnapshot()));
  f.results.start();
  f.results.start();
  assert.equal(f.reads(), 0, 'Initial server rows must skip older storage');
  assert(snapshots.every(snapshot => snapshot.events[0].eventId === event(1).eventId && !snapshot.searching));
  await f.results.nextPage();
  assert.equal(f.searches.length, 0);
  await f.advance(0);
  assert.equal(f.searches.length, 1);
  f.searches[0].resolve(page([event(2)], 'browser-cursor'));
  await settle();
  assert.equal(f.results.getSnapshot().canLoadMore, true);
  const loading = f.results.nextPage();
  assert.equal(f.searches[1].request.cursor, 'browser-cursor');
  f.searches[1].resolve(page([event(2), event(3)]));
  await loading;
  assert.deepEqual(f.results.getSnapshot().events.map(item => item.eventId), [event(2).eventId, event(3).eventId]);
  assert.deepEqual(readEarthquakeCache(eventSearch(state()), f.storage).items, [event(2)]);
  assert.equal(f.results.getServerSnapshot(), initialSnapshot, 'Hydration must retain its fixed initialization snapshot');
  unsubscribe();
});

test('matching cache remains visible on refresh failure, without a reusable cursor', async t => {
  const f = setup(t, { saved: page([event(1)], 'old-cursor') });
  f.results.start();
  assert.equal(f.results.getSnapshot().events[0].eventId, event(1).eventId);
  assert.equal(f.results.getSnapshot().searching, false);
  assert.equal(f.results.getSnapshot().canLoadMore, false);
  await f.advance();
  f.searches[0].reject(new Error('Offline'));
  await settle();
  assert.deepEqual(f.notices, ['Refresh failed']);
  assert.equal(f.results.getSnapshot().status, 'ready');
  assert.equal(f.results.getSnapshot().events.length, 1);
});

test('server rows survive setup cleanup and reactivation when storage is unavailable', async t => {
  const f = setup(t, { initial: page([event(1)]), unavailable: true });
  f.results.start();
  f.results.stop();
  await f.advance();
  assert.equal(f.searches.length, 0, 'Cleanup must cancel a pending debounce');
  f.results.start();
  assert.equal(f.results.getSnapshot().searching, false);
  assert.equal(f.results.getSnapshot().events[0].eventId, event(1).eventId);
  await f.advance();
  f.searches[0].reject(new Error('Refresh unavailable'));
  await settle();
  assert.equal(f.results.getSnapshot().events.length, 1);
  assert.deepEqual(f.notices, ['Refresh failed']);
});

test('missing fallback shows an error and retry recovers; unavailable storage never blocks live results', async t => {
  const f = setup(t, { unavailable: true });
  f.results.start();
  assert.equal(f.results.getSnapshot().searching, true);
  await f.advance();
  f.searches[0].reject(new Error('Offline'));
  await settle();
  assert.equal(f.results.getSnapshot().failed, true);
  assert.equal(f.results.getSnapshot().searching, false);
  f.results.refresh();
  await f.advance();
  f.searches[1].resolve(page([event(1)]));
  await settle();
  assert.equal(f.results.getSnapshot().failed, false);
  assert.equal(f.results.getSnapshot().events.length, 1);
  assert.deepEqual(f.notices, []);
});

test('obsolete searches cannot replace rows, cache, errors, or cursor after filters change', async t => {
  const f = setup(t);
  f.results.start();
  await f.advance();
  f.results.changeFilters({ query: 'north' });
  await f.advance();
  f.results.changeFilters({ query: 'south' });
  await f.advance();
  assert(f.searches[0].signal.aborted);
  assert(f.searches[1].signal.aborted);
  f.searches[2].resolve(page([event(3, { locationDescription: 'south' })], 'south-cursor'));
  await settle();
  const accepted = f.results.getSnapshot();
  f.searches[0].resolve(page([event(1)], 'obsolete-cursor'));
  f.searches[1].reject(new Error('Obsolete failure'));
  await settle();
  assert.equal(f.results.getSnapshot(), accepted);
  assert.equal(readEarthquakeCache(eventSearch(accepted.state), f.storage).items[0].eventId, event(3).eventId);
  assert.deepEqual(f.notices, []);
  const loading = f.results.nextPage();
  assert.equal(f.searches[3].request.cursor, 'south-cursor');
  f.searches[3].resolve(page([]));
  await loading;
});

test('short queries preserve the last applied search, results, selection and pagination', async t => {
  const f = setup(t, { filters: state({ query: 'Albay' }), initial: page([event(1)], 'next-page') });
  f.results.start();
  await f.advance();
  f.searches[0].resolve(page([event(1)], 'next-page'));
  await settle();
  f.results.select(event(1).eventId);
  f.details[0].resolve(detail(event(1)));
  await settle();
  const before = f.results.getSnapshot();
  for (const query of ['a', '', '   ']) {
    f.results.changeFilters({ query });
    await f.advance();
    assert.equal(f.results.getSnapshot(), before);
    assert.equal(f.searches.length, 1);
  }
  f.results.changeFilters({ query: 'ab' });
  await f.advance();
  assert.equal(f.searches.length, 2);
  assert.equal(f.searches[1].request.location, 'ab');
});

test('changing filters invalidates pending pagination before its response arrives', async t => {
  const f = setup(t);
  f.results.start();
  await f.advance();
  f.searches[0].resolve(page([event(1)], 'first-cursor'));
  await settle();
  const more = f.results.nextPage();
  f.results.changeFilters({ query: 'new' });
  assert(f.searches[1].signal.aborted);
  assert.equal(f.results.getSnapshot().events.length, 0);
  await f.advance();
  f.searches[2].resolve(page([event(3)], 'new-cursor'));
  await settle();
  const accepted = f.results.getSnapshot();
  f.searches[1].resolve(page([event(2)], 'obsolete-cursor'));
  await more;
  assert.equal(f.results.getSnapshot(), accepted);
  const next = f.results.nextPage();
  assert.equal(f.searches[3].request.cursor, 'new-cursor');
  f.searches[3].resolve(page([]));
  await next;
});

test('pagination permits one request, retains rows on failure, retries, and keeps the first page cache', async t => {
  const items = Array.from({ length: 30 }, (_, index) => event(index));
  const f = setup(t);
  f.results.start();
  await f.advance();
  f.searches[0].resolve(page(items, 'cursor'));
  await settle();
  const first = f.results.nextPage();
  await f.results.nextPage();
  assert.equal(f.searches.length, 2);
  f.searches[1].reject(new Error('Page unavailable'));
  await first;
  assert.equal(f.results.getSnapshot().pageStatus, 'error');
  assert.equal(f.results.getSnapshot().events.length, 30);
  const retry = f.results.nextPage();
  f.searches[2].resolve(page([event(0), event(30)]));
  await retry;
  assert.equal(f.results.getSnapshot().events.length, 2);
  assert.equal(f.results.getSnapshot().canLoadMore, false);
  assert.equal(readEarthquakeCache(eventSearch(state()), f.storage).items.length, 30);
});

test('previous page restores its cursor; row size cancels pending paging and resets to page one', async t => {
  const f = setup(t);
  f.results.start();
  await f.advance();
  f.searches[0].resolve(page([event(1)], 'first-cursor'));
  await settle();
  const next = f.results.nextPage();
  f.searches[1].resolve(page([event(2)], 'second-cursor'));
  await next;
  assert.equal(f.results.getSnapshot().pageNumber, 2);
  assert.deepEqual(f.results.getSnapshot().events, [event(2)]);
  f.results.previousPage();
  assert.equal(f.results.getSnapshot().pageNumber, 1);
  assert.deepEqual(f.results.getSnapshot().events, [event(1)]);
  const pending = f.results.nextPage();
  assert.equal(f.searches[2].request.cursor, 'first-cursor');
  f.results.changePageSize(100);
  assert(f.searches[2].signal.aborted);
  await f.advance();
  assert.equal(f.searches[3].request.limit, 100);
  assert.equal(f.searches[3].request.cursor, undefined);
  const items = Array.from({ length: 100 }, (_, index) => event(index));
  f.searches[3].resolve(page(items, 'large-cursor'));
  await settle();
  f.searches[2].resolve(page([event(9)]));
  await pending;
  assert.equal(f.results.getSnapshot().pageNumber, 1);
  assert.equal(f.results.getSnapshot().pageSize, 100);
  assert.deepEqual(f.results.getSnapshot().events, items);
  assert.equal(readEarthquakeCache(eventSearch(state(), 100), f.storage).items.length, 100);
  const largeNext = f.results.nextPage();
  assert.equal(f.searches[4].request.limit, 100);
  assert.equal(f.searches[4].request.cursor, 'large-cursor');
  f.searches[4].resolve(page([event(101)]));
  await largeNext;
  f.results.changeFilters({ magnitudes: ['mag-3'] });
  await f.advance();
  assert.equal(f.results.getSnapshot().pageNumber, 1);
  assert.equal(f.searches[5].request.limit, 100);
  assert.equal(f.searches[5].request.cursor, undefined);
});

test('obsolete detail responses are ignored and detail stays independent of list refresh', async t => {
  const f = setup(t, { initial: page([event(1), event(2)]) });
  f.results.start();
  await f.advance();
  f.searches[0].resolve(page([event(1), event(2)]));
  await settle();
  f.results.select(event(1).eventId);
  f.results.select(event(2).eventId);
  assert(f.details[0].signal.aborted);
  f.details[1].resolve(detail(event(2)));
  await settle();
  const accepted = f.results.getSnapshot();
  f.details[0].resolve(detail(event(1)));
  await settle();
  assert.equal(f.results.getSnapshot(), accepted);
  f.results.select(event(2).eventId);
  assert.equal(f.details.length, 2);
  f.results.refresh();
  await f.advance();
  f.searches[1].resolve(page([event(1)]));
  await settle();
  assert.equal(f.details.length, 2);
  assert.equal(f.results.getSnapshot().selected.eventId, event(2).eventId, 'Detail restores selection outside the refreshed first page');
  assert.equal(f.results.getSnapshot().detailStatus, 'ready');
  f.results.changeFilters({ query: 'different' });
  assert.equal(f.results.getSnapshot().state.selectedId, null);
  assert.equal(f.results.getSnapshot().selectedDetail, null);
});

test('initial selection outside the first page must satisfy active filters', async t => {
  const filters = state({ query: 'Test', magnitudes: ['mag-3'], date: { value: 'custom', from: '2026-10-05T00:00:00Z', to: '2026-10-06T00:00:00Z' }, selectedId: event(2).eventId });
  const f = setup(t, { filters, initial: page([event(1)]) });
  f.results.start();
  f.details[0].resolve(detail(event(2, { magnitude: 4 })));
  await settle();
  assert.equal(f.results.getSnapshot().selected, undefined, 'Exclusive magnitude upper bound must prevent restoration');
  assert.equal(f.results.getSnapshot().events.length, 1);
  f.results.select(event(2).eventId);
  f.details[1].resolve(detail(event(2)));
  await settle();
  assert.equal(f.results.getSnapshot().selected.eventId, event(2).eventId);
  assert.equal(f.results.getSnapshot().events.length, 2);
});

test('detail failure affects selection only, while stopped work cannot update a restarted controller', async t => {
  const f = setup(t, { initial: page([event(1)]), filters: state({ selectedId: event(1).eventId }) });
  f.results.start();
  await f.advance();
  f.details[0].reject(new Error('Detail unavailable'));
  await settle();
  assert.equal(f.results.getSnapshot().detailStatus, 'error');
  assert.equal(f.results.getSnapshot().events.length, 1);
  f.results.stop();
  assert(f.searches[0].signal.aborted);
  f.results.start();
  await f.advance();
  f.searches[1].resolve(page([event(1)]));
  f.details[1].resolve(detail(event(1)));
  await settle();
  const accepted = f.results.getSnapshot();
  f.searches[0].reject(new Error('Old work failed'));
  await settle();
  assert.equal(f.results.getSnapshot(), accepted);
  assert.deepEqual(f.notices, []);
  f.results.stop();
  f.results.refresh();
  await f.advance();
  assert.equal(f.searches.length, 2, 'Stopped controllers must not issue requests');
});
