import assert from 'node:assert/strict';
import test from 'node:test';
import { SmsEnrollment, SmsOptInFailure } from '../../src/features/accounts/sms-enrollment.ts';
import { PreferenceSaves } from '../../src/features/accounts/preference-saves.ts';

const baseline = { userId: 'fixture-user', displayName: 'Maria', email: 'maria@example.invalid',
  phone: null, onboardingCompleted: false, status: 'active', emailEnabled: false, smsEnabled: false,
  magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
const now = Date.parse('2026-10-12T10:00:00Z');
const attempt = (id = 'attempt-1') => ({ id, phone: '+639171234567',
  expiresAt: new Date(now + 300000).toISOString(), resendAt: new Date(now + 60000).toISOString() });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const failure = (code = 'UNAVAILABLE', field) => Object.assign(new Error(`Failure: ${code}`), { code, field });
const tick = () => new Promise(resolve => setTimeout(resolve, 15));

function fixture(t, initial = baseline, pending = null) {
  let backend = { ...initial }, serverPending = pending, account = backend, current = true;
  const trace = [], events = [], replies = new Map(), reconciled = [];
  function enqueue(key, reply) {
    if (!replies.has(key)) replies.set(key, []);
    replies.get(key).push(reply);
  }
  async function request(path = '', method = 'GET', body) {
    const key = `${method} ${path}`;
    trace.push({ key, body });
    if (key === 'POST /phone/attempts' && backend.phone) backend = { ...backend, smsEnabled: false };
    const reply = replies.get(key)?.shift();
    if (reply) return reply(body);
    if (key === 'GET ') return { account: backend, pending: serverPending, nextStep: 'complete' };
    if (key === 'POST /phone/attempts') {
      serverPending = attempt(`attempt-${trace.length}`);
      return serverPending;
    }
    if (key === 'POST /phone/verify') {
      assert.equal(body.attemptId, serverPending.id);
      backend = { ...backend, phone: serverPending.phone, smsEnabled: false };
      serverPending = null;
      return backend;
    }
    if (key === 'DELETE /phone/attempts') { serverPending = null; return; }
    assert.equal(key, 'PUT /preferences');
    backend = { ...backend, ...body, onboardingCompleted: true };
    return backend;
  }
  const queue = new PreferenceSaves(account, preferences => request('/preferences', 'PUT', preferences), assert.fail);
  const enrollment = new SmsEnrollment({ request, read: () => ({ account, saves: queue }),
    reconcile: next => {
      reconciled.push(next);
      if (!next) { account = null; return null; }
      queue.refresh(next);
      account = queue.snapshot.account;
      return queue;
    }, isCurrent: () => current, emit: event => events.push(event) });
  if (pending) enrollment.resume(pending);
  t.after(() => { enrollment.dispose(); queue.cancel(); });
  return { enrollment, queue, trace, events, enqueue, reconciled,
    account: () => account, invalidate: () => { current = false; },
    setPending: value => { serverPending = value; enrollment.resume(value); } };
}

test('resume uses Backend timing and performs no extra request', t => {
  const f = fixture(t, baseline, attempt());
  assert.deepEqual(f.enrollment.view(now), { pending: attempt(), expired: false, cooldown: 60 });
  assert.equal(f.enrollment.view(now + 59999).cooldown, 1);
  assert.equal(f.enrollment.view(now + 60000).cooldown, 0);
  assert.equal(f.enrollment.view(now + 300000).expired, true);
  assert.deepEqual(f.trace, []);
});

for (const [sendFails, refreshFails] of [[true, false], [false, true], [true, true]]) {
  test(`replacement reconciles after send ${sendFails ? 'failure' : 'success'} and refresh ${refreshFails ? 'failure' : 'success'}`, async t => {
    const f = fixture(t, { ...baseline, phone: '+639181234567', smsEnabled: true });
    const sendFailure = failure();
    if (sendFails) f.enqueue('POST /phone/attempts', () => Promise.reject(sendFailure));
    if (refreshFails) f.enqueue('GET ', () => Promise.reject(failure()));
    const operation = f.enrollment.send('09171234567');
    if (sendFails) await assert.rejects(operation, error => error === sendFailure);
    else assert.equal((await operation).kind, 'completed');
    assert.deepEqual(f.trace.map(item => item.key), ['POST /phone/attempts', 'GET ']);
    if (refreshFails) assert.equal(f.account(), null);
    else {
      assert.equal(f.account().phone, '+639181234567');
      assert.equal(f.queue.snapshot.preferences.smsEnabled, false);
    }
  });
}

for (const [verified, sms] of [[false, false], [false, true], [true, false], [true, true]]) {
  test(`onboarding saves selected channels, verified=${verified}, sms=${sms}`, async t => {
    const f = fixture(t, { ...baseline, ...(verified ? { phone: '+639171234567' } : {}) });
    const result = await f.enrollment.confirmChannels({ email: true, sms });
    assert.deepEqual(result, { kind: 'completed', value: sms && !verified });
    assert.equal(f.trace[0].body.emailEnabled, true);
    assert.equal(f.trace[0].body.smsEnabled, sms && verified);
    assert.equal(f.account().onboardingCompleted, true);
  });
}

test('unverified email and phone flags cannot enable selected channels', async t => {
  const f = fixture(t, { ...baseline, phone: '+639171234567', phoneVerified: false, emailVerified: false });
  assert.equal((await f.enrollment.confirmChannels({ email: true, sms: true })).value, true);
  assert.equal(f.trace[0].body.emailEnabled, false);
  assert.equal(f.trace[0].body.smsEnabled, false);
});

test('failed onboarding confirmation does not create SMS opt-in intent', async t => {
  const f = fixture(t);
  f.enqueue('PUT /preferences', () => Promise.reject(failure()));
  await assert.rejects(f.enrollment.confirmChannels({ email: true, sms: true }));
  f.setPending(attempt());
  await f.enrollment.verify('111111', now);
  assert.equal(f.trace.filter(item => item.key === 'PUT /preferences').length, 1);
  assert.deepEqual(f.events.filter(event => event.kind !== 'pending'), [{ kind: 'verified' }]);
});

test('a resumed attempt verifies without restoring SMS opt-in intent', async t => {
  const f = fixture(t, { ...baseline, onboardingCompleted: true }, attempt());
  await f.enrollment.verify('111111', now);
  assert.equal(f.enrollment.view(now).pending, null);
  assert.equal(f.account().phone, attempt().phone);
  assert.equal(f.account().smsEnabled, false);
  assert.deepEqual(f.trace.map(item => item.key), ['POST /phone/verify']);
  assert.deepEqual(f.events.filter(event => event.kind !== 'pending'), [{ kind: 'verified' }]);
});

test('verification reports before held opt-in and uses a separate preference write', async t => {
  const f = fixture(t);
  await f.enrollment.confirmChannels({ email: true, sms: true });
  f.setPending(attempt());
  const response = deferred(), requested = deferred();
  f.enqueue('PUT /preferences', body => { requested.resolve(body); return response.promise; });
  const operation = f.enrollment.verify('111111', now);
  assert.equal((await requested.promise).smsEnabled, true);
  assert.equal(f.enrollment.view(now).pending, null);
  assert.equal(f.account().phone, attempt().phone);
  assert.deepEqual(f.events.filter(event => event.kind !== 'pending'), [{ kind: 'verified' }]);
  const laterEdit = f.queue.saveConfirmed({ emailEnabled: false });
  await tick();
  assert.equal(f.trace.filter(item => item.key === 'PUT /preferences').length, 2);
  response.resolve({ ...f.account(), smsEnabled: true });
  await operation;
  await laterEdit;
  const laterWrite = f.trace.filter(item => item.key === 'PUT /preferences').at(-1).body;
  assert.equal(laterWrite.smsEnabled, true);
  assert.equal(laterWrite.emailEnabled, false);
  assert.equal(f.queue.snapshot.account.smsEnabled, true);
  assert.equal(f.queue.snapshot.account.emailEnabled, false);
  assert.deepEqual(f.events.filter(event => event.kind !== 'pending'), [{ kind: 'verified' }, { kind: 'enabled' }]);
  assert.deepEqual(f.trace.map(item => item.key), ['PUT /preferences', 'POST /phone/verify', 'PUT /preferences', 'PUT /preferences']);
});

for (const code of ['UNAVAILABLE']) {
  test(`opt-in failure retains verified phone and original ${code} failure`, async t => {
    const f = fixture(t);
    await f.enrollment.confirmChannels({ email: false, sms: true });
    f.setPending(attempt());
    const error = failure(code, 'smsEnabled');
    f.enqueue('PUT /preferences', () => Promise.reject(error));
    await assert.rejects(f.enrollment.verify('111111', now), value =>
      value instanceof SmsOptInFailure && value.failure === error);
    assert.equal(f.enrollment.view(now).pending, null);
    assert.equal(f.account().phone, attempt().phone);
    assert.equal(f.queue.snapshot.preferences.smsEnabled, false);
    assert.deepEqual(f.events.filter(event => event.kind !== 'pending'), [{ kind: 'verified' }]);
    await f.queue.saveConfirmed({ smsEnabled: true });
    assert.equal(f.queue.snapshot.account.smsEnabled, true);
    assert.equal(f.trace.filter(item => item.key === 'POST /phone/verify').length, 1);
  });
}

test('newer email edit survives failed opt-in in the shared queue', async t => {
  const f = fixture(t);
  await f.enrollment.confirmChannels({ email: false, sms: true });
  f.setPending(attempt());
  const response = deferred(), requested = deferred();
  f.enqueue('PUT /preferences', () => { requested.resolve(); return response.promise; });
  const rejected = assert.rejects(f.enrollment.verify('111111', now), SmsOptInFailure);
  await requested.promise;
  const saved = f.queue.saveConfirmed({ emailEnabled: true });
  response.reject(failure());
  await rejected;
  await saved;
  assert.equal(f.queue.snapshot.preferences.emailEnabled, true);
  assert.equal(f.queue.snapshot.preferences.smsEnabled, false);
});

test('a later SMS-off edit suppresses the enabled claim', async t => {
  const f = fixture(t);
  await f.enrollment.confirmChannels({ email: false, sms: true });
  f.setPending(attempt());
  const response = deferred(), requested = deferred();
  f.enqueue('PUT /preferences', () => { requested.resolve(); return response.promise; });
  const verifying = f.enrollment.verify('111111', now);
  await requested.promise;
  const saved = f.queue.saveConfirmed({ smsEnabled: false });
  response.resolve({ ...f.account(), smsEnabled: true });
  await verifying;
  await saved;
  assert.equal(f.queue.snapshot.preferences.smsEnabled, false);
  assert.deepEqual(f.events.filter(event => event.kind !== 'pending'), [{ kind: 'verified' }]);
});

for (const command of ['changeNumber', 'skip']) {
  test(`${command} commits cancellation only after successful deletion`, async t => {
    const f = fixture(t);
    await f.enrollment.confirmChannels({ email: false, sms: true });
    f.setPending(attempt());
    f.enqueue('DELETE /phone/attempts', () => Promise.reject(failure()));
    await assert.rejects(f.enrollment[command]());
    assert.equal(f.enrollment.view(now).pending.id, 'attempt-1');
    await f.enrollment[command]();
    assert.equal(f.enrollment.view(now).pending, null);
    f.setPending(attempt('attempt-2'));
    await f.enrollment.verify('111111', now);
    assert.equal(f.queue.snapshot.preferences.smsEnabled, command === 'changeNumber');
  });
}

test('skip without an attempt clears intent without a DELETE', async t => {
  const f = fixture(t);
  await f.enrollment.confirmChannels({ email: false, sms: true });
  await f.enrollment.skip();
  f.setPending(attempt());
  await f.enrollment.verify('111111', now);
  assert.deepEqual(f.trace.map(item => item.key), ['PUT /preferences', 'POST /phone/verify']);
});

test('resend failure retains the attempt even when replacement refresh returns another attempt', async t => {
  const f = fixture(t, { ...baseline, phone: '+639181234567' }, attempt());
  f.enqueue('POST /phone/attempts', () => Promise.reject(failure()));
  f.enqueue('GET ', async () => ({ account: f.account(), pending: attempt('different') }));
  await assert.rejects(f.enrollment.resend('different input'));
  assert.equal(f.enrollment.view(now).pending.id, 'attempt-1');
  assert.equal(f.trace[0].body.phone, attempt().phone);
  assert.equal((await f.enrollment.resend('different input')).kind, 'completed');
  assert.notEqual(f.enrollment.view(now).pending.id, 'attempt-1');
});

test('local expiry blocks proof; Backend expiry clears the attempt; invalid code preserves it', async t => {
  const f = fixture(t, baseline, attempt());
  assert.deepEqual(await f.enrollment.verify('111111', now + 300000), { kind: 'ignored' });
  assert.deepEqual(f.trace, []);
  f.enqueue('POST /phone/verify', () => Promise.reject(failure('INVALID_CODE', 'code')));
  await assert.rejects(f.enrollment.verify('111111', now), error => error.field === 'code');
  assert.equal(f.enrollment.view(now).pending.id, 'attempt-1');
  f.enqueue('POST /phone/verify', () => Promise.reject(failure('ATTEMPT_EXPIRED')));
  await assert.rejects(f.enrollment.verify('111111', now));
  assert.equal(f.enrollment.view(now).pending, null);
});

for (const command of ['send', 'replacement-send', 'replacement-refresh', 'resend', 'verify', 'changeNumber', 'skip', 'opt-in', 'channels']) {
  for (const rejects of [false, true]) {
    test(`obsolete ${command} ${rejects ? 'failure' : 'success'} is ignored`, async t => {
      const replacement = command.startsWith('replacement');
      const f = fixture(t, { ...baseline, ...(replacement ? { phone: '+639181234567', smsEnabled: true } : {}) });
      if (command === 'opt-in') await f.enrollment.confirmChannels({ email: false, sms: true });
      if (['resend', 'verify', 'changeNumber', 'skip', 'opt-in'].includes(command)) f.setPending(attempt());
      const response = deferred(), requested = deferred();
      const key = command === 'replacement-refresh' ? 'GET ' : ['opt-in', 'channels'].includes(command)
        ? 'PUT /preferences' : command === 'verify' ? 'POST /phone/verify'
          : ['changeNumber', 'skip'].includes(command) ? 'DELETE /phone/attempts' : 'POST /phone/attempts';
      f.enqueue(key, () => { requested.resolve(); return response.promise; });
      const operation = command === 'channels' ? f.enrollment.confirmChannels({ email: false, sms: true })
        : command === 'opt-in' || command === 'verify' ? f.enrollment.verify('111111', now)
          : command.startsWith('replacement') || command === 'send' ? f.enrollment.send('09171234567')
            : command === 'resend' ? f.enrollment.resend('09171234567') : f.enrollment[command]();
      await requested.promise;
      const events = [...f.events], reconciled = [...f.reconciled];
      f.invalidate();
      // The production identity adapter rejects former-session responses; this adapter also exercises raw late success.
      if (rejects) response.reject(failure());
      else response.resolve(key === 'GET ' ? { account: baseline, pending: null }
        : key === 'POST /phone/attempts' ? attempt('late') : { ...baseline, smsEnabled: true });
      assert.deepEqual(await operation, { kind: 'ignored' });
      assert.deepEqual(f.events, events);
      assert.deepEqual(f.reconciled, reconciled);
      if (command === 'replacement-send') assert.equal(f.trace.filter(item => item.key === 'GET ').length, 0);
    });
  }
}

test('disposing suppresses local results while a submitted preference write can finish', async t => {
  const f = fixture(t);
  await f.enrollment.confirmChannels({ email: false, sms: true });
  f.setPending(attempt());
  const response = deferred(), requested = deferred();
  f.enqueue('PUT /preferences', () => { requested.resolve(); return response.promise; });
  const verifying = f.enrollment.verify('111111', now);
  await requested.promise;
  const events = [...f.events];
  f.enrollment.dispose();
  response.resolve({ ...f.account(), smsEnabled: true });
  assert.deepEqual(await verifying, { kind: 'ignored' });
  assert.equal(f.queue.snapshot.account.smsEnabled, true);
  assert.deepEqual(f.events, events);
  assert.deepEqual(await f.enrollment.send('09171234567'), { kind: 'ignored' });
  await tick();
});
