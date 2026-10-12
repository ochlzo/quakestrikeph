import assert from 'node:assert/strict';
import test from 'node:test';
import { LocationEdit, browserLocation } from '../../src/features/accounts/location-edit.ts';
import { PreferenceSaves } from '../../src/features/accounts/preference-saves.ts';

const saved = { latitude: 13.21667, longitude: 123.51667, distanceKm: 50 };
function fixture(location = saved) {
  const requests = [], failures = [];
  const edit = new LocationEdit(location, (success, failure) => requests.push({ success, failure }));
  return { edit, requests, failures, locate: () => edit.locate(message => failures.push(message)) };
}
const tick = () => new Promise(resolve => setTimeout(resolve, 15));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

test('initial state and default distance do not count as edits', () => {
  const { edit } = fixture({ latitude: null, longitude: null, distanceKm: null });
  assert.equal(edit.snapshot.editing, false);
  assert.equal(edit.snapshot.distance, '50');
  edit.begin();
  assert.equal(edit.snapshot.dirty, false);
  edit.setDistance('050');
  assert.equal(edit.snapshot.dirty, false);
});

for (const mode of ['immediate', 'confirmed']) {
  test(`${mode} commit reports missing pin and invalid distance together, with pin focus first`, () => {
    const { edit } = fixture({ latitude: null, longitude: null, distanceKm: null });
    edit.begin();
    edit.setDistance('0');
    assert.equal(edit.commit(mode), null);
    assert.equal(edit.snapshot.errors.focus, 'pin');
    assert.match(edit.snapshot.errors.pin, /Choose a location/);
    assert.match(edit.snapshot.errors.distance, /whole-kilometre/);
    const first = edit.snapshot.errors;
    assert.equal(edit.commit(mode), null);
    assert.notEqual(edit.snapshot.errors, first, 'Each invalid submission can present focus and messages again');
    edit.choose([14.6, 121]);
    assert.equal(edit.snapshot.errors.pin, '');
    assert.notEqual(edit.snapshot.errors.distance, '');
    assert.equal(edit.snapshot.errors.focus, null, 'Correcting a field must not move focus');
    assert.equal(edit.commit(mode), null);
    assert.equal(edit.snapshot.errors.focus, 'distance');
  });
  for (const distance of ['', '0', '1001']) {
    test(`${mode} commit rejects distance ${JSON.stringify(distance)}`, () => {
      const { edit } = fixture();
      edit.begin();
      edit.setDistance(distance);
      assert.equal(edit.commit(mode), null);
      assert.equal(edit.snapshot.editing, true);
      assert.equal(edit.snapshot.errors.focus, 'distance');
    });
  }
  for (const distance of ['1', '1000']) {
    test(`${mode} commit accepts boundary distance ${distance}`, () => {
      const { edit } = fixture();
      edit.begin();
      edit.setDistance(distance);
      assert.deepEqual(edit.commit(mode), { ...saved, distanceKm: Number(distance) });
      assert.equal(edit.snapshot.editing, mode === 'confirmed');
      assert.equal(edit.snapshot.committing, mode === 'confirmed');
    });
  }
}

test('distance input rejects non-digits and correction clears only its field error', () => {
  const { edit } = fixture();
  edit.begin();
  for (const text of ['letters', '50km', '5.5', '-1', '1e2']) {
    edit.setDistance(text);
    assert.equal(edit.snapshot.distance, '50');
  }
  edit.setDistance('0');
  edit.commit('immediate');
  edit.setDistance('100');
  assert.equal(edit.snapshot.errors.distance, '');
  assert.equal(edit.snapshot.dirty, true);
});

test('refresh preserves open input; cancel restores the latest queue settings', () => {
  const { edit } = fixture();
  edit.begin();
  edit.choose([14.6, 121]);
  edit.setDistance('0075');
  const refreshed = { latitude: 10.3, longitude: 123.9, distanceKm: 100 };
  edit.refresh(refreshed);
  assert.deepEqual(edit.snapshot.point, [14.6, 121]);
  assert.equal(edit.snapshot.distance, '0075');
  assert.equal(edit.snapshot.dirty, true);
  edit.cancel();
  assert.deepEqual(edit.snapshot.point, [10.3, 123.9]);
  assert.equal(edit.snapshot.distance, '100');
  assert.equal(edit.snapshot.dirty, false);
  edit.refresh(saved);
  assert.deepEqual(edit.snapshot.point, [saved.latitude, saved.longitude]);
  assert.equal(edit.snapshot.distance, '50');
});

test('refreshed matching settings clear dirty status without changing raw input', () => {
  const { edit } = fixture();
  edit.begin();
  edit.setDistance('0100');
  edit.refresh({ ...saved, distanceKm: 100 });
  assert.equal(edit.snapshot.distance, '0100');
  assert.equal(edit.snapshot.dirty, false);
});

test('device success updates a pin and distance changes keep the request active', () => {
  const f = fixture();
  f.edit.begin();
  f.locate();
  f.locate();
  assert.equal(f.requests.length, 1, 'Do not start concurrent requests');
  f.edit.setDistance('75');
  f.requests[0].success([14.6, 121]);
  assert.deepEqual(f.edit.snapshot.point, [14.6, 121]);
  assert.equal(f.edit.snapshot.distance, '75');
  assert.equal(f.edit.snapshot.locating, false);
  assert.deepEqual(f.failures, []);
});

test('device failure preserves pin and allows retry', () => {
  const f = fixture();
  f.edit.begin();
  f.locate();
  f.requests[0].failure('Device denied');
  assert.deepEqual(f.edit.snapshot.point, [saved.latitude, saved.longitude]);
  assert.equal(f.edit.snapshot.locating, false);
  assert.deepEqual(f.failures, ['Device denied']);
  f.locate();
  assert.equal(f.requests.length, 2);
});

for (const action of ['choose', 'cancel', 'dispose', 'immediate', 'confirmed']) {
  for (const outcome of ['success', 'failure']) {
    test(`late device ${outcome} is ignored after ${action}, including a newer request`, () => {
      const f = fixture();
      f.edit.begin();
      f.locate();
      if (action === 'choose') f.edit.choose([10.3, 123.9]);
      else if (action === 'immediate' || action === 'confirmed') f.edit.commit(action);
      else f.edit[action]();
      assert.equal(f.edit.snapshot.locating, false);
      if (action === 'confirmed') f.edit.complete(false);
      if (!f.edit.snapshot.editing) f.edit.begin();
      f.locate();
      const expected = f.edit.snapshot;
      f.requests[0][outcome](outcome === 'success' ? [14.6, 121] : 'Old failure');
      assert.equal(f.edit.snapshot, expected, 'Old callback cannot change a newer edit or its busy state');
      assert.deepEqual(f.failures, []);
      f.requests[1].success([11, 124]);
      assert.deepEqual(f.edit.snapshot.point, [11, 124]);
    });
  }
}

test('confirmed commit captures and locks input; failure permits retry and cancel', () => {
  const f = fixture();
  f.edit.begin();
  f.edit.setDistance('100');
  f.locate();
  const captured = f.edit.commit('confirmed');
  f.edit.choose([14.6, 121]);
  f.edit.setDistance('200');
  f.locate();
  assert.equal(f.edit.commit('confirmed'), null);
  assert.deepEqual(captured, { ...saved, distanceKm: 100 });
  assert.equal(f.edit.snapshot.distance, '100');
  assert.equal(f.requests.length, 1);
  f.requests[0].success([14.6, 121]);
  f.edit.refresh({ ...saved, distanceKm: 75 });
  f.edit.complete(false);
  assert.equal(f.edit.snapshot.editing, true);
  assert.equal(f.edit.snapshot.distance, '100');
  assert.deepEqual(f.edit.commit('confirmed'), captured);
  f.edit.complete(false);
  f.edit.cancel();
  assert.equal(f.edit.snapshot.distance, '75');
});

test('confirmed success ends editing and disposal permits a fresh screen edit', () => {
  const { edit } = fixture();
  edit.begin();
  edit.setDistance('100');
  const location = edit.commit('confirmed');
  edit.refresh(location);
  edit.complete(true);
  assert.equal(edit.snapshot.editing, false);
  assert.equal(edit.snapshot.distance, '100');
  edit.begin();
  edit.setDistance('200');
  edit.dispose();
  edit.begin();
  assert.equal(edit.snapshot.distance, '100');
  assert.equal(edit.snapshot.dirty, false);
});

test('subscribers see stable snapshots and unsubscribe ends notifications', () => {
  const { edit } = fixture();
  let calls = 0;
  const first = edit.getSnapshot();
  assert.equal(edit.getSnapshot(), first);
  const unsubscribe = edit.subscribe(() => calls++);
  edit.begin();
  assert.equal(calls, 1);
  assert.notEqual(edit.getSnapshot(), first);
  unsubscribe();
  edit.cancel();
  assert.equal(calls, 1);
});

const account = { userId: 'fixture-user', displayName: 'Test', email: 'fixture@example.invalid',
  phone: null, status: 'active', onboardingCompleted: true, emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, ...saved };
for (const mode of ['immediate', 'confirmed']) {
  test(`${mode} save failure preserves its agreed edit behavior through the preference queue`, async () => {
    const response = deferred(), failures = [];
    const queue = new PreferenceSaves(account, () => response.promise, error => failures.push(error));
    const { edit } = fixture(queue.snapshot.preferences);
    const unsubscribe = queue.subscribe(() => edit.refresh(queue.snapshot.preferences));
    edit.begin();
    edit.setDistance('100');
    const location = edit.commit(mode);
    const saving = mode === 'confirmed'
      ? queue.saveConfirmed(location).catch(() => edit.complete(false))
      : queue.save(location, 0);
    assert.equal(queue.snapshot.preferences.distanceKm, 100);
    await tick();
    response.reject(new Error('Save unavailable'));
    if (mode === 'confirmed') await saving;
    await tick();
    assert.equal(edit.snapshot.editing, mode === 'confirmed');
    assert.equal(edit.snapshot.distance, mode === 'confirmed' ? '100' : '50');
    assert.equal(edit.snapshot.dirty, mode === 'confirmed');
    assert.deepEqual(failures, mode === 'confirmed' ? [] : ['Save unavailable']);
    unsubscribe();
    queue.cancel();
  });
}

test('browser device adapter reports unavailable devices and uses the existing options', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const failures = [], points = [];
  try {
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {} });
    browserLocation(point => points.push(point), message => failures.push(message));
    assert.match(failures[0], /unavailable on this device/);
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { geolocation: {
      getCurrentPosition(success, failure, options) {
        assert.deepEqual(options, { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 });
        success({ coords: { latitude: 14.6, longitude: 121 } });
        failure({ code: 1 });
      },
    } } });
    browserLocation(point => points.push(point), message => failures.push(message));
    assert.deepEqual(points, [[14.6, 121]]);
    assert.match(failures[1], /could not be used/);
  } finally {
    if (previous) Object.defineProperty(globalThis, 'navigator', previous);
    else delete globalThis.navigator;
  }
});
