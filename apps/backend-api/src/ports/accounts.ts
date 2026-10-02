import type { Account, Identity, Preferences } from '../domain/accounts.js';

export interface AccountStore {
  failure(identity: Identity | undefined, code: string, requestId: string): Promise<void>;
  read(identity: Identity): Promise<Account | null>;
  profile(identity: Identity, name: string, requestId: string): Promise<Account>;
  save(identity: Identity, preferences: Preferences, requestId: string): Promise<Account>;
  pauseSms(identity: Identity, requestId: string): Promise<Account>;
  bindPhone(identity: Identity, phone: string, requestId: string): Promise<Account>;
  phoneAvailable(phone: string, userId: string): Promise<boolean>;
}
export type AuthenticateAccount = (headers: Headers) => Promise<Identity>;

export interface PhoneProvider {
  supported(phone: string): Promise<boolean>;
  send(phone: string, attemptId: string): Promise<string>;
  proof(attemptId: string, code: string): string;
  verify(phone: string, code: string): Promise<boolean>;
}

export interface PendingPhone { id: string; phone: string; expiresAt: string; resendAt: string }
export interface PhoneAttempts {
  exclusive<T>(userId: string, phone: string, work: () => Promise<T>): Promise<T>;
  start(userId: string, phone: string): Promise<PendingPhone>;
  pending(userId: string): Promise<PendingPhone | null>;
  check(userId: string, attemptId: string): Promise<PendingPhone>;
  arm(userId: string, attemptId: string, proof: string): Promise<void>;
  matches(userId: string, attemptId: string, proof: string): Promise<boolean>;
  wrong(userId: string, attemptId: string): Promise<void>;
  consume(userId: string, attemptId: string): Promise<void>;
  cancel(userId: string): Promise<void>;
}
