export class AccountError extends Error {
  constructor(public code: string, message: string, public status = 400, public field?: string) {
    super(message);
  }
}

export interface SmsDiagnostic {
  provider: 'iprog';
  operation: 'detect' | 'send_otp' | 'verify_otp';
  category: 'rate_limit' | 'credential_or_credit' | 'credentials' | 'credits' | 'configuration' | 'malformed_response' | 'transport_uncertain' | 'provider_failure' | 'http_failure';
  failureSource: 'http' | 'body' | 'transport' | 'configuration';
  providerCode: number | null;
  httpStatus: number | null;
  retryAfterSeconds: number | null;
}

export class SmsProviderError extends AccountError {
  constructor(public diagnostic: SmsDiagnostic) {
    super('SMS_UNAVAILABLE', 'The SMS service is unavailable. Please try again later.', 503);
  }
}

export interface Identity {
  clerkUserId: string;
  email: string;
  recent: boolean;
}

export interface Preferences {
  emailEnabled: boolean;
  smsEnabled: boolean;
  magnitude: number;
  nearbyOnly: boolean;
  latitude: number | null;
  longitude: number | null;
  distanceKm: number | null;
}

export interface Account extends Preferences {
  userId: string;
  displayName: string;
  email: string;
  phone: string | null;
  onboardingCompleted: boolean;
  status: 'active' | 'suspended' | 'closed';
}

export function requireActive(account: Account) {
  if (account.status !== 'active') throw new AccountError('ACCOUNT_UNAVAILABLE', 'This account is unavailable.', 403);
}

export function requireRecent(identity: Identity) {
  if (!identity.recent) throw new AccountError('REVERIFICATION_REQUIRED', 'Verify your identity again to continue.', 403);
}

export function displayName(value: unknown): string {
  if (typeof value !== 'string' || !value.trim() || value.trim().length > 100) {
    throw new AccountError('INVALID_NAME', 'Enter a name of 1–100 characters.', 400, 'displayName');
  }
  return value.trim();
}

export function normalizePhone(value: unknown): string {
  const cleaned = typeof value === 'string' ? value.replace(/[\s()-]/g, '') : '';
  const normalized = cleaned.startsWith('09') ? `+63${cleaned.slice(1)}` :
    cleaned.startsWith('639') ? `+${cleaned}` : cleaned;
  if (!/^\+639\d{9}$/.test(normalized)) {
    throw new AccountError('INVALID_PHONE', 'Enter a Philippine mobile number, such as 0917 123 4567.', 400, 'phone');
  }
  return normalized;
}

export function preferences(value: unknown): Preferences {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AccountError('INVALID_REQUEST', 'Enter your preferences.');
  const v = value as Record<string, unknown>;
  for (const name of ['emailEnabled', 'smsEnabled', 'nearbyOnly']) {
    if (typeof v[name] !== 'boolean') throw new AccountError('INVALID_PREFERENCES', 'Choose each receive option.', 400, name);
  }
  if (typeof v.magnitude !== 'number' || !Number.isFinite(v.magnitude) || v.magnitude < 1 || v.magnitude > 10 ||
      Math.abs(v.magnitude * 10 - Math.round(v.magnitude * 10)) > 1e-7) {
    throw new AccountError('INVALID_MAGNITUDE', 'Choose M1.0–M10.0, in steps of 0.1.', 400, 'magnitude');
  }
  const numeric = (name: string, min: number, max: number): number | null => {
    const x = v[name];
    if (x === null) return null;
    if (typeof x !== 'number' || !Number.isFinite(x) || x < min || x > max) {
      throw new AccountError('INVALID_LOCATION', 'Choose a location and a distance of 1–1,000 km.', 400, name);
    }
    return x;
  };
  const latitude = numeric('latitude', -90, 90);
  const longitude = numeric('longitude', -180, 180);
  const distanceKm = numeric('distanceKm', 1, 1000);
  if ((latitude === null) !== (longitude === null) ||
      (distanceKm !== null && !Number.isInteger(distanceKm)) ||
      (v.nearbyOnly && (latitude === null || distanceKm === null))) {
    throw new AccountError('INVALID_LOCATION', 'Choose a location and a whole-kilometre distance first.', 400, 'location');
  }
  return { emailEnabled: v.emailEnabled as boolean, smsEnabled: v.smsEnabled as boolean,
    nearbyOnly: v.nearbyOnly as boolean, magnitude: v.magnitude, latitude, longitude, distanceKm };
}
