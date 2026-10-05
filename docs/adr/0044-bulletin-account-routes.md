# Separate Bulletin account destinations and preserve settings drafts

**Status**: accepted by the user on 5 October 2026.

The Bulletin exposes these account destinations through Astro pages:

| Route | Responsibility |
| --- | --- |
| `/sign-in` | Password/Google sign-in and device verification. |
| `/sign-up` | Account creation and email verification. |
| `/forgot-password` | Recovery code and password reset. |
| `/sso-callback` | Clerk OAuth callback. |
| `/onboarding` | Resume the first incomplete profile or alert setup step. |
| `/alerts` | Alert preferences. |
| `/alerts/location` | Draft alert location and distance. |
| `/account` | Profile, destinations, sign-out, and unavailable account actions. |
| `/account/password` | Reverification and password creation/change. |
| `/account/phone` | Mobile-number enrollment/replacement and SMS verification. |

`/auth?mode=sign-in` and `/auth?mode=sign-up` remain compatibility redirects to
the canonical authentication routes. Successful authentication opens `/alerts`
for completed accounts. Unfinished accounts resume `/onboarding`; completion
opens `/alerts`. This replaces the earlier return to the public Bulletin after
authentication or the final onboarding save.

Signed-out visits to protected destinations replace the route with `/sign-in`.
Unknown authentication shows the destination's loading skeleton: `/sign-in`
shows authentication loading, and `/alerts` shows alert-settings loading.
Saved preferences are not shown until Clerk confirms a signed-in session.
Backend session verification
and ownership checks remain authoritative; browser routing is a UX safeguard.

The account React island retains the shared workflow and draft while local
navigation updates the URL with the History API. Browser Back/Forward restores
the destination. Preferences/location navigation preserves the draft without
an account request. Leaving a dirty draft for another screen requires the
existing discard confirmation. Refresh loads saved data; drafts, passwords,
codes, and account data are not serialized into history or browser storage.
Signing out or switching identities discards private React state and ignores
responses belonging to the former session.

Verification codes and recent-identity checks remain steps in their parent
flow. Refresh starts authentication/recovery at its safe entry screen; the
Backend can resume a pending phone attempt. Direct password or verified-phone
replacement visits require Clerk reverification. Session tasks still take
precedence over account screens. No new router dependency or Backend endpoint
is required. The controller, shared layout, and route-specific screen modules
remain private implementation details of the account feature.

This decision changes browser navigation only. ADRs 0036–0038 and 0042 still
control identity, verification, preference ownership, and delivery behavior.
