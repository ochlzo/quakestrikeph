import assert from 'node:assert/strict';
import test from 'node:test';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { AccountError, normalizePhone, preferences, type Account, type Identity } from '../../src/domain/accounts.js';
import { AccountService } from '../../src/application/accounts/service.js';
import { Iprog } from '../../src/infrastructure/sms/iprog.js';
import { clerkIdentity } from '../../src/infrastructure/clerk/identity.js';
import type { AccountStore, PhoneAttempts, PhoneProvider, PendingPhone } from '../../src/ports/accounts.js';
import { createApp } from '../../src/interface/http/app.js';

const identity: Identity = { clerkUserId: 'user_test', email: 'test@example.invalid', recent: false };
test('configured Clerk session authentication rejects invalid tokens instead of reporting missing configuration', async () => {
  const authenticate = clerkIdentity('sk_test_fixture', ['http://localhost:4321'], 'pk_test_Y2xlcmsudGVzdC5kZXYk');
  await assert.rejects(authenticate(new Headers({ authorization: 'Bearer invalid-session-token' })),
    (error: unknown) => error instanceof AccountError && error.code === 'SIGN_IN_REQUIRED' && error.status === 401);
});
const base = { emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
const account: Account = { ...base, userId: randomUUID(), displayName: 'Test', email: identity.email, phone: null, onboardingCompleted: false, status: 'active' };
function fixture(initial: Account | null = account) {
  let current = initial ? { ...initial } : null, sends = 0, checks = 0, pauses = 0;
  let pending: PendingPhone | null = null, failures = 0;
  const store: AccountStore = {
    failure: async () => {},
    read: async () => current,
    profile: async (_id, name) => { current = { ...account, displayName: name }; return current; },
    save: async (_id, p) => { current = { ...current!, ...p, onboardingCompleted: true }; return current; },
    pauseSms: async () => { pauses++; current = { ...current!, smsEnabled: false }; return current; },
    bindPhone: async (_id, phone) => { current = { ...current!, phone, smsEnabled: false }; return current; },
    phoneAvailable: async () => true,
  };
  const attempts: PhoneAttempts = {
    exclusive: async (_u, _p, work) => work(),
    start: async (_u, phone) => { pending = { id: randomUUID(), phone, expiresAt: new Date(Date.now() + 300000).toISOString(), resendAt: new Date(Date.now() + 60000).toISOString() }; return pending; },
    pending: async () => pending,
    arm: async () => {}, matches: async () => true,
    check: async (_u, id) => { if (!pending || pending.id !== id) throw new AccountError('ATTEMPT_EXPIRED', 'Expired', 409); return pending; },
    wrong: async () => { failures++; },
    consume: async () => { pending = null; }, cancel: async () => { pending = null; },
  };
  const provider: PhoneProvider = { supported: async () => { checks++; return true; }, send: async () => { sends++; return 'FIXTURE_PROOF'; }, proof: () => 'FIXTURE_PROOF', verify: async () => true };
  return { store, attempts, provider, service: new AccountService(store, attempts, provider), stats: () => ({ current, sends, checks, pauses, pending, failures }) };
}

test('finite rule bounds reject incomplete location, fractions and coercion', () => {
  for (const bad of [{ magnitude: NaN }, { magnitude: Infinity }, { magnitude: 0.9 }, { magnitude: 10.1 },
    { magnitude: 4.55 }, { magnitude: '4.5' }, { emailEnabled: 'true' }, { nearbyOnly: true },
    { latitude: 14 }, { distanceKm: 2.5 }, { longitude: 200 }, { distanceKm: 1001 }]) {
    assert.throws(() => preferences({ ...base, ...bad }), AccountError);
  }
  assert.deepEqual(preferences(base), base);
  assert.equal(normalizePhone('0917 123 4567'), '+639171234567');
  assert.equal(normalizePhone('+63 (917) 123-4567'), '+639171234567');
  assert.throws(() => normalizePhone('0917x234567'), AccountError);
});

test('both-off saves complete onboarding; only supported verified phones may enable SMS', async () => {
  const f = fixture();
  await assert.rejects(f.service.save(identity, { ...base, smsEnabled: true }, randomUUID()), { code: 'SMS_UNSUPPORTED' });
  const next = await f.service.save(identity, base, randomUUID());
  assert.equal(next.onboardingCompleted, true); assert.equal(next.smsEnabled, false); assert.equal(next.emailEnabled, false);
});

test('unsupported and unknown networks stop before OTP, and proof never opts in', async () => {
  const f = fixture(); f.provider.supported = async () => false;
  await assert.rejects(f.service.start(identity, { phone: '09171234567' }, randomUUID()), { code: 'SMS_UNSUPPORTED' });
  assert.equal(f.stats().sends, 0); assert.equal(f.stats().pending, null);
  f.provider.supported = async () => true;
  const pending = await f.service.start(identity, { phone: '09171234567' }, randomUUID());
  await assert.rejects(f.service.verify(identity, { attemptId: 'wrong-attempt', code: '123456' }, randomUUID()), { code: 'ATTEMPT_EXPIRED' });
  const next = await f.service.verify(identity, { attemptId: pending.id, code: '123456' }, randomUUID());
  assert.equal(next.phone, '+639171234567'); assert.equal(next.smsEnabled, false);
  await assert.rejects(f.service.verify(identity, { attemptId: pending.id, code: '123456' }, randomUUID()), { code: 'REVERIFICATION_REQUIRED' });
});

test('replacement needs fresh identity and pauses SMS even if provider is unavailable', async () => {
  const f = fixture({ ...account, phone: '+639171234567', smsEnabled: true, onboardingCompleted: true });
  await assert.rejects(f.service.start(identity, { phone: '09171234568' }, randomUUID()), { code: 'REVERIFICATION_REQUIRED' });
  assert.equal(f.stats().pauses, 0);
  f.provider.supported = async () => { throw new AccountError('SMS_UNAVAILABLE', 'Unavailable', 503); };
  await assert.rejects(f.service.start({ ...identity, recent: true }, { phone: '09171234568' }, randomUUID()), { code: 'SMS_UNAVAILABLE' });
  assert.equal(f.stats().current?.smsEnabled, false); assert.equal(f.stats().current?.phone, '+639171234567');
});

test('suspended/closed users and wrong codes cannot bind destinations', async () => {
  for (const status of ['suspended', 'closed'] as const) {
    const f = fixture({ ...account, status });
    await assert.rejects(f.service.start(identity, { phone: '09171234567' }, randomUUID()), { code: 'ACCOUNT_UNAVAILABLE' });
    assert.equal(f.stats().sends, 0);
  }
  const f = fixture(); const pending = await f.service.start(identity, { phone: '09171234567' }, randomUUID());
  f.provider.verify = async () => false;
  await assert.rejects(f.service.verify(identity, { attemptId: pending.id, code: '123456' }, randomUUID()), { code: 'INVALID_CODE' });
  assert.equal(f.stats().current?.phone, null); assert.equal(f.stats().failures, 1);
});

test('IPROG adapter interprets documented string statuses and strips returned OTP data', async () => {
  const calls: string[] = [];
  const request = (async (url, options) => {
    calls.push(String(url)); const body = JSON.parse(String(options?.body));
    assert.equal(body.phone_number, '+639171234567');
    if (String(url).endsWith('/detect')) return Response.json({ status: 'success', data: { network: 'Globe/TM', is_smart_tnt: false } });
    if (String(url).endsWith('/send_otp')) { assert.equal(body.expires_in_minutes, 5); return Response.json({ status: 'success', data: { otp_code: '123456', message: 'PRIVATE_MESSAGE' } }); }
    return Response.json({ status: 'success' });
  }) as typeof fetch;
  const provider = new Iprog('TEST_ONLY', request);
  assert.equal(await provider.supported('+639171234567'), true);
  const proof = await provider.send('+639171234567', 'FIXTURE_ATTEMPT');
  assert.equal(proof, provider.proof('FIXTURE_ATTEMPT', '123456'));
  assert.notEqual(proof, provider.proof('NEW_ATTEMPT', '123456'));
  assert.equal(await provider.verify('+639171234567', '123456'), true);
  assert.equal(calls.length, 3);
  for (const network of ['Smart/TNT', 'Unknown Network', 'Invalid Format']) {
    const unsupported = new Iprog('TEST_ONLY', (async () => Response.json({ status: 'success', data: { network, is_smart_tnt: false } })) as typeof fetch);
    assert.equal(await unsupported.supported('+639171234567'), false);
  }
  await assert.rejects(new Iprog(undefined).send('+639171234567', 'FIXTURE_ATTEMPT'), { code: 'SMS_UNAVAILABLE' });
});

test('account HTTP routes require owner identity; removal and email mutations are absent', async () => {
  const f = fixture();
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
    { service: f.service, authenticate: async headers => {
      if (headers.get('authorization') !== 'Bearer TEST_SESSION') throw new AccountError('SIGN_IN_REQUIRED', 'Sign in', 401);
      return identity;
    } });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No server address');
  const baseUrl = `http://127.0.0.1:${address.port}/api/v1/account`;
  try {
    assert.equal((await fetch(baseUrl)).status, 401);
    const response = await fetch(baseUrl, { headers: { authorization: 'Bearer TEST_SESSION' } });
    assert.equal(response.status, 200); assert.equal(response.headers.get('cache-control'), 'private, no-store');
    for (const path of ['', '/email', '/close']) {
      assert.equal((await fetch(`${baseUrl}${path}`, { method: 'DELETE', headers: { authorization: 'Bearer TEST_SESSION' } })).status, 404);
    }
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});
