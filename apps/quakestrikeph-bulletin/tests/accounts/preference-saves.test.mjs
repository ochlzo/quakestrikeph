import assert from 'node:assert/strict';
import test from 'node:test';
import { PreferenceSaves } from '../../src/features/accounts/preference-saves.ts';

const account = { userId: 'fixture-user', displayName: 'Test', email: 'fixture@example.invalid',
  phone: null, status: 'active', onboardingCompleted: true, emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: 14.6, longitude: 121, distanceKm: 50 };
const tick = () => new Promise(resolve => setTimeout(resolve, 15));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('debounces switches and combines only committed settings', async () => {
  const writes = [];
  const queue = new PreferenceSaves(account, async body => { writes.push(body); return { ...account, ...body }; }, assert.fail);
  queue.save({ emailEnabled: true }, 5);
  queue.save({ emailEnabled: false, nearbyOnly: true }, 5);
  assert.equal(queue.snapshot.preferences.nearbyOnly, true);
  assert.equal(writes.length, 0);
  await tick();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].emailEnabled, false);
  assert.equal(writes[0].nearbyOnly, true);
  assert.equal(writes[0].magnitude, 4.5);
});

test('serializes writes and preserves newer edits when an older write fails', async () => {
  const first = deferred(), second = deferred(), writes = [], errors = [];
  const queue = new PreferenceSaves(account, body => { writes.push(body); return writes.length === 1 ? first.promise : second.promise; }, error => errors.push(error));
  queue.save({ magnitude: 6 }, 0);
  await tick();
  queue.save({ magnitude: 7, emailEnabled: true }, 0);
  await tick();
  assert.equal(writes.length, 1);
  first.reject(new Error('First save failed'));
  await tick();
  assert.equal(writes.length, 2);
  assert.equal(writes[1].magnitude, 7);
  assert.equal(writes[1].emailEnabled, true);
  assert.equal(queue.snapshot.preferences.magnitude, 7);
  second.resolve({ ...account, ...writes[1] });
  await tick();
  assert.deepEqual(errors, ['First save failed']);
  assert.equal(queue.snapshot.account.magnitude, 7);
});

test('navigation unsubscribe does not cancel saves or error notifications; failures roll back', async () => {
  const response = deferred(), errors = [];
  const queue = new PreferenceSaves(account, () => response.promise, error => errors.push(error));
  const unsubscribe = queue.subscribe(() => {});
  queue.save({ emailEnabled: true }, 0);
  unsubscribe();
  await tick();
  queue.refresh(account); // A newly mounted page can read old server values.
  assert.equal(queue.snapshot.preferences.emailEnabled, true);
  response.reject(new Error('Save failed after navigation'));
  await tick();
  assert.equal(queue.snapshot.preferences.emailEnabled, false);
  assert.deepEqual(errors, ['Save failed after navigation']);
});

test('changing identity cancels pending work and suppresses old account notifications', async () => {
  const errors = [], response = deferred();
  const queue = new PreferenceSaves(account, () => response.promise, error => errors.push(error));
  queue.save({ emailEnabled: true }, 0);
  await tick();
  queue.cancel();
  response.reject(new Error('Old account failure'));
  await tick();
  assert.deepEqual(errors, []);
});
