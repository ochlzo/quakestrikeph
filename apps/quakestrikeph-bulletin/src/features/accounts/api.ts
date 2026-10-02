import type { components } from '../../lib/api/schema';

export type Account = components['schemas']['Account'];
export type Preferences = components['schemas']['Preferences'];
export type PendingPhone = components['schemas']['PendingPhone'];
export type AccountState = components['schemas']['AccountState'];

export class AccountFailure extends Error {
  constructor(message: string, public code: string, public field?: string) { super(message); }
}

export async function accountRequest<T>(token: string | null, path = '', method = 'GET', body?: unknown): Promise<T> {
  if (!token) throw new AccountFailure('Your session has expired. Sign in again.', 'SIGN_IN_REQUIRED');
  const response = await fetch(`/api/v1/account${path}`, { method, cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  if (!response.ok) {
    const value = await response.json().catch(() => null);
    throw new AccountFailure(value?.error?.message ?? 'Your changes could not be saved. Try again.',
      value?.error?.code ?? 'UNAVAILABLE', value?.error?.field);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
