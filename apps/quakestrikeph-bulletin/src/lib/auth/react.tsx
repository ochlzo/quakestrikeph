import { AuthenticateWithRedirectCallback, ClerkProvider, TaskChooseOrganization, TaskSetupMFA,
  useAuth, useClerk, useReverification, useSession, useUser } from '@clerk/react';
import { useSignIn, useSignUp } from '@clerk/react/legacy';
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { EmailProof } from './email-proof';
import { createIdentity, identitySessionMarker, updateRequiredPassword, type IdentityEvent } from './protocol';

export function IdentityProvider({ publishableKey, account = false, children }: {
  publishableKey: string; account?: boolean; children: ReactNode;
}) {
  return <ClerkProvider publishableKey={publishableKey} {...(account ? {
    signInUrl: '/sign-in', signUpUrl: '/sign-up',
    signInFallbackRedirectUrl: '/alerts', signUpFallbackRedirectUrl: '/alerts',
    taskUrls: { 'reset-password': '/sign-in', 'setup-mfa': '/sign-in', 'choose-organization': '/sign-in' },
  } : {})}>{children}</ClerkProvider>;
}
export function IdentityCallback() {
  return <AuthenticateWithRedirectCallback signInUrl="/sign-in" signUpUrl="/sign-up"
    signInFallbackRedirectUrl="/alerts" signUpFallbackRedirectUrl="/alerts" />;
}
export function IdentityTask() {
  const { session } = useSession();
  if (session?.currentTask?.key === 'setup-mfa') return <TaskSetupMFA redirectUrlComplete="/alerts" />;
  if (session?.currentTask?.key === 'choose-organization') return <TaskChooseOrganization redirectUrlComplete="/alerts" />;
  return <p>Please sign in again to complete account verification.</p>;
}
export function useIdentitySession({ allowPending = false }: { allowPending?: boolean } = {}) {
  const { isLoaded, isSignedIn, userId, sessionId } = useAuth({ treatPendingAsSignedOut: !allowPending });
  return { loaded: isLoaded, signedIn: !!isSignedIn,
    marker: isLoaded ? identitySessionMarker(userId, sessionId) : 'loading' };
}
export function useIdentity(emit: (event: IdentityEvent) => void) {
  const auth = useAuth({ treatPendingAsSignedOut: false });
  const { user } = useUser();
  const { session } = useSession();
  const clerk = useClerk();
  const { signIn } = useSignIn();
  const { signUp } = useSignUp();
  const active = useRef(true);
  useLayoutEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);
  const updateTaskPassword = useReverification((password: string, isCurrent: () => boolean) =>
    updateRequiredPassword(user, password, isCurrent));
  const marker = identitySessionMarker(auth.userId, auth.sessionId);
  const proof = useRef({ marker, value: new EmailProof() });
  if (proof.current.marker !== marker) proof.current = { marker, value: new EmailProof() };
  const identity = createIdentity({ signIn, signUp, user, session, clerk, getToken: auth.getToken,
    // Read the live client, even after the account island unmounts during Astro navigation.
    sessionMarker: () => identitySessionMarker(clerk.user?.id, clerk.session?.id), updateTaskPassword,
  }, { marker, screenActive: () => active.current, emit, emailProof: proof.current.value });
  return { ...identity,
    session: { loaded: auth.isLoaded, signedIn: !!auth.isSignedIn, marker,
      requiredStep: session?.currentTask ? session.currentTask.key === 'reset-password' ? 'new-password' as const : 'verification' as const : null },
    view: { hasPassword: !!user?.passwordEnabled, email: user?.primaryEmailAddress?.emailAddress, avatarUrl: user?.imageUrl },
  };
}
