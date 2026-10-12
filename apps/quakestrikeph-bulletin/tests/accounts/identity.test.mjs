import assert from 'node:assert/strict';
import test from 'node:test';
import { createIdentity, updateRequiredPassword } from '../../src/lib/auth/protocol.ts';
import { PreferenceSaves } from '../../src/features/accounts/preference-saves.ts';

const complete = { status: 'complete', createdSessionId: 'created-session' };
const emailFactor = { strategy: 'email_code', emailAddressId: 'verified-email' };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture() {
  const state = { marker: 'original-session', active: true };
  const calls = [], events = [];
  const call = (name, value) => async options => { calls.push({ name, options }); return typeof value === 'function' ? value(options) : value; };
  const provider = {
    sessionMarker: () => state.marker,
    getToken: call('token', 'original-token'),
    user: { passwordEnabled: true, updatePassword: call('password', undefined) },
    signIn: {
      supportedSecondFactors: [emailFactor],
      create: call('login', complete),
      prepareSecondFactor: call('device-prepare', undefined),
      attemptSecondFactor: call('device-verify', complete),
      attemptFirstFactor: call('recovery-verify', { status: 'needs_new_password' }),
      resetPassword: call('recovery-password', complete),
      authenticateWithRedirect: call('google', undefined),
    },
    signUp: {
      create: call('signup', undefined),
      prepareEmailAddressVerification: call('signup-prepare', undefined),
      attemptEmailAddressVerification: call('signup-verify', complete),
    },
    session: {
      startVerification: call('proof-start', { supportedFirstFactors: [{ strategy: 'password' }, emailFactor] }),
      prepareFirstFactorVerification: call('proof-prepare', undefined),
      attemptFirstFactorVerification: call('proof-verify', { status: 'complete' }),
    },
    clerk: {
      setActive: call('activate', () => { state.marker = 'created-session'; }),
      signOut: call('signout', () => { state.marker = 'signed-out'; }),
    },
  };
  provider.updateTaskPassword = (password, current) => updateRequiredPassword(provider.user, password, current);
  const identity = createIdentity(provider, { marker: state.marker, screenActive: () => state.active,
    emit: event => { events.push(event); calls.push({ name: event }); } });
  return { identity, provider, state, calls, events, call, methods: () => calls.map(value => value.name) };
}

test('password login prepares device proof after clearing consumed credentials', async () => {
  const f = fixture();
  f.provider.signIn.create = f.call('login', { status: 'needs_client_trust', createdSessionId: null });
  const outcome = await f.identity.signInWithPassword('reader@example.invalid', 'password');
  assert.equal(outcome.step, 'device-code');
  assert.equal(typeof outcome.sentAt, 'number');
  assert.deepEqual(f.methods(), ['login', 'authentication-fields-consumed', 'device-prepare']);
  assert.deepEqual(f.calls[2].options, { strategy: 'email_code', emailAddressId: 'verified-email' });
});

test('first activation completes despite its expected session transition', async () => {
  const f = fixture();
  assert.deepEqual((await f.identity.verifySignupEmail('123456')).step, 'signed-in');
  assert.equal(f.state.marker, 'created-session');
  assert.deepEqual(f.methods(), ['signup-verify', 'authentication-fields-consumed', 'activate']);
});

test('unavailable factors produce a safe login failure after credential consumption', async () => {
  const f = fixture();
  f.provider.signIn.create = f.call('login', { status: 'needs_second_factor', createdSessionId: null });
  f.provider.signIn.supportedSecondFactors = [];
  assert.deepEqual(await f.identity.signInWithPassword('email', 'password'), {
    kind: 'failed', message: 'Check your email and password, then try again.',
  });
  assert.deepEqual(f.methods(), ['login', 'authentication-fields-consumed']);
});

test('signup records the anonymous profile handoff before preparing email proof', async () => {
  const f = fixture();
  const outcome = await f.identity.createAccount('email', 'password', () => f.calls.push({ name: 'profile-handoff' }));
  assert.equal(outcome.step, 'signup-code');
  assert.deepEqual(f.methods(), ['signup', 'profile-handoff', 'signup-prepare']);
});

test('signup maps breached-password errors without exposing the provider error', async () => {
  const f = fixture();
  f.provider.signUp.create = async () => { throw { errors: [{ code: 'form_password_pwned' }] }; };
  assert.deepEqual(await f.identity.createAccount('email', 'password', assert.fail), {
    kind: 'failed', field: 'password', message: 'This password has appeared in a data breach. Choose a different password.',
  });
});

for (const operation of ['requestRecoveryCode', 'resendRecoveryCode']) {
  test(`${operation} has the same public outcome when Clerk rejects an address`, async () => {
    const f = fixture();
    f.provider.signIn.create = async () => { throw new Error('Account does not exist'); };
    const outcome = await f.identity[operation]('unknown@example.invalid');
    assert.equal(outcome.kind, 'completed');
    assert.equal(outcome.step, 'recovery-code');
    assert.equal(typeof outcome.sentAt, 'number');
  });
}

test('Google login keeps its explicit account chooser and callback configuration', async () => {
  const f = fixture();
  await f.identity.signInWithGoogle();
  assert.deepEqual(f.calls[0].options, { strategy: 'oauth_google', redirectUrl: '/sso-callback',
    redirectUrlComplete: '/alerts', oidcPrompt: 'select_account' });
});

test('reverification prefers an available password, otherwise prepares email proof', async () => {
  const f = fixture();
  assert.equal((await f.identity.prepareReverification()).step, 'current-password');
  f.provider.user.passwordEnabled = false;
  assert.equal((await f.identity.prepareReverification()).step, 'email-code');
  assert.deepEqual(f.methods(), ['proof-start', 'proof-start', 'proof-prepare']);
});

test('completed proof refreshes its token before returning to the account flow', async () => {
  const f = fixture();
  assert.equal((await f.identity.verifyIdentity('email-code', '123456')).step, 'identity-verified');
  assert.deepEqual(f.methods(), ['proof-verify', 'token']);
  assert.deepEqual(f.calls[1].options, { skipCache: true });
});

test('incomplete proof never refreshes the token', async () => {
  const f = fixture();
  f.provider.session.attemptFirstFactorVerification = f.call('proof-verify', { status: 'needs_first_factor' });
  assert.equal((await f.identity.verifyIdentity('current-password', 'password')).kind, 'failed');
  assert.deepEqual(f.methods(), ['proof-verify']);
});

test('token rejection fails proof continuation; null refresh retains existing continuation', async () => {
  const f = fixture();
  f.provider.getToken = async () => { throw new Error('Provider offline'); };
  assert.equal((await f.identity.verifyIdentity('current-password', 'password')).kind, 'failed');
  f.provider.getToken = async () => null;
  assert.equal((await f.identity.verifyIdentity('current-password', 'password')).step, 'identity-verified');
});

for (const result of ['success', 'failure']) {
  test(`old login ${result} cannot consume fields or activate a session`, async () => {
    const f = fixture(), response = deferred();
    f.provider.signIn.create = () => response.promise;
    const operation = f.identity.signInWithPassword('email', 'password');
    f.state.marker = 'another-session';
    if (result === 'success') response.resolve(complete);
    else response.reject(new Error('Late provider error'));
    assert.deepEqual(await operation, { kind: 'ignored' });
    assert.deepEqual(f.events, []);
    assert.deepEqual(f.methods(), []);
  });
}

test('session change between signup stages blocks proof preparation and profile handoff', async () => {
  const f = fixture(), response = deferred();
  f.provider.signUp.create = () => response.promise;
  const operation = f.identity.createAccount('email', 'password', assert.fail);
  f.state.marker = 'another-session';
  response.resolve();
  assert.deepEqual(await operation, { kind: 'ignored' });
  assert.deepEqual(f.methods(), []);
});

test('screen requests use cached GET tokens and fresh mutation tokens', async () => {
  const f = fixture();
  const send = f.call('http', { saved: true });
  await f.identity.screenRequest(send);
  await f.identity.screenRequest(send, '/profile', 'PUT', { displayName: 'Reader' });
  assert.deepEqual(f.calls.filter(value => value.name === 'token').map(value => value.options),
    [{ skipCache: false }, { skipCache: true }]);
});

test('background saves survive unmount while screen answers become obsolete', async () => {
  const f = fixture(), response = deferred();
  const saving = f.identity.backgroundRequest(() => response.promise, '/preferences', 'PUT', {});
  await tick();
  f.state.active = false;
  response.resolve({ saved: true });
  assert.deepEqual(await saving, { saved: true });
  assert.deepEqual(await f.identity.backgroundRequest(async () => ({ anotherSave: true }), '/preferences', 'PUT', {}), { anotherSave: true });
  await assert.rejects(f.identity.screenRequest(assert.fail), /session changed/);
  assert.deepEqual(f.calls[0].options, { skipCache: true });
});

test('session change during token acquisition blocks an old background request', async () => {
  const f = fixture(), token = deferred();
  f.provider.getToken = () => token.promise;
  const saving = f.identity.backgroundRequest(assert.fail, '/preferences', 'PUT', {});
  const rejected = assert.rejects(saving, /session changed/);
  f.state.marker = 'another-session';
  token.resolve('new-user-token');
  await rejected;
});

test('session change suppresses a late token failure before transport', async () => {
  const f = fixture(), token = deferred();
  f.provider.getToken = () => token.promise;
  const saving = f.identity.backgroundRequest(assert.fail, '/preferences', 'PUT', {});
  const rejected = assert.rejects(saving, /session changed/);
  f.state.marker = 'another-session';
  token.reject(new Error('Former provider error'));
  await rejected;
});

for (const result of ['success', 'failure']) {
  test(`screen unmount suppresses a submitted request's ${result}`, async () => {
    const f = fixture(), response = deferred();
    const saving = f.identity.screenRequest(() => response.promise, '/profile', 'PUT', {});
    const rejected = assert.rejects(saving, /session changed/);
    await tick();
    f.state.active = false;
    if (result === 'success') response.resolve({ saved: true });
    else response.reject(new Error('Former screen error'));
    await rejected;
  });
}

for (const result of ['success', 'failure']) {
  test(`old background ${result} is suppressed after transport completes`, async () => {
    const f = fixture(), response = deferred();
    const saving = f.identity.backgroundRequest(() => response.promise, '/preferences', 'PUT', {});
    const rejected = assert.rejects(saving, /session changed/);
    await tick();
    f.state.marker = 'another-session';
    if (result === 'success') response.resolve({ saved: true });
    else response.reject(new Error('Late backend error'));
    await rejected;
  });
}

for (const result of ['success', 'failure']) {
  test(`session change after navigation cancels preference saves without an obsolete ${result} notification`, async () => {
    const f = fixture(), response = deferred(), submitted = deferred();
    const notices = [];
    const account = { emailEnabled: false, smsEnabled: false, magnitude: 4.5, nearbyOnly: false,
      latitude: null, longitude: null, distanceKm: null };
    let writes = 0;
    const queue = new PreferenceSaves(account, value => f.identity.backgroundRequest(() => {
      writes++;
      submitted.resolve();
      return response.promise;
    }, '/preferences', 'PUT', value, () => queue.cancel()), message => notices.push(message));
    queue.save({ emailEnabled: true }, 0);
    await submitted.promise;
    f.state.active = false;
    queue.save({ magnitude: 5 }, 0);
    f.state.marker = 'another-session';
    if (result === 'success') response.resolve({ ...account, emailEnabled: true });
    else response.reject(new Error('Late backend failure'));
    await tick();
    queue.save({ smsEnabled: true }, 0);
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.deepEqual(notices, []);
    assert.equal(writes, 1, 'The obsolete queue must cancel later writes');
    assert.equal(queue.snapshot.account.emailEnabled, false, 'The old result must not update the account');
    queue.cancel();
  });
}

test('required password proof retries the real guarded callback before activation', async () => {
  const f = fixture();
  let attempts = 0;
  f.provider.user.updatePassword = f.call('password', () => {
    if (++attempts === 1) throw new Error('Needs proof');
  });
  f.provider.updateTaskPassword = async (password, current) => {
    try { await updateRequiredPassword(f.provider.user, password, current); }
    catch {
      f.calls.push({ name: 'interactive-proof' });
      await updateRequiredPassword(f.provider.user, password, current);
    }
  };
  // Clearing a task keeps the existing session identity.
  f.provider.clerk.setActive = f.call('activate', undefined);
  assert.equal((await f.identity.saveRequiredPassword('new-password')).step, 'task-password-saved');
  assert.deepEqual(f.methods(), ['password', 'interactive-proof', 'password', 'task-password-consumed', 'activate']);
});

test('identity change during task proof prevents its retry and activation', async () => {
  const f = fixture();
  f.provider.user.updatePassword = async () => { throw new Error('Needs proof'); };
  f.provider.updateTaskPassword = async (password, current) => {
    try { await updateRequiredPassword(f.provider.user, password, current); }
    catch {
      f.state.marker = 'another-session';
      await updateRequiredPassword(f.provider.user, password, current);
    }
  };
  assert.deepEqual(await f.identity.saveRequiredPassword('new-password'), { kind: 'ignored' });
  assert.deepEqual(f.events, []);
  assert.deepEqual(f.methods(), []);
});

test('late task-password proof requirement is swallowed before Clerk opens proof', async () => {
  const f = fixture(), response = deferred();
  f.provider.user.updatePassword = () => response.promise;
  const operation = f.identity.saveRequiredPassword('new-password');
  f.state.marker = 'another-session';
  response.reject(new Error('Late proof requirement'));
  assert.deepEqual(await operation, { kind: 'ignored' });
  assert.deepEqual(f.events, []);
});
