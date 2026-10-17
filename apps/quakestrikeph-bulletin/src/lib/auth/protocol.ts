import type { useAuth, useClerk, useSession, useUser } from '@clerk/react';
import type { useSignIn, useSignUp } from '@clerk/react/legacy';
import { EmailProof } from './email-proof.ts';

// This dependency seam stays private to identity; tests replace raw Clerk calls.
export type ClerkIdentity = {
  signIn: ReturnType<typeof useSignIn>['signIn'];
  signUp: ReturnType<typeof useSignUp>['signUp'];
  user: ReturnType<typeof useUser>['user'];
  session: ReturnType<typeof useSession>['session'];
  clerk: Pick<ReturnType<typeof useClerk>, 'setActive' | 'signOut'>;
  getToken: ReturnType<typeof useAuth>['getToken'];
  sessionMarker: () => string;
  updateTaskPassword: (password: string, isCurrent: () => boolean) => Promise<unknown>;
};

export type ProofMethod = 'current-password' | 'email-code';
export type IdentityStep = 'signed-in' | 'signup-code' | 'device-code' | 'recovery-code' |
  'recovery-password' | ProofMethod | 'identity-verified' | 'password-saved' | 'task-password-saved' | 'signed-out';
export type IdentityOutcome =
  | { kind: 'completed'; step: IdentityStep; sentAt?: number }
  | { kind: 'failed'; message: string; field?: 'password' }
  | { kind: 'ignored' };
export type IdentityEvent = 'authentication-fields-consumed' | 'task-password-consumed';
type AccountRequest = <T>(token: string | null, path?: string, method?: string, body?: unknown) => Promise<T>;
const ignored: IdentityOutcome = { kind: 'ignored' };
const completed = (step: IdentityStep, sentAt?: number): IdentityOutcome => ({ kind: 'completed', step, sentAt });
const recoveryFailure = 'Recovery could not be completed. Check your code or request a new one.';

export function identitySessionMarker(userId: string | null | undefined, sessionId: string | null | undefined) {
  return userId && sessionId ? `${userId}:${sessionId}` : 'signed-out';
}

export async function updateRequiredPassword(user: ClerkIdentity['user'], password: string, isCurrent: () => boolean) {
  // This same callback runs before and after Clerk's interactive proof.
  if (!isCurrent()) return;
  if (!user) throw new Error('Sign in again');
  try { await user.updatePassword({ newPassword: password, signOutOfOtherSessions: true }); }
  catch (failure) {
    // Suppress a late proof requirement before Clerk can open its modal for a different session.
    if (isCurrent()) throw failure;
  }
}

export function createIdentity(provider: ClerkIdentity, options: {
  marker: string;
  screenActive: () => boolean;
  emit: (event: IdentityEvent) => void;
  emailProof?: EmailProof;
}) {
  const emailProof = options.emailProof ?? new EmailProof();
  const sessionCurrent = () => provider.sessionMarker() === options.marker;
  const screenCurrent = () => options.screenActive() && sessionCurrent();
  async function operation(work: () => Promise<IdentityOutcome>, message: string, passwordField = false): Promise<IdentityOutcome> {
    if (!screenCurrent()) return ignored;
    try { return await work(); }
    catch (failure) {
      if (!screenCurrent()) return ignored;
      if (passwordField && typeof failure === 'object' && failure && 'errors' in failure &&
        Array.isArray(failure.errors) && failure.errors.some(error => error?.code === 'form_password_pwned'))
        return { kind: 'failed', field: 'password', message: 'This password has appeared in a data breach. Choose a different password.' };
      return { kind: 'failed', message };
    }
  }
  async function completeAuthentication(attempt: { status: string | null; createdSessionId: string | null }): Promise<IdentityOutcome> {
    if (!screenCurrent()) return ignored;
    options.emit('authentication-fields-consumed');
    if (attempt.status === 'complete' && attempt.createdSessionId) {
      // Activation intentionally changes identity; the account feature resumes from its session observation.
      await provider.clerk.setActive({ session: attempt.createdSessionId });
      return completed('signed-in');
    }
    if (attempt.status === 'needs_client_trust' || attempt.status === 'needs_second_factor') {
      const factor = provider.signIn?.supportedSecondFactors?.find(value => value.strategy === 'email_code');
      if (!factor || !provider.signIn) throw new Error('A verification factor is unavailable');
      await provider.signIn.prepareSecondFactor({ strategy: 'email_code', emailAddressId: factor.emailAddressId });
      return screenCurrent() ? completed('device-code', Date.now()) : ignored;
    }
    throw new Error('Additional account information is needed');
  }
  async function request<T>(send: AccountRequest, path: string, method: string, body: unknown, isCurrent: () => boolean) {
    if (!isCurrent()) throw new Error('The account session changed.');
    try {
      const token = await provider.getToken({ skipCache: method !== 'GET' });
      if (!isCurrent()) throw new Error('The account session changed.');
      return await send<T>(token, path, method, body);
    }
    finally {
      // A submitted request may finish; neither its success nor its failure belongs to a former session.
      if (!isCurrent()) throw new Error('The account session changed.');
    }
  }
  return {
    hasRecentEmailProof: () => screenCurrent() && emailProof.recent(options.marker),
    clearEmailProof: () => emailProof.clear(),
    signInWithPassword: (email: string, password: string) => operation(async () => provider.signIn
      ? completeAuthentication(await provider.signIn.create({ identifier: email, password })) : ignored,
      'Check your email and password, then try again.'),
    createAccount: (email: string, password: string, onCreated: () => void) => operation(async () => {
      if (!provider.signUp) return ignored;
      await provider.signUp.create({ emailAddress: email, password });
      if (!screenCurrent()) return ignored;
      onCreated();
      await provider.signUp.prepareEmailAddressVerification({ strategy: 'email_code' });
      return screenCurrent() ? completed('signup-code', Date.now()) : ignored;
    }, 'The account could not be created. Check the password requirements, or try sign-in and recovery.', true),
    signInWithGoogle: () => operation(async () => {
      if (!provider.signIn) return ignored;
      await provider.signIn.authenticateWithRedirect({ strategy: 'oauth_google', redirectUrl: '/sso-callback',
        redirectUrlComplete: '/alerts', oidcPrompt: 'select_account' });
      return screenCurrent() ? completed('signed-in') : ignored;
    }, 'Google sign-in was not completed. Try again or use your password.'),
    verifySignupEmail: (code: string) => operation(async () => provider.signUp
      ? completeAuthentication(await provider.signUp.attemptEmailAddressVerification({ code })) : ignored,
      'That code did not work. Check it or request a new code.'),
    verifySignInEmail: (code: string) => operation(async () => provider.signIn
      ? completeAuthentication(await provider.signIn.attemptSecondFactor({ strategy: 'email_code', code })) : ignored,
      'That code did not work. Check it or request a new code.'),
    resendSignupEmail: () => operation(async () => {
      await provider.signUp?.prepareEmailAddressVerification({ strategy: 'email_code' });
      return screenCurrent() ? completed('signup-code', Date.now()) : ignored;
    }, 'This request could not be completed. Please try again.'),
    resendSignInEmail: () => operation(async () => {
      const factor = provider.signIn?.supportedSecondFactors?.find(value => value.strategy === 'email_code');
      if (factor) await provider.signIn?.prepareSecondFactor({ strategy: 'email_code', emailAddressId: factor.emailAddressId });
      return screenCurrent() ? completed('device-code', Date.now()) : ignored;
    }, 'This request could not be completed. Please try again.'),
    requestRecoveryCode: (email: string) => operation(async () => {
      if (!provider.signIn) return ignored;
      try { await provider.signIn.create({ strategy: 'reset_password_email_code', identifier: email }); }
      catch { /* Preserve the same public result for existing, Google-only and unknown addresses. */ }
      return screenCurrent() ? completed('recovery-code', Date.now()) : ignored;
    }, recoveryFailure),
    verifyRecoveryCode: (code: string) => operation(async () => {
      if (!provider.signIn) return ignored;
      await provider.signIn.attemptFirstFactor({ strategy: 'reset_password_email_code', code });
      return screenCurrent() ? completed('recovery-password') : ignored;
    }, recoveryFailure),
    saveRecoveredPassword: (password: string) => operation(async () => provider.signIn
      ? completeAuthentication(await provider.signIn.resetPassword({ password, signOutOfOtherSessions: true })) : ignored,
      recoveryFailure),
    resendRecoveryCode: (email: string) => operation(async () => {
      try { await provider.signIn?.create({ strategy: 'reset_password_email_code', identifier: email }); }
      catch { /* Enumeration-safe resend result. */ }
      return screenCurrent() ? completed('recovery-code', Date.now()) : ignored;
    }, 'This request could not be completed. Please try again.'),
    prepareReverification: (method: ProofMethod = 'email-code', force = false) => operation(async () => {
      if (!provider.session) throw new Error('Sign in again');
      if (force) emailProof.clear();
      if (method === 'email-code' && emailProof.recent(options.marker)) return completed('identity-verified');
      const verification = await provider.session.startVerification({ level: 'first_factor' });
      if (!screenCurrent()) return ignored;
      if (method === 'current-password' && provider.user?.passwordEnabled && verification.supportedFirstFactors?.some(value => value.strategy === 'password'))
        return completed('current-password');
      const factor = verification.supportedFirstFactors?.find(value => value.strategy === 'email_code');
      if (!factor || factor.strategy !== 'email_code') throw new Error('Email verification is unavailable');
      await provider.session.prepareFirstFactorVerification({ strategy: 'email_code', emailAddressId: factor.emailAddressId });
      return screenCurrent() ? completed('email-code', Date.now()) : ignored;
    }, 'Identity verification is unavailable. Please sign in again.'),
    verifyIdentity: (method: ProofMethod, value: string) => operation(async () => {
      if (!provider.session) return ignored;
      const verification = await provider.session.attemptFirstFactorVerification(method === 'current-password'
        ? { strategy: 'password', password: value } : { strategy: 'email_code', code: value });
      if (!screenCurrent()) return ignored;
      if (verification.status !== 'complete') throw new Error('Verification is incomplete');
      // Preserve null-refresh behavior: proof completes; the HTTP helper later rejects a missing token.
      await provider.getToken({ skipCache: true });
      if (screenCurrent() && method === 'email-code') emailProof.record(options.marker);
      return screenCurrent() ? completed('identity-verified') : ignored;
    }, 'Identity verification did not work. Check your password or code and try again.'),
    savePassword: (password: string) => operation(async () => {
      if (!provider.user) throw new Error('Sign in again');
      await provider.user.updatePassword({ newPassword: password, signOutOfOtherSessions: true });
      return screenCurrent() ? completed('password-saved') : ignored;
    }, 'The password could not be saved. Try again or verify your email again.'),
    saveRequiredPassword: (password: string) => operation(async () => {
      await provider.updateTaskPassword(password, screenCurrent);
      if (!screenCurrent()) return ignored;
      options.emit('task-password-consumed');
      await provider.clerk.setActive({ session: provider.session });
      return screenCurrent() ? completed('task-password-saved') : ignored;
    }, 'The password could not be saved. Please try again.'),
    signOut: (redirectUrl: '/' | '/sign-in') => operation(async () => {
      emailProof.clear();
      await provider.clerk.signOut({ redirectUrl });
      return completed('signed-out');
    }, 'Sign-out could not be completed. Please try again.'),
    screenRequest: <T>(send: AccountRequest, path = '', method = 'GET', body?: unknown) =>
      request<T>(send, path, method, body, screenCurrent),
    backgroundRequest: async <T>(send: AccountRequest, path = '', method = 'GET', body?: unknown, onSessionChanged?: () => void) => {
      try { return await request<T>(send, path, method, body, sessionCurrent); }
      finally {
        // Cancel the caller's surviving queue before an obsolete rejection can notify.
        if (!sessionCurrent()) onSessionChanged?.();
      }
    },
  };
}
