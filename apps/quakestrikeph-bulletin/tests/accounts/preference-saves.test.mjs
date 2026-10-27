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

test('confirmed saves wait for the response and return failures without a duplicate toast', async () => {
  const response = deferred(), errors = [];
  const queue = new PreferenceSaves(account, () => response.promise, error => errors.push(error));
  let settled = false;
  const saving = queue.saveConfirmed({ distanceKm: 100 }).finally(() => { settled = true; });
  const rejected = assert.rejects(saving, /Location save failed/);
  await tick();
  assert.equal(settled, false);
  response.reject(new Error('Location save failed'));
  await rejected;
  assert.equal(queue.snapshot.preferences.distanceKm, 50);
  assert.deepEqual(errors, []);

  const retry = new PreferenceSaves(account, async body => ({ ...account, ...body }), assert.fail);
  assert.equal((await retry.saveConfirmed({ distanceKm: 100 })).distanceKm, 100);
});

test('identity cancellation rejects a pending confirmation and ignores its late response', async () => {
  const response = deferred();
  const queue = new PreferenceSaves(account, () => response.promise, assert.fail);
  const saving = assert.rejects(queue.saveConfirmed({ smsEnabled: true }), /session changed/);
  await tick();
  queue.cancel();
  await saving;
  response.resolve({ ...account, smsEnabled: true });
  await tick();
  assert.equal(queue.snapshot.account.smsEnabled, false);
});
