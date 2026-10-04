// This module is reachable only from the separate test Vite configuration.
// It is never imported or aliased by Astro or the production build.
import { useSyncExternalStore, type ReactNode } from 'react';
let signed = new URLSearchParams(location.search).get('signed') === '1';
const listeners = new Set<() => void>();
const subscribe = (callback: () => void) => { listeners.add(callback); return () => { listeners.delete(callback); }; };
let userId = 'fixture-user', sessionId = 'fixture-session';
const snapshot = () => signed ? `${userId}:${sessionId}` : 'signed-out';
window.addEventListener('fixture:auth', event => {
  const next = (event as CustomEvent<{ userId: string | null; sessionId: string | null }>).detail;
  signed = !!next.userId && !!next.sessionId;
  userId = next.userId ?? '';
  sessionId = next.sessionId ?? '';
  listeners.forEach(fn => fn());
});
export const ClerkProvider = ({ children }: { children: ReactNode }) => children;
export const AuthenticateWithRedirectCallback = () => <p>OAuth callback fixture</p>;
export const TaskSetupMFA = () => <p>Required multi-factor setup</p>;
export const TaskChooseOrganization = () => <p>Required organization choice</p>;
export function useAuth() {
  const identity = useSyncExternalStore(subscribe, snapshot);
  const isSignedIn = identity !== 'signed-out';
  return { isLoaded: true, isSignedIn, userId: isSignedIn ? userId : null,
    sessionId: isSignedIn ? sessionId : null, getToken: async (options?: { skipCache?: boolean }) => {
      console.info(`fixture:token-mode:${options?.skipCache ? 'fresh' : 'cached'}`);
      return isSignedIn ? 'FIXTURE_SESSION' : null;
    } };
}
let passwordError = new URLSearchParams(location.search).get('password-error') === '1';
export const useUser = () => ({ user: {
  primaryEmailAddress: { emailAddress: 'maria@example.com' },
  passwordEnabled: new URLSearchParams(location.search).get('passwordless') !== '1',
  updatePassword: async () => {
    if (passwordError) { passwordError = false; throw new Error('Fixture provider failure'); }
    console.info('fixture:password-write:update');
  },
  emailAddresses: [],
} });
export const useReverification = <Args extends unknown[], Result,>(work: (...args: Args) => Promise<Result>) => work;
const session = {
  currentTask: new URLSearchParams(location.search).get('task') === 'reset-password'
    ? { key: 'reset-password' } : null,
  startVerification: async () => ({ supportedFirstFactors: [{ strategy: 'password' }, { strategy: 'email_code', emailAddressId: 'fixture-email' }] }),
  prepareFirstFactorVerification: async () => {},
  attemptFirstFactorVerification: async ({ password, code }: { password?: string; code?: string }) => {
    if (password !== 'fixture-password' && code !== '111111') throw new Error('wrong factor'); return { status: 'complete' };
  },
};
export const useSession = () => ({ session });
export const useClerk = () => ({
  setActive: async () => { signed = true; session.currentTask = null; listeners.forEach(fn => fn()); },
  signOut: async (options?: { redirectUrl?: string }) => {
    if (new URLSearchParams(location.search).has('signout-error')) throw new Error('Fixture sign-out failure');
    signed = false; listeners.forEach(fn => fn());
    if (options?.redirectUrl) location.assign(options.redirectUrl);
  },
});
const complete = { status: 'complete', createdSessionId: 'fixture-session' };
const signIn = {
  supportedSecondFactors: [{ strategy: 'email_code', emailAddressId: 'fixture-email' }],
  create: async ({ password, strategy }: { password?: string; strategy?: string }) => {
    if (strategy) return { status: 'needs_first_factor', createdSessionId: null };
    if (password !== 'fixture-password') throw new Error('Invalid login');
    return { status: 'needs_client_trust', createdSessionId: null };
  },
  prepareSecondFactor: async () => {},
  attemptSecondFactor: async ({ code }: { code: string }) => { if (code !== '111111') throw new Error('Invalid code'); return complete; },
  attemptFirstFactor: async ({ code }: { code: string }) => { if (code !== '111111') throw new Error('Invalid code'); return { status: 'needs_new_password', createdSessionId: null }; },
  resetPassword: async () => { console.info('fixture:password-write:recovery'); return complete; },
  authenticateWithRedirect: async () => { throw new Error('Fixture OAuth cancellation'); },
};
const signUp = {
  create: async ({ password }: { password?: string }) => {
    if (password === 'Fixture-breached-password1') throw { errors: [{ code: 'form_password_pwned', meta: { paramName: 'password' } }] };
  }, prepareEmailAddressVerification: async () => {},
  attemptEmailAddressVerification: async ({ code }: { code: string }) => { if (code !== '111111') throw new Error('Invalid code'); return complete; },
};
export const useSignIn = () => ({ signIn });
export const useSignUp = () => ({ signUp });
