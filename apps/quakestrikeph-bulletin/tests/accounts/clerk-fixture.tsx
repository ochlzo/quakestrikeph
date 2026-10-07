// This module is reachable only from the isolated Vite/Astro test configurations.
// It is never imported or aliased by the production configuration.
import { useSyncExternalStore, type ReactNode } from 'react';
const query = new URLSearchParams(typeof location === 'undefined' ? '' : location.search);
const fixtureStorage = typeof sessionStorage === 'undefined' ? { getItem: (_key: string) => null, setItem: (_key: string, _value: string) => {} } : sessionStorage;
let signed = query.has('signed') ? query.get('signed') === '1' : fixtureStorage.getItem('fixture:signed') === '1';
fixtureStorage.setItem('fixture:signed', signed ? '1' : '0');
const listeners = new Set<() => void>();
const subscribe = (callback: () => void) => { listeners.add(callback); return () => { listeners.delete(callback); }; };
let userId = 'fixture-user', sessionId = 'fixture-session';
const snapshot = () => signed ? `${userId}:${sessionId}` : 'signed-out';
// Browser tests control individual provider stages without live Clerk requests.
type Reply = { defer?: boolean; fail?: boolean; reverify?: boolean; value?: unknown };
type Call = { method: string; args: unknown; settled: boolean };
const replies: Record<string, Reply[]> = {};
const releases: Record<string, (() => void)[]> = {};
const calls: Call[] = [];
const control = {
  calls,
  queue(method: string, reply: Reply) { (replies[method] ??= []).push(reply); },
  release(method: string) { releases[method]?.shift()?.(); },
};
declare global { interface Window { clerkFixture: typeof control } }
if (typeof window !== 'undefined') window.clerkFixture = control;
async function provider<T>(method: string, args: unknown, work: () => T | Promise<T>): Promise<T> {
  const call = { method, args, settled: false };
  calls.push(call);
  const reply = replies[method]?.shift();
  try {
    if (reply?.defer) await new Promise<void>(resolve => (releases[method] ??= []).push(resolve));
    if (reply?.reverify) throw { errors: [{ code: 'session_reverification_required' }] };
    if (reply?.fail) throw new Error(`Fixture ${method} failure`);
    return reply && 'value' in reply ? reply.value as T : await work();
  } finally { call.settled = true; }
}
if (typeof window !== 'undefined') window.addEventListener('fixture:auth', event => {
  const next = (event as CustomEvent<{ userId: string | null; sessionId: string | null }>).detail;
  signed = !!next.userId && !!next.sessionId;
  sessionStorage.setItem('fixture:signed', signed ? '1' : '0');
  userId = next.userId ?? '';
  sessionId = next.sessionId ?? '';
  session.currentTask = null;
  listeners.forEach(fn => fn());
});
export const ClerkProvider = ({ children }: { children: ReactNode }) => children;
export const AuthenticateWithRedirectCallback = () => <p>OAuth callback fixture</p>;
export const TaskSetupMFA = () => <p>Required multi-factor setup</p>;
export const TaskChooseOrganization = () => <p>Required organization choice</p>;
export function useAuth() {
  const identity = useSyncExternalStore(subscribe, snapshot, () => 'signed-out');
  const isSignedIn = identity !== 'signed-out';
  return { isLoaded: true, isSignedIn, userId: isSignedIn ? userId : null,
    sessionId: isSignedIn ? sessionId : null, getToken: (options?: { skipCache?: boolean }) => provider('getToken', options, () => {
      console.info(`fixture:token-mode:${options?.skipCache ? 'fresh' : 'cached'}`);
      return isSignedIn ? 'FIXTURE_SESSION' : null;
    }) };
}
let passwordError = query.get('password-error') === '1';
export const useUser = () => ({ user: {
  primaryEmailAddress: { emailAddress: 'maria@example.com' },
  passwordEnabled: query.get('passwordless') !== '1',
  updatePassword: (options: unknown) => provider('updatePassword', options, () => {
    if (passwordError) { passwordError = false; throw new Error('Fixture provider failure'); }
    console.info('fixture:password-write:update');
  }),
  emailAddresses: [],
} });
export const useReverification = <Args extends unknown[], Result,>(work: (...args: Args) => Promise<Result>) => async (...args: Args) => {
  try { return await work(...args); }
  catch (failure) {
    if (typeof failure !== 'object' || !failure || !('errors' in failure) ||
      !Array.isArray(failure.errors) || !failure.errors.some(error => error.code === 'session_reverification_required')) throw failure;
    // Match Clerk's proof-before-retry behavior, including cancellation.
    await provider('reverification', null, () => {});
    return work(...args);
  }
};
const session = {
  currentTask: query.has('task') ? { key: query.get('task')! } : null,
  startVerification: (options: unknown) => provider('startVerification', options, () => ({ supportedFirstFactors: query.has('missing-factor') ? [] : [{ strategy: 'password' }, { strategy: 'email_code', emailAddressId: 'fixture-email' }] })),
  prepareFirstFactorVerification: (options: unknown) => provider('prepareFirstFactorVerification', options, () => {}),
  attemptFirstFactorVerification: (options: { password?: string; code?: string }) => provider('attemptFirstFactorVerification', options, () => {
    const { password, code } = options;
    if (password !== 'fixture-password' && code !== '111111') throw new Error('wrong factor'); return { status: 'complete' };
  }),
};
export const useSession = () => ({ session });
export const useClerk = () => ({
  setActive: (options: unknown) => provider('setActive', options, () => { signed = true; sessionStorage.setItem('fixture:signed', '1'); session.currentTask = null; listeners.forEach(fn => fn()); }),
  signOut: (options?: { redirectUrl?: string }) => provider('signOut', options, () => {
    if (query.has('signout-error')) throw new Error('Fixture sign-out failure');
    signed = false; sessionStorage.setItem('fixture:signed', '0'); listeners.forEach(fn => fn());
    if (options?.redirectUrl) location.assign(options.redirectUrl);
  }),
});
const complete = { status: 'complete', createdSessionId: 'fixture-session' };
const signIn = {
  supportedSecondFactors: query.has('missing-factor') ? [] : [{ strategy: 'email_code', emailAddressId: 'fixture-email' }],
  create: (options: { password?: string; strategy?: string }) => provider('signIn.create', options, () => {
    const { password, strategy } = options;
    if (strategy) return { status: 'needs_first_factor', createdSessionId: null };
    if (password !== 'fixture-password') throw new Error('Invalid login');
    return { status: 'needs_client_trust', createdSessionId: null };
  }),
  prepareSecondFactor: (options: unknown) => provider('prepareSecondFactor', options, () => {}),
  attemptSecondFactor: (options: { code: string }) => provider('attemptSecondFactor', options, () => { if (options.code !== '111111') throw new Error('Invalid code'); return complete; }),
  attemptFirstFactor: (options: { code: string }) => provider('attemptFirstFactor', options, () => { if (options.code !== '111111') throw new Error('Invalid code'); return { status: 'needs_new_password', createdSessionId: null }; }),
  resetPassword: (options: unknown) => provider('resetPassword', options, () => { console.info('fixture:password-write:recovery'); return complete; }),
  authenticateWithRedirect: (options: unknown) => provider('authenticateWithRedirect', options, () => { throw new Error('Fixture OAuth cancellation'); }),
};
const signUp = {
  create: (options: { password?: string }) => provider('signUp.create', options, () => {
    const { password } = options;
    if (password === 'Fixture-breached-password1') throw { errors: [{ code: 'form_password_pwned', meta: { paramName: 'password' } }] };
  }), prepareEmailAddressVerification: (options: unknown) => provider('prepareEmailAddressVerification', options, () => {}),
  attemptEmailAddressVerification: (options: { code: string }) => provider('attemptEmailAddressVerification', options, () => { if (options.code !== '111111') throw new Error('Invalid code'); return complete; }),
};
export const useSignIn = () => ({ signIn });
export const useSignUp = () => ({ signUp });
