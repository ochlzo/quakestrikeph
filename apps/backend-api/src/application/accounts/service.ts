import {
  AccountError,
  displayName,
  normalizePhone,
  preferences,
  requireActive,
  requireRecent,
  type Identity,
} from "../../domain/accounts.js";
import type {
  AccountStore,
  PhoneAttempts,
  PhoneProvider,
} from "../../ports/accounts.js";

export class AccountService {
  constructor(
    private store: AccountStore,
    private attempts: PhoneAttempts,
    private provider: PhoneProvider,
  ) {}
  async failure(
    identity: Identity | undefined,
    code: string,
    requestId: string,
  ) {
    try {
      await this.store.failure(identity, code, requestId);
    } catch {
      /* A failed audit never turns a denial into success. */
    }
  }

  async read(identity: Identity) {
    const account = await this.store.read(identity);
    let pending = null;
    if (account) {
      try {
        pending = await this.attempts.pending(identity.clerkUserId);
      } catch (error) {
        if (
          !(error instanceof AccountError) ||
          error.code !== "VERIFICATION_UNAVAILABLE"
        )
          throw error;
      }
    }
    return {
      account,
      pending,
      nextStep: !account?.displayName?.trim()
        ? "profile"
        : account.onboardingCompleted
          ? "complete"
          : pending
            ? "verify-phone"
            : account.phone
              ? "preferences"
              : "channels",
      deliveryAvailable: false,
    };
  }
  profile(
    identity: Identity,
    body: Record<string, unknown>,
    requestId: string,
  ) {
    return this.store.profile(
      identity,
      displayName(body.displayName),
      requestId,
    );
  }
  private async current(identity: Identity) {
    const account = await this.store.read(identity);
    if (!account)
      throw new AccountError(
        "PROFILE_REQUIRED",
        "Complete your profile first.",
      );
    requireActive(account);
    return account;
  }
  async save(identity: Identity, body: unknown, requestId: string) {
    const p = preferences(body);
    const account = await this.current(identity);
    if (
      p.smsEnabled &&
      (!account.phone || !(await this.provider.supported(account.phone)))
    ) {
      throw new AccountError(
        "SMS_UNSUPPORTED",
        "Verify a mobile number supported by our SMS sender first.",
        "smsEnabled",
      );
    }
    return this.store.save(identity, p, requestId);
  }
  async start(
    identity: Identity,
    body: Record<string, unknown>,
    requestId: string,
  ) {
    const account = await this.current(identity);
    const phone = normalizePhone(body.phone);
    if (account.phone) requireRecent(identity);
    return this.attempts.exclusive(identity.clerkUserId, phone, async () => {
      // Pause before starting any replacement attempt, including provider failure.
      if (account.phone) await this.store.pauseSms(identity, requestId);
      if (!(await this.store.phoneAvailable(phone, account.userId))) {
        throw new AccountError(
          "PHONE_UNAVAILABLE",
          "This mobile number cannot be added to this account.",
          "phone",
        );
      }
      if (!(await this.provider.supported(phone))) {
        throw new AccountError(
          "SMS_UNSUPPORTED",
          "Our SMS sender currently supports only Globe/TM and DITO. Choose email or another number.",
          "phone",
        );
      }
      const pending = await this.attempts.start(identity.clerkUserId, phone);
      try {
        await this.attempts.arm(
          identity.clerkUserId,
          pending.id,
          await this.provider.send(phone, pending.id),
        );
      } catch (error) {
        await this.attempts.consume(identity.clerkUserId, pending.id);
        throw error;
      }
      return pending;
    });
  }
  async verify(
    identity: Identity,
    body: Record<string, unknown>,
    requestId: string,
  ) {
    const account = await this.current(identity);
    if (account.phone) requireRecent(identity);
    if (
      typeof body.attemptId !== "string" ||
      typeof body.code !== "string" ||
      !/^\d{6}$/.test(body.code)
    ) {
      throw new AccountError(
        "INVALID_CODE",
        "Enter the six-digit code.",
        "code",
      );
    }
    const attemptId = body.attemptId;
    const code = body.code;
    const pending = await this.attempts.check(identity.clerkUserId, attemptId);
    return this.attempts.exclusive(
      identity.clerkUserId,
      pending.phone,
      async () => {
        await this.attempts.check(identity.clerkUserId, attemptId);
        if (
          !(await this.attempts.matches(
            identity.clerkUserId,
            attemptId,
            this.provider.proof(attemptId, code),
          )) ||
          !(await this.provider.verify(pending.phone, code))
        ) {
          await this.attempts.wrong(identity.clerkUserId, attemptId);
          throw new AccountError(
            "INVALID_CODE",
            "That code did not work. Try again or request a new code.",
            "code",
          );
        }
        // Consume before durable binding. Database failure requires a new proof.
        await this.attempts.consume(identity.clerkUserId, attemptId);
        return this.store.bindPhone(identity, pending.phone, requestId);
      },
    );
  }
  async cancel(identity: Identity) {
    await this.current(identity);
    const pending = await this.attempts.pending(identity.clerkUserId);
    if (pending)
      await this.attempts.exclusive(identity.clerkUserId, pending.phone, () =>
        this.attempts.cancel(identity.clerkUserId),
      );
  }
  async removePhone(identity: Identity, requestId: string) {
    await this.current(identity);
    requireRecent(identity);
    // Always lock the account: verification may bind a phone after the initial read.
    return this.attempts.exclusive(identity.clerkUserId, null, async () => {
      const account = await this.current(identity);
      await this.attempts.cancel(identity.clerkUserId);
      return account.phone ? this.store.removePhone(identity, requestId) : account;
    });
  }
}
