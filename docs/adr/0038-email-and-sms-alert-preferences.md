# Offer independent email and SMS alert channels

**Status**: accepted

This decision extends [ADR 0027](0027-automatic-alerts-without-forecast-review.md)
beyond SMS and applies [ADR 0030's](0030-optional-nearby-sms-alerts.md) magnitude
and nearby-only rules to both channels. One current, unexpired live M1+
forecast still creates one automatic alert job; historical, backfill, and
expired work create none. The Alert Worker resolves at most one email and one
SMS recipient for each eligible user. Each channel has its own destination,
provider attempts, status, idempotency, and reconciliation. The observed
anchor magnitude threshold and optional observed-epicenter distance rule are
shared. Brevo sends transactional alert email; Clerk sends authentication email.

After account sign-up, show independent provisional SMS and email checkboxes to
route the user. SMS appears first and is selected by default. A separated
"Neither for now" choice clears both selections. These choices do not enable
alerts. Email alone proceeds to the final alert-preferences screen. SMS or both first
checks whether the current IPROG shared sender can carry ordinary alerts to
the proposed network. An unsupported or unknown result stops before OTP and
offers email or no alerts. A supported number proceeds to IPROG provider-managed
OTP verification, then the final preferences screen. That screen always shows
both receive options, the shared magnitude threshold, and the optional
nearby-only rule. The final save is the explicit opt-in; verification alone
never enables a channel. Both channels may be off. An interrupted flow resumes
at the first unfinished step; an expired SMS attempt starts over.

The verified email comes from Clerk. The verified SMS destination comes from
the Backend's IPROG proof bound to the signed-in Clerk user and pending phone,
as in ADR 0036. The Backend owns both channel settings and their audit evidence
in PostgreSQL. It refuses email enablement without a current verified email and
SMS enablement without a current verified, supported phone. A requested email
change pauses email delivery until the replacement is verified and recorded;
the existing email preference then resumes. Starting a phone change
pauses SMS immediately; successful replacement still needs a new explicit SMS
opt-in. The other channel can remain enabled. Closing or suspending an account
prevents delivery on both.

IPROG SMS is selected for phone OTP and SMS alert delivery using the existing
account and shared sender identity. Its OTP route and ordinary alert sender
have different network coverage. IPROG currently reports that ordinary alerts
using the shared sender do not reach Smart/TNT; a successful OTP must never be
taken as evidence of ordinary alert deliverability. The Backend checks the
provider's network result before starting SMS verification or enabling SMS.
The Alert Worker rechecks sender support and all current eligibility before
each send, fails closed on unknown support, and records provider rejection or
uncertain delivery honestly. It never enables email as a silent fallback;
email is sent only when that user opted in. Provider credentials, the
IPROG-returned OTP code, and complete OTP responses stay out of clients, logs,
audits, and the Console. A code typed by the user is used only to check the
pending attempt and is never retained in logs or durable records.

Brevo's Transactional Email API is selected for alert email. The Alert Worker
sends one message for each eligible email recipient and records Brevo's
returned message ID on the delivery attempt. A successful API response means
Brevo accepted the request, not that the message reached an inbox. Reconcile
delivery, bounce, blocked, and error events through authenticated,
idempotent transactional webhooks; uncertain calls remain unknown until
resolved. Authenticate the sending domain and configure an approved sender
before production delivery. Keep Brevo credentials server-side and out of
Clerk, browser code, logs, and audits. Email remains an independent opt-in;
Brevo is not used to verify the account email or sign users in.

Use the [database contract](../system-design/ERD/DATABASE-DESIGN.md) for exact
columns, uniqueness, snapshots, and transactions. Production delivery still needs tested sender coverage,
provider security, callback or polling reconciliation, rate and cost controls
for both providers.

References: [IPROG API and network detection](https://www.iprogsms.com/api/v1/documentation)
and [IPROG shared-sender notice](https://www.iprogsms.com/announcements);
[Brevo transactional email API](https://developers.brevo.com/reference/send-transac-email),
[transactional webhooks](https://developers.brevo.com/docs/transactional-webhooks),
and [sender-domain authentication](https://help.brevo.com/hc/en-us/articles/12163873383186-Authenticate-your-domain-with-Brevo-Brevo-code-DKIM-DMARC).
