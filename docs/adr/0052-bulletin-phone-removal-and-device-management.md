# Enable Bulletin phone removal and signed-in device management

**Status**: accepted by the user on 18 October 2026.

Amends [ADR 0042](0042-bulletin-account-implementation.md) by adding a verified
destination-removal operation and by enabling signed-in device management. It
does not enable email change or account removal, which remain unavailable with
no mutation route. [ADR 0044](0044-bulletin-account-routes.md) and
[ADR 0051](0051-desktop-account-dialog-and-location-route.md) still control the
routes, drafts, desktop Dialog, history and session isolation. Clerk remains the
owner of credentials, email identity, verification and sessions.

## Remove the saved mobile number

`DELETE /api/v1/account/phone` removes the signed-in account's current verified
mobile number and returns the updated account. It requires an active account
and the same fresh Clerk first-factor proof as replacement
(`requireRecent`). The five-minute browser proof reuse, the Backend
first-factor `fva` check and the shared email reverification gate are unchanged
from ADR 0042. Removing a number when none is saved leaves the account unchanged
and writes no success audit.

One transaction clears `mobile_number` and `mobile_verified_at`, sets
`sms_enabled = false`, refreshes `updated_at` and appends one success audit. It
preserves the display name, email mirror, magnitude, nearby-only rule, alert
location, distance and onboarding completion; the account stays onboarded and
its next step remains `complete`. The result satisfies the existing
null-pair and channel `CHECK` constraints. No column, table, constraint, index
or grant is added; the restricted Backend role already updates these columns and
inserts audits.

Removal serializes with the account/phone verification locks. Any pending Redis
attempt is cancelled under the same lock before the row is cleared, so an
in-flight or stale send or verification cannot rebind a removed number; a
verification that already committed a binding is cleared by the removal that
follows it. The `phone_removed` success audit contains no phone number, and the
bounded failure path is unchanged.

Removal is a new operation. The existing `DELETE /api/v1/account/phone/attempts`
still cancels only a pending verification attempt and is not repurposed. Account
closure keeps its existing meaning: it clears the current phone and verification
time and disables both channels, exactly as
[DATABASE-DESIGN.md](../system-design/ERD/DATABASE-DESIGN.md) already records.

## Manage signed-in devices

The devices screen lists the authenticated user's active Clerk sessions through
the Bulletin identity seam (`user.getSessions()`). It marks the current session
by its Clerk session ID, shows only device type, browser and last-active time,
and presents no city, country or IP-derived location and no exact hardware
identity. Loading, unavailable-metadata, provider-failure and empty
other-session states are rendered as such rather than filled with examples.

Viewing devices and signing out the current device require only an active
session. The current device keeps the existing ordinary sign-out with no extra
verification. Revoking one other session and revoking all other sessions both
require the shared email OTP gate and reuse a successful proof for less than
five minutes in the same session. The gate reopens when Clerk rejects a
revocation as stale.

Listing and revocation use the publishable-key Clerk client. Clerk enforces that
a user can revoke only their own sessions and refuses to revoke the active
session. The Bulletin does not treat a browser value as authorization and
discards results that arrive after the user or session changes. No Backend
endpoint, database change, dependency or migration is added, and device actions
create no business audit. A revoked session signs out when its token can no
longer refresh, so propagation is bounded by the session token lifetime rather
than instantaneous.

## Pin the Clerk reverification window to five minutes

Both the development instance and, before release, production set the Clerk
reverification window to 5 minutes (Dashboard **Sessions**, **Session
lifetime**). This matches the Bulletin's five-minute proof reuse and the Backend
first-factor `fva` check, so a proof the product already accepted also satisfies
Clerk's own requirement for protected client actions, including session
revocation. A `session_reverification_required` result clears the local proof
cache and returns the user to the email gate instead of surfacing a provider
error.

## Scope

Automatic alert delivery, email change, account removal and production
deployment remain outside this decision. The separate OTP initial-send
rate-limit gap is not addressed here.

References: [Clerk reverification](https://clerk.com/docs/guides/secure/reverification),
[Clerk session object](https://clerk.com/docs/react/reference/objects/session),
[Clerk user object](https://clerk.com/docs/react/reference/objects/user),
[Clerk Backend API sessions](https://clerk.com/docs/reference/backend-api/tag/sessions).
