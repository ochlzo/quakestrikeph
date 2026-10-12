import type { Account, AccountState, PendingPhone } from './api';
import type { PreferenceSaves } from './preference-saves';

type Outcome<T = void> = { kind: 'completed'; value: T } | { kind: 'ignored' };
type EnrollmentEvent = { kind: 'pending'; pending: PendingPhone | null } |
  { kind: 'verified' } | { kind: 'enabled' };
type EnrollmentDependencies = {
  request: <T>(path?: string, method?: string, body?: unknown) => Promise<T>;
  read: () => { account: Account | null; saves: PreferenceSaves | null };
  reconcile: (account: Account | null) => PreferenceSaves | null;
  isCurrent: () => boolean;
  emit: (event: EnrollmentEvent) => void;
};

// Preserve the Backend failure for the account's authorization and field handling.
export class SmsOptInFailure extends Error {
  readonly failure: unknown;
  constructor(failure: unknown) {
    super('SMS alerts could not be enabled.');
    this.failure = failure;
  }
}

export class SmsEnrollment {
  private pending: PendingPhone | null = null;
  private onboardingSms = false;
  private disposed = false;
  private dependencies: EnrollmentDependencies;

  constructor(dependencies: EnrollmentDependencies) { this.dependencies = dependencies; }
  private current() { return !this.disposed && this.dependencies.isCurrent(); }
  private setPending(pending: PendingPhone | null) {
    if (!this.current()) return;
    this.pending = pending;
    this.dependencies.emit({ kind: 'pending', pending });
  }
  view(now: number) {
    return {
      pending: this.pending,
      expired: !!this.pending && Date.parse(this.pending.expiresAt) <= now,
      cooldown: Math.max(0, Math.ceil((Date.parse(this.pending?.resendAt ?? '') - now) / 1000)) || 0,
    };
  }
  resume(pending: PendingPhone | null) { this.setPending(pending); }
  dispose() { this.disposed = true; this.pending = null; this.onboardingSms = false; }

  private async operation<T>(work: () => Promise<T>): Promise<Outcome<T>> {
    if (!this.current()) return { kind: 'ignored' };
    try {
      const value = await work();
      return this.current() ? { kind: 'completed', value } : { kind: 'ignored' };
    } catch (failure) {
      if (!this.current()) return { kind: 'ignored' };
      if (failure instanceof Error && 'code' in failure && failure.code === 'ATTEMPT_EXPIRED')
        this.setPending(null);
      throw failure;
    }
  }

  confirmChannels(selected: { email: boolean; sms: boolean }) {
    const { account, saves } = this.dependencies.read();
    if (!account || !saves) return Promise.resolve<Outcome<boolean>>({ kind: 'ignored' });
    return this.operation(async () => {
      const phoneVerified = !!account.phone && account.phoneVerified !== false;
      const next = await saves.saveConfirmed({
        emailEnabled: selected.email && !!account.email && account.emailVerified !== false,
        smsEnabled: selected.sms && phoneVerified,
      });
      if (!this.current()) return false;
      this.dependencies.reconcile(next);
      this.onboardingSms = selected.sms && !phoneVerified;
      return this.onboardingSms;
    });
  }

  private async requestPhone(phone: string) {
    const replacement = !!this.dependencies.read().account?.phone;
    try { return await this.dependencies.request<PendingPhone>('/phone/attempts', 'POST', { phone }); }
    finally {
      // Replacement may pause SMS before a failed send. Do not hydrate attempts from this read.
      if (replacement && this.current()) {
        try {
          const state = await this.dependencies.request<AccountState>();
          if (this.current() && state.account) this.dependencies.reconcile(state.account);
        } catch {
          if (this.current()) this.dependencies.reconcile(null);
        }
      }
    }
  }
  send(phone: string) {
    return this.operation(async () => {
      const pending = await this.requestPhone(phone);
      this.setPending(pending);
      return pending;
    });
  }
  resend(fallbackPhone: string) { return this.send(this.pending?.phone ?? fallbackPhone); }
  verify(code: string, now = Date.now()) {
    if (!this.pending || this.view(now).expired) return Promise.resolve<Outcome>({ kind: 'ignored' });
    return this.operation(async () => {
      const next = await this.dependencies.request<Account>('/phone/verify', 'POST', { attemptId: this.pending!.id, code });
      if (!this.current()) return;
      this.setPending(null);
      const queue = this.dependencies.reconcile(next)!;
      this.dependencies.emit({ kind: 'verified' });
      if (!this.onboardingSms || !this.current()) return;
      try {
        const enabled = await queue.saveConfirmed({ smsEnabled: true });
        if (!this.current()) return;
        this.dependencies.reconcile(enabled);
        this.onboardingSms = false;
        if (enabled.smsEnabled && queue.snapshot.preferences.smsEnabled)
          this.dependencies.emit({ kind: 'enabled' });
      } catch (failure) { throw new SmsOptInFailure(failure); }
    });
  }
  changeNumber() { return this.cancel(false); }
  skip() { return this.cancel(true); }
  private cancel(skip: boolean) {
    return this.operation(async () => {
      if (!skip || this.pending) await this.dependencies.request('/phone/attempts', 'DELETE');
      if (!this.current()) return;
      if (skip) this.onboardingSms = false;
      this.setPending(null);
    });
  }
}
