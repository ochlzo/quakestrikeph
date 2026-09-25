# Use Google accounts and independent phone verification for SMS alerts

**Status**: accepted

The Bulletin remains available anonymously for public earthquake information.
An account is needed only for personal alert settings. Clerk authenticates
those accounts through Google OAuth only. Phone/password, phone-code, email
password, and email-code sign-in are outside this design. Clerk's stable user
ID identifies the `users` row; its Google email is contact/profile data, not
a separate QuakeStrike login key. A Google account may exist without a phone
and receives no SMS alerts until it completes phone verification and opts in.
Operators use the separate Cloudflare Access identity in [ADR 0035](0035-cloudflare-access-operations-console.md).

The Backend owns the current alert phone, verification status, and consent in
PostgreSQL. A signed-in user starts a phone-verification attempt; short-lived
Redis state with expiry binds the Clerk user ID and normalized proposed number.
Allow only one active pending attempt per proposed phone; a provider must
invalidate older codes when a new attempt begins. Losing pending state requires
a new attempt and never verifies a phone by default. A selected SMS
verification provider sends and checks a short-lived,
single-use code. The Backend accepts a provider-confirmed result only for the
same pending user and number, applies rate limits, and atomically records the
verified current phone with its timestamp. It never treats an SMS delivery
acceptance or a delayed webhook as proof of verification. The provider's code
and complete responses must never reach browser state, ordinary logs, audit
metadata, or the Operations Console. Pending attempts expire and are not
durable account or alert history. Failed or unavailable verification does not
bind the proposed phone. A first-time enrollee remains unable to opt into
alerts; an existing account keeps its old phone and settings until a verified
replacement commits.

Each account has at most one current phone, and a normalized current phone
belongs to at most one account. A second account cannot claim a bound phone;
there is no automatic account merge or transfer of alert history based on
phone possession. A phone change requires a recent interactive Google login,
verification of the replacement number, and an atomic replacement that
disables SMS alerts. The user must explicitly opt in again. Closing an account
disables alerts and clears its active phone binding so a future owner of the
number can enroll, while retained audit and delivery evidence follows its
separate retention rules. Lost Google access is handled through the account
provider and a separately controlled support procedure, never a read-only
Console action or proof of phone possession alone.

Phone verification alone never enables alerts. The existing `sms_enabled`
setting remains a separate, audited user action as specified by
[ADR 0030](0030-optional-nearby-sms-alerts.md). The Alert Worker continues to
recheck an active account, the current verified phone, `sms_enabled`, and
other eligibility before each provider call. The SMS provider is not the
identity provider; it proves possession of an alert destination for a
particular attempt.

IPROG SMS is the leading candidate for both provider-managed OTP verification
and alert delivery, not an approved production dependency yet. Before
selection, verify code expiry, one-time use, attempt limits, Philippine network
coverage including Smart/TNT, sender approval and fallback behavior, delivery
status and reconciliation, API credential handling, and cost. IPROG's
documented OTP send response includes the code, so the integration must strip
it from all client and diagnostic paths. If IPROG cannot meet these gates,
select another provider with the same verification and delivery contract.
The production provider, sender identity, callback verification, and budgets
remain deployment decisions. Clerk SMS authentication and its production
phone-authentication fee are not part of this Google-only design.

References: [IPROG SMS API](https://www.iprogsms.com/api/v1/documentation),
[IPROG network notice](https://www.iprogsms.com/announcements),
[Clerk pricing](https://clerk.com/pricing).
