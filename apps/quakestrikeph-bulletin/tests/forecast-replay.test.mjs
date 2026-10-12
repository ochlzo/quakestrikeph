import assert from 'node:assert/strict';
import test from 'node:test';
import { ReplayController } from '../src/features/forecast-replay/controller.ts';

const origin = Date.parse('2026-10-01T00:00:00.000Z');
const minute = 60000, day = 86400000;
const event = {
  eventId: 'anchor', eventTime: new Date(origin).toISOString(), magnitude: 3, depthKm: 10,
  latitude: 13, longitude: 121, locationDescription: 'Fixture',
  source: { provider: 'PHIVOLCS', url: 'https://example.invalid/' },
  forecast: { windowStart: new Date(origin).toISOString(), windowEnd: new Date(origin + day).toISOString() },
};
const observation = (id, minutes) => ({ ...event, eventId: id, eventTime: new Date(origin + minutes * minute).toISOString() });
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function setup(t, nowMinutes = 5000) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  let now = origin + nowMinutes * minute;
  const requests = [], snapshots = [], notices = [];
  const controller = new ReplayController(event, {
    now: () => now,
    load(from, to) {
      let resolve, reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      requests.push({ from, to, resolve, reject });
      return promise;
    },
    onChange: snapshot => snapshots.push(snapshot),
    onLoadError: () => notices.push('error'),
    onLoadSuccess: () => notices.push('loaded'),
  });
  t.after(() => controller.dispose());
  return {
    controller, requests, snapshots, notices,
    setNow: minutes => { now = origin + minutes * minute; },
    advance: async milliseconds => { t.mock.timers.tick(milliseconds); await settle(); },
    ready: async (items = []) => { controller.start(); requests[0].resolve(items); await settle(); },
  };
}

test('startup is inert until start, idempotent, and bounded by Now', async t => {
  const f = setup(t, 67);
  assert.equal(f.requests.length, 0);
  assert.equal(f.controller.snapshot.ready, false);
  f.controller.start();
  f.controller.start();
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].from, event.forecast.windowStart);
  assert.equal(f.requests[0].to, new Date(origin + 67 * minute + 1).toISOString());
  f.requests[0].resolve([event, observation('same-instant', 0), observation('future', 68)]);
  await settle();
  assert.equal(f.controller.snapshot.ready, true);
  assert.equal(f.controller.snapshot.loadStatus, 'complete');
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['same-instant']);
});

test('startup preloads only the original forecast day and paints the newer selection', async t => {
  const f = setup(t);
  f.controller.start();
  assert.equal(f.requests[0].to, event.forecast.windowEnd);
  f.controller.seek('replay', 60);
  await f.advance(150);
  assert.equal(f.requests.length, 1, 'Startup and seeking share the pending chunk');
  f.requests[0].resolve([observation('one-hour', 60)]);
  await settle();
  assert.equal(f.controller.snapshot.replayMinutes, 60);
  assert.equal(f.controller.snapshot.ready, true);
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['one-hour']);
});

test('playback waits for completeness, resumes, and pauses at the original forecast end', async t => {
  const f = setup(t);
  await f.ready();
  f.controller.seek('replay', 1425);
  f.controller.setPlaying(true);
  await settle();
  assert.equal(f.requests.length, 2, 'Prefetch includes the exact end instant, but no later day');
  assert.equal(f.requests[1].from, event.forecast.windowEnd);
  await f.advance(300);
  assert.equal(f.controller.snapshot.replayMinutes, 1437);
  assert.equal(f.controller.snapshot.playing, true);
  assert.equal(f.controller.snapshot.loadStatus, 'loading');
  await f.advance(500);
  assert.equal(f.controller.snapshot.replayMinutes, 1437, 'Waiting must not skip uncovered observations');
  f.requests[1].resolve([observation('end-instant', 1440)]);
  await settle();
  await f.advance(100);
  assert.equal(f.controller.snapshot.replayMinutes, 1440);
  assert.equal(f.controller.snapshot.playing, false);
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['end-instant']);
  f.controller.setPlaying(true);
  await f.advance(100);
  assert.equal(f.controller.snapshot.replayMinutes, 1446, 'A second Play continues beyond the forecast');
  assert.equal(f.requests.length, 2);
});

test('seeking preserves snapping, the exact Now limit, and the observation range ordering', async t => {
  const f = setup(t, 67);
  await f.ready();
  f.controller.seek('replay', 22);
  assert.equal(f.controller.snapshot.replayMinutes, 15);
  f.controller.seek('replay', 1440);
  assert.equal(f.controller.snapshot.replayMinutes, 67);
  f.controller.seek('history', 1440);
  assert.equal(f.controller.snapshot.rangeStartMinutes, 67);
  f.controller.seek('replay', 0);
  assert.equal(f.controller.snapshot.replayMinutes, 67);
  f.controller.seek('history', -1440);
  assert.equal(f.controller.snapshot.rangeStartMinutes, -1440, 'Earlier observations remain selectable');
  f.controller.reset();
  assert.equal(f.controller.snapshot.replayMinutes, 0);
  assert.equal(f.controller.snapshot.rangeStartMinutes, 0);
});

test('playback freezes Now until an interaction refreshes it and retains the selected speed', async t => {
  const f = setup(t, 67);
  await f.ready([observation('available', 60), observation('future', 68)]);
  f.controller.seek('replay', 60);
  f.setNow(200);
  f.controller.setPlaying(true);
  await f.advance(200);
  assert.equal(f.controller.snapshot.replayMinutes, 67);
  assert.equal(f.controller.snapshot.playing, false);
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['available']);
  f.controller.refreshNow();
  f.controller.setPlaybackSpeed(2);
  f.controller.setPlaying(true);
  await settle();
  assert.equal(f.requests[1].to, new Date(origin + 200 * minute + 1).toISOString());
  await f.advance(100);
  assert.equal(f.controller.snapshot.replayMinutes, 67, 'Extended Now must load before advancing');
  f.requests[1].resolve([]);
  await settle();
  await f.advance(100);
  assert.equal(f.controller.snapshot.replayMinutes, 79);
  f.controller.reset();
  assert.equal(f.controller.snapshot.playing, false);
  assert.equal(f.controller.snapshot.playbackSpeed, 2);
});

test('reset suppresses obsolete success callbacks and stops sequential history loading', async t => {
  const f = setup(t);
  await f.ready();
  f.controller.seek('history', -2880);
  await f.advance(150);
  assert.equal(f.requests.length, 2);
  f.controller.reset();
  const snapshot = f.controller.snapshot, count = f.snapshots.length;
  f.requests[1].resolve([observation('obsolete', -2800)]);
  await settle();
  assert.equal(f.controller.snapshot, snapshot);
  assert.equal(f.snapshots.length, count);
  assert.equal(f.requests.length, 2, 'Obsolete selection must not request its remaining chunks');
  assert.deepEqual(f.notices, []);
});

test('a newer seek suppresses obsolete failures and retains its own request', async t => {
  const f = setup(t);
  await f.ready();
  f.controller.seek('history', -2880);
  await f.advance(150);
  f.controller.seek('history', -1440);
  await f.advance(150);
  assert.equal(f.requests.length, 3);
  const snapshot = f.controller.snapshot;
  f.requests[1].reject(new Error('Obsolete failure'));
  await settle();
  assert.equal(f.controller.snapshot, snapshot);
  assert.deepEqual(f.notices, []);
  f.requests[2].resolve([observation('selected', -1200)]);
  await settle();
  assert.equal(f.controller.snapshot.rangeStartMinutes, -1440);
  assert.equal(f.controller.snapshot.loadStatus, 'complete');
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['selected']);
  assert.deepEqual(f.notices, ['loaded']);
});

test('partial loading failure keeps observations and Retry reuses successful chunks', async t => {
  const f = setup(t);
  await f.ready();
  f.controller.seek('history', -2880);
  await f.advance(150);
  f.requests[1].resolve([observation('earlier', -2800)]);
  await settle();
  f.requests[2].reject(new Error('Offline'));
  await settle();
  assert.equal(f.controller.snapshot.loadStatus, 'incomplete');
  assert.equal(f.controller.snapshot.playing, false);
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['earlier']);
  assert.deepEqual(f.notices, ['error']);
  f.controller.retry();
  assert.equal(f.requests.length, 4);
  assert.equal(f.requests[3].from, new Date(origin - day).toISOString());
  f.requests[3].resolve([observation('later', -1200)]);
  await settle();
  assert.equal(f.controller.snapshot.loadStatus, 'complete');
  assert.deepEqual(f.controller.snapshot.observations.map(item => item.eventId), ['earlier', 'later']);
  assert.deepEqual(f.notices, ['error', 'loaded']);
});

test('startup failure enables Play and permits Retry', async t => {
  const f = setup(t);
  f.controller.start();
  f.requests[0].reject(new Error('Offline'));
  await settle();
  assert.equal(f.controller.snapshot.ready, true);
  assert.equal(f.controller.snapshot.loadStatus, 'incomplete');
  f.controller.retry();
  f.requests[1].resolve([]);
  await settle();
  assert.equal(f.controller.snapshot.loadStatus, 'complete');
  assert.deepEqual(f.notices, ['error', 'loaded']);
});

for (const outcome of ['resolve', 'reject']) {
  test(`disposal suppresses startup ${outcome} callbacks`, async t => {
    const f = setup(t);
    f.controller.start();
    f.controller.dispose();
    const snapshot = f.controller.snapshot;
    f.requests[0][outcome](outcome === 'resolve' ? [] : new Error('After disposal'));
    await settle();
    assert.equal(f.controller.snapshot, snapshot);
    assert.deepEqual(f.snapshots, []);
    assert.deepEqual(f.notices, []);
  });
}

test('disposal stops playback', async t => {
  const playback = setup(t);
  await playback.ready();
  playback.controller.setPlaying(true);
  playback.controller.dispose();
  const snapshot = playback.controller.snapshot, count = playback.snapshots.length;
  await playback.advance(1000);
  assert.equal(playback.controller.snapshot, snapshot);
  assert.equal(playback.snapshots.length, count);
  assert.equal(playback.requests.length, 1);
});

test('disposal stops pending debounce work and subsequent commands', async t => {
  const seeking = setup(t);
  await seeking.ready();
  seeking.controller.seek('history', -2880);
  seeking.controller.dispose();
  await seeking.advance(1000);
  seeking.controller.start();
  seeking.controller.retry();
  seeking.controller.reset();
  seeking.controller.seek('replay', 60);
  seeking.controller.setPlaying(true);
  assert.equal(seeking.requests.length, 1);
});

test('disposal prevents later chunks and notifications after an in-flight selection load', async t => {
  const f = setup(t);
  await f.ready();
  f.controller.seek('history', -2880);
  await f.advance(150);
  f.controller.dispose();
  const count = f.snapshots.length;
  f.requests[1].resolve([]);
  await settle();
  assert.equal(f.requests.length, 2);
  assert.equal(f.snapshots.length, count);
  assert.deepEqual(f.notices, []);
});
