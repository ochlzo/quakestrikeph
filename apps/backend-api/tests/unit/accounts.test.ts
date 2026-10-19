import assert from 'node:assert/strict';
import test from 'node:test';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { AccountError, SmsProviderError, normalizePhone, preferences, requireTrustedEmail, type Account, type Identity } from '../../src/domain/accounts.js';
import { AccountService } from '../../src/application/accounts/service.js';
import { Iprog } from '../../src/infrastructure/sms/iprog.js';
import { clerkIdentity } from '../../src/infrastructure/clerk/identity.js';
import type { AccountStore, PhoneAttempts, PhoneProvider, PendingPhone } from '../../src/ports/accounts.js';
import { createApp } from '../../src/interface/http/app.js';

const identity: Identity = { clerkUserId: 'user_test', email: 'test@example.invalid', recent: false };
test('configured Clerk session authentication rejects invalid tokens instead of reporting missing configuration', async () => {
  const authenticate = clerkIdentity('sk_test_fixture', ['http://localhost:4321'], 'pk_test_Y2xlcmsudGVzdC5kZXYk');
  await assert.rejects(authenticate(new Headers({ authorization: 'Bearer invalid-session-token' })),
    (error: unknown) => error instanceof AccountError && error.code === 'SIGN_IN_REQUIRED');
});
const base = { emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
const account: Account = { ...base, userId: randomUUID(), displayName: 'Test', email: identity.email, phone: null, onboardingCompleted: false, status: 'active' };
test('trusted email requires matching identity and stored verification evidence', () => {
  requireTrustedEmail(identity.email, true, identity);
  for (const [email, verified] of [[identity.email, false], ['changed@example.invalid', true], ['changed@example.invalid', false]] as const) {
    assert.throws(() => requireTrustedEmail(email, verified, identity),
      (error: unknown) => error instanceof AccountError && error.code === 'EMAIL_MIRROR_MISMATCH' && !('status' in error));
  }
});

test('account HTTP errors preserve statuses, messages, and field identifiers', async () => {
  const groups: [number, string[]][] = [
    [400, ['INVALID_CODE', 'INVALID_LOCATION', 'INVALID_MAGNITUDE', 'INVALID_NAME', 'INVALID_PHONE', 'INVALID_PREFERENCES', 'INVALID_REQUEST', 'PHONE_REQUIRED', 'SMS_UNSUPPORTED']],
    [401, ['SIGN_IN_REQUIRED']],
    [403, ['ACCOUNT_UNAVAILABLE', 'REVERIFICATION_REQUIRED', 'EMAIL_VERIFICATION_REQUIRED']],
    [409, ['EMAIL_MIRROR_MISMATCH', 'PHONE_UNAVAILABLE', 'PROFILE_REQUIRED', 'ATTEMPT_EXPIRED', 'VERIFICATION_BUSY']],
    [429, ['SEND_LIMIT']],
    [503, ['AUTH_UNAVAILABLE', 'SMS_UNAVAILABLE', 'VERIFICATION_UNAVAILABLE']],
  ];
  const f = fixture();
  let failure = new AccountError('INVALID_REQUEST', 'Request rejected.', 'phone');
  f.store.read = async () => { throw failure; };
  const server = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
    { service: f.service, authenticate: async () => identity }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No server address');
  try {
    for (const [status, codes] of groups) {
      for (const code of codes) {
        failure = new AccountError(code, 'Request rejected.', 'phone');
        const response: Response = await fetch(`http://127.0.0.1:${address.port}/api/v1/account`);
        assert.equal(response.status, status, code);
        assert.deepEqual(await response.json(), { error: { code, message: 'Request rejected.', field: 'phone' } });
      }
    }
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('profile completion depends on the saved name before other onboarding steps', async () => {
  assert.equal((await fixture(null).service.read(identity)).nextStep, 'profile');
  for (const name of [null, '', '   ']) {
    const missingName = { ...account, displayName: name } as unknown as Account;
    assert.equal((await fixture(missingName).service.read(identity)).nextStep, 'profile');
    assert.equal((await fixture({ ...missingName, onboardingCompleted: true }).service.read(identity)).nextStep, 'profile');
  }
  assert.equal((await fixture(account).service.read(identity)).nextStep, 'channels');
  assert.equal((await fixture({ ...account, phone: '+639171234567' }).service.read(identity)).nextStep, 'preferences');
  assert.equal((await fixture({ ...account, onboardingCompleted: true }).service.read(identity)).nextStep, 'complete');
});
function fixture(initial: Account | null = account) {
  let current = initial ? { ...initial } : null, sends = 0, checks = 0, pauses = 0, removals = 0;
  let pending: PendingPhone | null = null, failures = 0;
  const store: AccountStore = {
    failure: async () => {},
    read: async () => current,
    profile: async (_id, name) => { current = { ...account, displayName: name }; return current; },
    save: async (_id, p) => { current = { ...current!, ...p, onboardingCompleted: true }; return current; },
    pauseSms: async () => { pauses++; current = { ...current!, smsEnabled: false }; return current; },
    bindPhone: async (_id, phone) => { current = { ...current!, phone, smsEnabled: false }; return current; },
    removePhone: async () => { removals++; current = { ...current!, phone: null, smsEnabled: false }; return current; },
    phoneAvailable: async () => true,
  };
  const attempts: PhoneAttempts = {
    exclusive: async (_u, _p, work) => work(),
    start: async (_u, phone) => { pending = { id: randomUUID(), phone, expiresAt: new Date(Date.now() + 300000).toISOString(), resendAt: new Date(Date.now() + 60000).toISOString() }; return pending; },
    pending: async () => pending,
    arm: async () => {}, matches: async () => true,
    check: async (_u, id) => { if (!pending || pending.id !== id) throw new AccountError('ATTEMPT_EXPIRED', 'Expired'); return pending; },
    wrong: async () => { failures++; },
    consume: async () => { pending = null; }, cancel: async () => { pending = null; },
  };
  const provider: PhoneProvider = { supported: async () => { checks++; return true; }, send: async () => { sends++; return 'FIXTURE_PROOF'; }, proof: () => 'FIXTURE_PROOF', verify: async () => true };
  return { store, attempts, provider, service: new AccountService(store, attempts, provider), stats: () => ({ current, sends, checks, pauses, removals, pending, failures }) };
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
  f.provider.supported = async () => { throw new AccountError('SMS_UNAVAILABLE', 'Unavailable'); };
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

test('phone removal requires a fresh identity and clears the saved number', async () => {
  const bound = { ...account, phone: '+639171234567', smsEnabled: true, onboardingCompleted: true };
  const denied = fixture(bound);
  await assert.rejects(denied.service.removePhone(identity, randomUUID()), { code: 'REVERIFICATION_REQUIRED' });
  assert.equal(denied.stats().removals, 0);
  const f = fixture(bound);
  const next = await f.service.removePhone({ ...identity, recent: true }, randomUUID());
  assert.equal(next.phone, null); assert.equal(next.smsEnabled, false); assert.equal(f.stats().removals, 1);
});

test('phone removal cancels an in-flight verification attempt before clearing', async () => {
  const f = fixture({ ...account, phone: '+639171234567', smsEnabled: true, onboardingCompleted: true });
  const recent = { ...identity, recent: true };
  await f.service.start(recent, { phone: '09171234568' }, randomUUID());
  assert.equal(f.stats().pending?.phone, '+639171234568');
  const next = await f.service.removePhone(recent, randomUUID());
  assert.equal(next.phone, null); assert.equal(f.stats().pending, null);
});

test('phone removal with no saved number changes nothing but cancels a pending attempt', async () => {
  const empty = fixture({ ...account, phone: null });
  const next = await empty.service.removePhone({ ...identity, recent: true }, randomUUID());
  assert.equal(next.phone, null); assert.equal(empty.stats().removals, 0);
  const adding = fixture({ ...account, phone: null });
  await adding.service.start(identity, { phone: '09171234567' }, randomUUID());
  assert.notEqual(adding.stats().pending, null);
  await adding.service.removePhone({ ...identity, recent: true }, randomUUID());
  assert.equal(adding.stats().removals, 0); assert.equal(adding.stats().pending, null);
});

for (const pauseAt of ['read', 'lock'] as const) {
  test(`phone removal clears verification committed after its initial ${pauseAt}`, async () => {
    const f = fixture({ ...account, phone: null, onboardingCompleted: true });
    const recent = { ...identity, recent: true };
    const pending = await f.service.start(recent, { phone: '09171234567' }, randomUUID());
    let entered!: () => void, release!: () => void;
    const paused = new Promise<void>(resolve => { entered = resolve; });
    const resume = new Promise<void>(resolve => { release = resolve; });
    let pauseNextRead = pauseAt === 'read', pauseNextLock = pauseAt === 'lock', locked = false;
    const read = f.store.read;
    f.store.read = async owner => {
      const snapshot = await read(owner);
      if (pauseNextRead) { pauseNextRead = false; entered(); await resume; }
      return snapshot;
    };
    f.attempts.exclusive = async (_user, _phone, work) => {
      if (pauseNextLock) { pauseNextLock = false; entered(); await resume; }
      if (locked) throw new AccountError('VERIFICATION_BUSY', 'Busy');
      locked = true;
      try { return await work(); } finally { locked = false; }
    };
    const removing = f.service.removePhone(recent, randomUUID());
    await paused;
    try {
      const verified = await f.service.verify(recent, { attemptId: pending.id, code: '123456' }, randomUUID());
      assert.equal(verified.phone, '+639171234567');
      assert.equal(f.stats().pending, null);
    } finally { release(); }
    const removed = await removing;
    assert.equal(removed.phone, null);
    assert.equal(f.stats().current?.phone, null, 'Removal must clear the binding committed by verification');
    assert.equal(f.stats().removals, 1);
  });
}

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
  for (const network of ['Smart', 'TNT', 'Smart/TNT']) {
    const unsupported = new Iprog('TEST_ONLY', (async () => Response.json({ status: 'success', data: { network, is_smart_tnt: true } })) as typeof fetch);
    assert.equal(await unsupported.supported('+639171234567'), false);
  }
  await assert.rejects(new Iprog(undefined).send('+639171234567', 'FIXTURE_ATTEMPT'), { code: 'SMS_UNAVAILABLE' });
});

test('account HTTP routes require owner identity; removal clears the phone and email/account removal stay absent', async () => {
  const f = fixture({ ...account, phone: '+639171234567', onboardingCompleted: true });
  const app = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
    { service: f.service, authenticate: async headers => {
      if (headers.get('authorization') !== 'Bearer TEST_SESSION') throw new AccountError('SIGN_IN_REQUIRED', 'Sign in');
      return { ...identity, recent: true };
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
    const removed = await fetch(`${baseUrl}/phone`, { method: 'DELETE', headers: { authorization: 'Bearer TEST_SESSION' } });
    assert.equal(removed.status, 200); assert.equal((await removed.json()).phone, null);
    assert.equal(f.stats().removals, 1);
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('number detection service errors do not report unsupported networks', async () => {
  const f = fixture();
  const provider = new Iprog('TEST_ONLY', (async () => Response.json({ status: 'error', message: 'Provider unavailable' })) as typeof fetch);
  const service = new AccountService(f.store, f.attempts, provider);
  await assert.rejects(service.start(identity, { phone: '09171234567' }, randomUUID()), { code: 'SMS_UNAVAILABLE' });
  assert.equal(f.stats().pending, null);
});

test('malformed network results return unavailable through account HTTP with safe diagnostics', async (t) => {
  const logs: string[] = [];
  t.mock.method(console, 'error', (line: string) => logs.push(line));
  for (const data of [
    { network: '', is_smart_tnt: false },
    { network: 'Unknown Network', is_smart_tnt: false },
    { network: 'Globe/TM', is_smart_tnt: true },
    { network: 'Smart/TNT', is_smart_tnt: false },
  ]) {
    const f = fixture(); let calls = 0;
    const provider = new Iprog('PRIVATE_TOKEN', (async () => {
      calls++;
      return Response.json({ status: 'success', data, message: 'PRIVATE_MESSAGE' });
    }) as typeof fetch);
    const service = new AccountService(f.store, f.attempts, provider);
    const server = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
      { service, authenticate: async () => identity }).listen(0, '127.0.0.1');
    await once(server, 'listening');
    const address = server.address(); if (!address || typeof address === 'string') throw new Error('No server address');
    try {
      const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/account/phone/attempts`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ phone: '09171234567' }),
      });
      assert.equal(response.status, 503);
      assert.equal((await response.json()).error.code, 'SMS_UNAVAILABLE');
      assert.equal(calls, 1); assert.equal(f.stats().pending, null);
      const diagnostic = JSON.parse(logs.at(-1)!);
      assert.equal(diagnostic.category, 'malformed_response');
      assert.equal(diagnostic.operation, 'detect');
      assert.equal(diagnostic.requestId, response.headers.get('x-request-id'));
      assert.equal(diagnostic.failureSource, 'body'); assert.equal(diagnostic.httpStatus, 200);
      assert.doesNotMatch(logs.join(''), /PRIVATE_TOKEN|PRIVATE_MESSAGE|639171234567/);
    } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
  }
});

test('IPROG combined credential and credit rejection remains ambiguous under HTTP success', async () => {
  const provider = new Iprog('PRIVATE_TOKEN', (async () => Response.json({ status: 500,
    message: 'Invalid api token or no load balance', data: { otp_code: '123456', phone_number: '+639171234567' } })) as typeof fetch);
  await assert.rejects(provider.supported('+639171234567'), (error: unknown) => {
    assert.ok(error instanceof SmsProviderError);
    assert.deepEqual(error.diagnostic, { provider: 'iprog', operation: 'detect', category: 'credential_or_credit',
      failureSource: 'body', httpStatus: 200, providerCode: 500, retryAfterSeconds: null });
    assert.doesNotMatch(JSON.stringify(error), /PRIVATE_TOKEN|123456|639171234567|load balance/);
    return true;
  });
});

test('phone verification service failures preserve matching proofs and classify sanitized diagnostics', async () => {
  const cases = [
    { category: 'credentials', source: 'http', status: 401, request: async () => Response.json({ status: 'error' }, { status: 401 }) },
    { category: 'credits', source: 'http', status: 402, request: async () => Response.json({ status: 'error' }, { status: 402 }) },
    { category: 'provider_failure', source: 'body', status: 200, request: async () => Response.json({ status: 'error', message: 'Unknown outage' }) },
    { category: 'rate_limit', source: 'body', status: 200, request: async () => Response.json({ status: 429 }) },
    { category: 'http_failure', source: 'http', status: 500, request: async () => Response.json({ status: 'success' }, { status: 500 }) },
    { category: 'malformed_response', source: 'body', status: 200, request: async () => new Response('PRIVATE_RESPONSE', { status: 200 }) },
    { category: 'malformed_response', source: 'body', status: 200, request: async () => Response.json(null) },
    { category: 'malformed_response', source: 'body', status: 200, request: async () => Response.json([]) },
    { category: 'malformed_response', source: 'body', status: 200, request: async () => Response.json({ data: {} }) },
    { category: 'transport_uncertain', source: 'transport', status: null, request: async (): Promise<Response> => { throw new DOMException('PRIVATE_TOKEN 123456 +639171234567', 'TimeoutError'); } },
  ];
  for (const scenario of cases) {
    const f = fixture();
    let digest = '';
    f.attempts.arm = async (_user, _attempt, proof) => { digest = proof; };
    f.attempts.matches = async (_user, _attempt, proof) => digest === proof;
    const provider = new Iprog('PRIVATE_TOKEN', (async (url) => {
      if (String(url).endsWith('/detect')) return Response.json({ status: 'success', data: { network: 'Globe/TM', is_smart_tnt: false } });
      if (String(url).endsWith('/send_otp')) return Response.json({ status: 'success', data: { otp_code: '123456' } });
      return scenario.request();
    }) as typeof fetch);
    const service = new AccountService(f.store, f.attempts, provider);
    const pending = await service.start(identity, { phone: '09171234567' }, randomUUID());
    await assert.rejects(service.verify(identity, { attemptId: pending.id, code: '123456' }, randomUUID()), (error: unknown) => {
      assert.ok(error instanceof SmsProviderError, scenario.category);
      assert.equal(error.diagnostic.category, scenario.category);
      assert.equal(error.diagnostic.failureSource, scenario.source);
      assert.equal(error.diagnostic.httpStatus, scenario.status);
      assert.equal(error.diagnostic.operation, 'verify_otp');
      assert.doesNotMatch(JSON.stringify(error), /PRIVATE_TOKEN|PRIVATE_RESPONSE|123456|639171234567/);
      return true;
    });
    assert.equal(f.stats().failures, 0);
    assert.equal(f.stats().pending?.id, pending.id);
    assert.equal(f.stats().current?.phone, null);
  }
});

test('phone setup rejects malformed detection and send results without creating a usable attempt', async () => {
  for (const failure of ['detect', 'send_otp'] as const) {
    for (const data of [undefined, null, [], {}, { network: 'Globe/TM' }, { otp_code: '123' }]) {
      const f = fixture();
      const provider = new Iprog('TEST_ONLY', (async (url) => {
        if (String(url).endsWith(`/${failure}`)) return Response.json({ status: 'success', data });
        return Response.json({ status: 'success', data: { network: 'Globe/TM', is_smart_tnt: false } });
      }) as typeof fetch);
      const service = new AccountService(f.store, f.attempts, provider);
      await assert.rejects(service.start(identity, { phone: '09171234567' }, randomUUID()), (error: unknown) => {
        assert.ok(error instanceof SmsProviderError);
        assert.equal(error.diagnostic.category, 'malformed_response');
        assert.equal(error.diagnostic.operation, failure);
        return true;
      });
      assert.equal(f.stats().pending, null);
      assert.equal(f.stats().current?.phone, null);
    }
  }
});

test('missing SMS configuration stays unavailable through account setup and preferences', async () => {
  for (const token of [undefined, '', '   ']) {
    const f = fixture({ ...account, phone: '+639171234567' });
    const provider = new Iprog(token, (async () => { throw new Error('Must not call the provider'); }) as typeof fetch);
    const service = new AccountService(f.store, f.attempts, provider);
    for (const action of [() => service.start({ ...identity, recent: true }, { phone: '09171234568' }, randomUUID()),
      () => service.save(identity, { ...base, smsEnabled: true }, randomUUID())]) {
      await assert.rejects(action(), (error: unknown) => {
        assert.ok(error instanceof SmsProviderError);
        assert.equal(error.code, 'SMS_UNAVAILABLE');
        assert.equal(error.diagnostic.category, 'configuration');
        assert.equal(error.diagnostic.httpStatus, null);
        return true;
      });
    }
  }
});

test('genuine local code mismatch consumes a wrong-code attempt without calling IPROG verification', async () => {
  const f = fixture();
  let digest = '';
  f.attempts.arm = async (_user, _attempt, proof) => { digest = proof; };
  f.attempts.matches = async (_user, _attempt, proof) => digest === proof;
  const provider = new Iprog('TEST_ONLY', (async (url) => {
    if (String(url).endsWith('/detect')) return Response.json({ status: 'success', data: { network: 'Globe/TM', is_smart_tnt: false } });
    if (String(url).endsWith('/send_otp')) return Response.json({ status: 'success', data: { otp_code: '123456' } });
    throw new Error('Wrong local code must not reach verification');
  }) as typeof fetch);
  const service = new AccountService(f.store, f.attempts, provider);
  const pending = await service.start(identity, { phone: '09171234567' }, randomUUID());
  await assert.rejects(service.verify(identity, { attemptId: pending.id, code: '654321' }, randomUUID()), { code: 'INVALID_CODE' });
  assert.equal(f.stats().failures, 1);
  assert.equal(f.stats().pending?.id, pending.id);
});

test('provider diagnostics preserve valid Retry-After dates and discard malformed values', async (t) => {
  t.mock.method(Date, 'now', () => Date.parse('2026-10-11T00:00:00Z'));
  for (const [retry, expected] of [['Sun, 11 Oct 2026 00:01:00 GMT', 60], ['Sun, 11 Oct 2026 00:00:00 GMT', 0],
    ['-1', null], ['123456 PRIVATE_TOKEN', null], ['99999999999999', null]] as const) {
    const provider = new Iprog('TEST_ONLY', (async () => new Response('not JSON', { status: 429, headers: { 'retry-after': retry } })) as typeof fetch);
    await assert.rejects(provider.supported('+639171234567'), (error: unknown) => {
      assert.ok(error instanceof SmsProviderError);
      assert.equal(error.diagnostic.retryAfterSeconds, expected);
      assert.equal(error.diagnostic.providerCode, null);
      return true;
    });
  }
});

test('an interrupted provider response retains transport uncertainty and HTTP status', async () => {
  const response = new Response(new ReadableStream({ start(controller) {
    controller.error(new DOMException('PRIVATE_TOKEN 123456', 'TimeoutError'));
  } }), { status: 200 });
  const provider = new Iprog('TEST_ONLY', (async () => response) as typeof fetch);
  await assert.rejects(provider.verify('+639171234567', '123456'), (error: unknown) => {
    assert.ok(error instanceof SmsProviderError);
    assert.equal(error.diagnostic.category, 'transport_uncertain');
    assert.equal(error.diagnostic.failureSource, 'transport');
    assert.equal(error.diagnostic.httpStatus, 200);
    assert.doesNotMatch(JSON.stringify(error), /PRIVATE_TOKEN|123456/);
    return true;
  });
});

test('account setup preserves documented unsupported network results', async () => {
  for (const body of [
    { status: 'success', data: { network: 'Smart/TNT', is_smart_tnt: true } },
    { status: 'error', message: 'Invalid phone number format. Philippine mobile numbers must be in format: 09XXXXXXXXX or +639XXXXXXXXX (11 digits total)',
      data: { network: 'Invalid Format', is_smart_tnt: false } },
  ]) {
    const f = fixture();
    const service = new AccountService(f.store, f.attempts, new Iprog('TEST_ONLY', (async () => Response.json(body)) as typeof fetch));
    await assert.rejects(service.start(identity, { phone: '09171234567' }, randomUUID()), { code: 'SMS_UNSUPPORTED' });
    assert.equal(f.stats().pending, null);
  }
});

test('verification rate limits retain attempts and log safe request diagnostics', async (t) => {
  const f = fixture();
  let limited = true;
  const logs: string[] = [];
  t.mock.method(console, 'error', (line: string) => logs.push(line));
  const provider = new Iprog('PRIVATE_TOKEN', (async (url) => {
    if (String(url).endsWith('/detect')) return Response.json({ status: 'success', data: { network: 'Globe/TM', is_smart_tnt: false } });
    if (String(url).endsWith('/send_otp')) return Response.json({ status: 'success', data: { otp_code: '123456' } });
    if (!limited) return Response.json({ status: 'success', message: 'OTP verified successfully' });
    return Response.json({ status: 429, message: 'PRIVATE_TOKEN +639171234567 123456 PRIVATE_MESSAGE', code: 'PRIVATE_TOKEN' },
      { status: 429, headers: { 'retry-after': '30' } });
  }) as typeof fetch);
  const service = new AccountService(f.store, f.attempts, provider);
  let digest = '';
  f.attempts.arm = async (_user, _attempt, proof) => { digest = proof; };
  f.attempts.matches = async (_user, _attempt, proof) => digest === proof;
  const pending = await service.start(identity, { phone: '09171234567' }, randomUUID());
  const server = createApp({ check: async () => {}, search: async () => [], findById: async () => null }, undefined,
    { service, authenticate: async () => identity }).listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('No server address');
  try {
    const response = await fetch(`http://127.0.0.1:${address.port}/api/v1/account/phone/verify`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ attemptId: pending.id, code: '123456' }),
    });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error.code, 'SMS_UNAVAILABLE');
    assert.equal(f.stats().failures, 0);
    assert.equal(f.stats().pending?.id, pending.id);
    assert.deepEqual(JSON.parse(logs[0]!), { service: 'backend-api', event: 'sms_provider_failed',
      requestId: response.headers.get('x-request-id'), provider: 'iprog', operation: 'verify_otp',
      category: 'rate_limit', failureSource: 'http', providerCode: 429, httpStatus: 429, retryAfterSeconds: 30 });
    assert.doesNotMatch(logs.join(''), /PRIVATE_TOKEN|123456|639171234567|PRIVATE_MESSAGE/);
    limited = false;
    const verified = await service.verify(identity, { attemptId: pending.id, code: '123456' }, randomUUID());
    assert.equal(verified.phone, '+639171234567');
    assert.equal(verified.smsEnabled, false);
  } finally { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); }
});
