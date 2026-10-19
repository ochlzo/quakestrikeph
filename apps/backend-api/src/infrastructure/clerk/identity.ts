import { createClerkClient } from '@clerk/backend';
import { AccountError, type Identity } from '../../domain/accounts.js';
import type { AuthenticateAccount } from '../../ports/accounts.js';

export function clerkIdentity(secretKey: string | undefined, authorizedParties: string[], publishableKey?: string): AuthenticateAccount {
  const clerk = secretKey && publishableKey ? createClerkClient({ secretKey, publishableKey, telemetry: { disabled: true } }) : null;
  return async (headers) => {
    if (!clerk || !authorizedParties.length) throw new AccountError('AUTH_UNAVAILABLE', 'Account access is temporarily unavailable.');
    const authorization = headers.get('authorization');
    if (!authorization?.startsWith('Bearer ')) throw new AccountError('SIGN_IN_REQUIRED', 'Sign in to continue.');
    let state;
    try {
      state = await clerk.authenticateRequest(new Request(`${authorizedParties[0]}/api/v1/account`, { headers }),
        { authorizedParties, acceptsToken: 'session_token' });
    } catch { throw new AccountError('AUTH_UNAVAILABLE', 'Account access is temporarily unavailable.'); }
    if (!state.isAuthenticated) throw new AccountError('SIGN_IN_REQUIRED', 'Your session has expired. Sign in again.');
    const auth = state.toAuth();
    let user;
    try { user = await clerk.users.getUser(auth.userId); }
    catch { throw new AccountError('AUTH_UNAVAILABLE', 'Account access is temporarily unavailable.'); }
    const email = user.emailAddresses.find((item) => item.id === user.primaryEmailAddressId);
    if (user.banned || user.locked || email?.verification?.status !== 'verified') {
      throw new AccountError('EMAIL_VERIFICATION_REQUIRED', 'Verify your account email to continue.');
    }
    const age = auth.sessionClaims?.fva;
    return { clerkUserId: user.id, email: email.emailAddress,
      recent: Array.isArray(age) && typeof age[0] === 'number' && age[0] >= 0 && age[0] < 5 };
  };
}
