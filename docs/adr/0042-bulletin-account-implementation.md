# Implement Bulletin accounts and saved preferences without automatic delivery

**Status**: accepted by the user on 2 October 2026.

Implements ADRs 0036–0038 within the approved mockup compositions. Public
reading remains anonymous. Clerk owns password/Google sign-in, email proof,
recovery, device trust and recent identity verification. The Bulletin uses
the publishable-key-only React client; its container receives no provider,
database or Redis secret. The Backend validates session tokens and authorized
origins, fetches the current primary verified Clerk email, and derives ownership
from the stable Clerk user ID. A stale email mirror fails closed. Email changes
and account removal remain explicitly unavailable, with no mutation routes.

Amends ADR 0037's provider-setting interpretation: the normal product sign-in
form offers only password and Google. Clerk's email-code capability remains
enabled because Google-only reverification and Device Trust need it; this
capability also technically permits primary code sign-in at the provider.
Do not claim that Clerk disables primary email-code authentication.

On 2 October 2026 the user replaced the initial 15-character password policy:
new passwords require at least 8 characters, one lowercase letter, one uppercase
letter and one number. No special character is required. Compromised-password
rejection and the additional strength estimator are disabled. The Bulletin
validates these rules on signup, recovery and password creation/change, while
Clerk remains the authoritative credential owner. On 3 October 2026 the user
accepted UI-only enforcement of these composition rules, replacing the earlier
requirement for custom server enforcement on the free plan. Direct Clerk API
requests can bypass the product's browser checks; that limitation is accepted.
Clerk applies its own server-side credential rules. Custom paid password
requirements and Backend password middleware are not required. The same form
validation covers required password-reset session tasks. Email proof, recovery
codes and recent identity verification remain Clerk-owned requirements.
Existing-password sign-in fields do not apply new-password composition rules.

Create only the documented `users` columns and the documented audit FK.
No undocumented database table or column may be added without pausing for
the user. Profile/preference/phone mutations and their success audits commit
atomically. Backend grants permit account reads and specific account writes
and append-only audits, while public information retains its existing reads.
The Backend cannot modify account status or unrelated worker data.

Preferences independently default email and SMS off. Provisional channel
selection and phone verification never opt in. Final Save completes onboarding
even with both channels off. Magnitude is M1.0–M10.0 at 0.1 steps, default M4.5.
Nearby-only defaults off; the UI uses a 50 km draft distance and accepts whole
kilometres from 1 to 1,000. Location selection uses local attributed GeoNames
search, an adjustable MapLibre pin and optional on-demand device location.
Coordinates are internal data, with no coordinate fields or readouts. Selecting
a location changes the draft; Save commits all preferences together.

IPROG ordinary shared-sender coverage is checked before OTP and SMS enablement.
Only known Globe/TM and DITO support qualifies. Redis holds one current
account/phone-bound attempt, with five-minute expiry, 60-second resend cooldown,
five wrong entries, and rolling limits of three sends/hour and ten/day per
account and phone. Distributed account/phone locks serialize provider calls.
Fresh Clerk first-factor proof within five minutes is required for replacement.
Starting replacement pauses SMS but retains the old verified binding. Binding
the new number still requires a later explicit SMS opt-in.

IPROG verifies by phone rather than by an opaque attempt ID. Bind its returned
code to the current attempt using HMAC-SHA256 with a random process-local key;
only the digest is stored briefly in Redis. Before calling provider verification,
the Backend checks both attempt ownership and that digest. Raw codes, full OTP
responses and the HMAC key are never persisted or exposed. Backend restart
invalidates previous digests; the user requests a new attempt. Consume the
attempt before durable binding; database failure needs a new proof.

This release saves settings and verifies destinations. Automatic earthquake
email/SMS delivery, Brevo setup, alert-worker changes and production deployment
remain outside scope. The interface states that delivery is not yet available.
Missing provider configuration never produces a verified destination.

References: [Clerk reverification](https://clerk.com/docs/guides/secure/reverification),
[Clerk Device Trust](https://clerk.com/docs/guides/secure/device-trust),
[IPROG OTP/network API](https://www.iprogsms.com/api/v1/documentation),
[GeoNames data and license](https://download.geonames.org/export/dump/readme.txt).
