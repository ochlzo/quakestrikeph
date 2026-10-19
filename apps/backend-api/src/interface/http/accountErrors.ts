import type { AccountError } from '../../domain/accounts.js';

export function accountErrorStatus(error: AccountError): number {
  switch (error.code) {
    case 'SIGN_IN_REQUIRED':
      return 401;
    case 'ACCOUNT_UNAVAILABLE':
    case 'REVERIFICATION_REQUIRED':
    case 'EMAIL_VERIFICATION_REQUIRED':
      return 403;
    case 'EMAIL_MIRROR_MISMATCH':
    case 'PHONE_UNAVAILABLE':
    case 'PROFILE_REQUIRED':
    case 'ATTEMPT_EXPIRED':
    case 'VERIFICATION_BUSY':
      return 409;
    case 'SEND_LIMIT':
      return 429;
    case 'AUTH_UNAVAILABLE':
    case 'SMS_UNAVAILABLE':
    case 'VERIFICATION_UNAVAILABLE':
      return 503;
    default:
      return 400;
  }
}
