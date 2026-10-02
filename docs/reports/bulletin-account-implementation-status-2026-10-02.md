# Bulletin account implementation status — 2 October 2026

Implementation is present in managed worktree
`C:\Users\cholo\.codex\worktrees\bulletin-accounts\quakestrikeph`, branch
`codex/bulletin-accounts`. The original checkout is unchanged. Nothing was
pushed or deployed. The documented migration was subsequently applied to the
disposable integration database and a separate local account-development database;
no production database was changed.

## Implemented

- Custom Clerk email/password and Google entry, email verification, Device
  Trust, recovery, required session tasks and recent identity verification.
- Backend-owned profile, onboarding resumption, verified phone binding and
  atomic preference/audit writes. Authentication and ownership are enforced
  server-side. No email-change or removal mutation is exposed.
- IPROG network gate and OTP adapter, Redis account/phone fencing, expiring
  proof, cooldown, wrong-code exhaustion and sliding send limits. Replacement
  pauses SMS and retains the previous binding until new proof commits.
- Approved responsive mockup compositions with shadcn fields, errors, switches
  and toasts. Search, draggable pin, distance circle and optional on-demand
  device location; no coordinate UI. Picker edits remain draft until Save.
- Independent receive choices, including both off. Verification never opts in.
  Automatic earthquake alert delivery remains outside this milestone.

The proposed migration contains only the 21 `users` columns already documented
in `docs/system-design/ERD/DATABASE-DESIGN.md`, plus the documented user audit
foreign key. No undocumented table or column was introduced. Temporary OTP
and rate state is stored in Redis.

## Provider setup

The free Clerk development app and its ignored local settings are configured.
The user's existing Google-linked IPROG account was accessed; its existing API
token was saved with explicit approval in the ignored Backend `.env.local`.
No new IPROG credential or paid purchase was performed. Secret keys are
absent from frontend source, generated bundles and Git changes.

## Verification

| Check | Result |
| --- | --- |
| Backend build and unit suite | Passed: 12 tests, including real Clerk SDK configuration regression |
| Worker unit suite | Passed: 287; 2 Windows symlink skips |
| Worker Ruff lint and formatting | Passed |
| Bulletin API generation, Astro check and build | Passed; 0 errors/warnings, 9 hints; large map bundle notice remains |
| Isolated browser fixtures | Passed desktop/mobile entry, verification, preference drafts, failures, static deferred screens, reverification, password and phone replacement transitions |
| Fresh full visual review | `ship` for the 12 desktop/mobile captures and fixture scope |
| Git whitespace | Passed |
| Required worker integration suite | Passed: 211; 2 skipped because ignored SEIS model bundle unavailable |
| Backend PostgreSQL/Redis integration suite | Passed: 3; no skips |
| Live IPROG adapter | Passed supported-network gate, one approved OTP send, HMAC attempt binding and provider verification; handset receipt confirmed by the user |
| Live Clerk Google and local persistence | Passed Google callback, verified email identity, profile save, onboarding completion and preference persistence after reopening; password/recovery/reverification remain unverified live |
| Full phone UI flow | Passed second approved send, handset code verification, Redis attempt proof and durable verified phone binding; reload restored binding with SMS off |
| Live account management | Passed name edit/save/reload and restoration; email change and removal remained static unavailable screens |

Earlier, all three required Compose commands under CONTRIBUTING.md were attempted for
`quakestrike-data-ingestion-test`; each timed out waiting for Docker. The
initial engine error reported the missing `dockerDesktopLinuxEngine` named
pipe; launching Docker Desktop did not restore a responsive engine. No host
pytest skips were presented as integration success and no development database
was substituted. Retry the documented disposable suite once Docker responds.
On the follow-up check, `com.docker.service` was stopped. Starting it failed
with `Cannot open 'com.docker.service' service on computer '.'`; this session
lacks service-control permission. The engine information command remained
unresponsive. Start Docker Desktop with administrator permission before retrying.

The user then started Docker; its engine responded with version 29.5.2. The
required suite ran successfully, followed by Backend tests using the provisioned
restricted role. PostgreSQL found a UUID/text parameter conflict in the success
audit insert; explicit UUID casts fixed it, and all three Backend integration
tests then passed. The final documented `down -v` removed the disposable project.
The mounted role-provisioning shell file was also normalized to Linux line endings.

For live browser checks, a separate ignored Compose runtime was created under
`.impeccable/runtime/accounts/`, project `quakestrike-bulletin-accounts-dev`,
database `quakestrike_accounts_dev`. It uses a separate durable volume, the
documented migrations, restricted Backend grants and private PostgreSQL/Redis.
Only the Backend port is published, at `127.0.0.1:3000`; the Bulletin is at
`http://127.0.0.1:4321`. Provider credentials remain server-only. A labelled
`account-ui-fixture` model metadata row satisfies the existing startup check;
it is not a real prediction model, and no prediction worker runs in this runtime.
Public Bulletin reads retain their existing target. Unauthenticated account
access was checked and returned HTTP 401.

The live Google flow exposed a missing Backend publishable-key setting. Clerk
Backend resources can use the secret key alone, but `authenticateRequest()`
requires the publishable key for session tokens. A regression test reproduced
the unavailable response before the fix and passed afterward. The Backend
factory, runtime wiring, Compose configuration and environment example now
include `CLERK_PUBLISHABLE_KEY`. Temporary diagnostics were removed. The real
authenticated account read and profile/preference writes then returned 200.
Reopening settings restored M5.6, the public named test location Legaspi in
Albay, nearby-only filtering and a 75 km distance. A database aggregate confirmed
one completed account with both email and SMS off. This location is a test
choice, not an observation of the user's device location.

The second approved OTP completed the real UI–Backend–Redis–IPROG flow.
Verification returned 200, and a database aggregate confirmed a verified phone
binding with both channels still off. Reloading settings restored the binding.
Existing-account preference updates stayed on settings; the test magnitude was
restored to M5.6. A profile edit survived reload and was restored to the original
name. Both deferred account actions showed their static unavailable screens.

The fresh documenter completed the interface report before the final functional
phone recovery adjustment. Its follow-up recheck hit the account usage limit;
the primary agent checked that the report's stated interface/fixture scope
remained accurate after regenerated passing captures. Global design documents
were preserved. See `bulletin-account-ui-review-2026-10-02.md`.

## Remaining gates

### Subsequent password signup check and user policy revision

The user's live email/password signup reached Clerk but returned
`form_password_pwned`. A generic fallback hid the reason. Password-field error
handling now explains that provider rejection, with an accessible invalid state;
temporary code-only diagnostics were removed. The user subsequently requested
minimum 8 characters, one lowercase letter, one uppercase letter and one number,
with compromised-password checks disabled. Matching Clerk development settings
were saved after explicit action-time confirmation; no paid plan was activated.
Signup, recovery and password creation/change inputs now mirror the rule.

The isolated signup regression passed: missing requirements are invalid, a
provider rejection appears beside the password, and a compliant eight-character
password advances to email verification. Astro check passed with 0 errors,
0 warnings and 9 hints; the build passed with its existing map-size notice.
The broader fixture rerun timed out waiting for map readiness; that rerun is
not counted as a pass. Live password signup with the revised policy remains
pending the user's credential entry and submission.

1. Exercise live Clerk password signup/recovery and recent reverification.
   Google sign-in, phone verification and durable local account writes passed.
   Password creation or changes require user entry and submission.
2. Both of the maximum two approved OTP sends have been used successfully. No
   further send is authorized. Provider proof remains transient; raw codes are
   not logged or persisted.

The Google/account/preferences/phone path is verified end to end in this local
development runtime. Password and recovery paths have fixture coverage but
remain unverified against live Clerk. This is not a production release.

### Accepted password enforcement — 3 October 2026

The user accepted UI-only enforcement of the eight-character, lowercase,
uppercase and digit requirements, replacing the earlier requirement for custom
server enforcement on the free plan. Signup, recovery, required password-reset
session tasks and password addition/change use the product's browser validation.
Direct Clerk requests can bypass those composition checks; this is an accepted
limitation. Clerk owns credentials and applies its own server-side rules.
Existing-password sign-in and reverification remain unrestricted by the
new-password composition rule.

The codebase has no experimental password middleware, alternate authentication
route or dedicated deployment configuration. The external experiment was
removed from the VPS and original Clerk/Traefik settings restored; homepage/API
checks passed. All experimental local source, scripts, images, credentials and
artifacts have also been removed. Backend account authentication, ownership,
verified-email checks and recent-proof requirements remain in place.

The isolated signup and password browser checks pass without provider requests.
They cover missing composition requirements, eight-character passwords without
special characters, mismatched confirmation, password visibility, recovery,
addition/change, required resets, provider-failure retry and existing-password
inputs. Bulletin `pnpm check` reports 0 errors, 0 warnings and 9 existing hints;
`pnpm build` passes with the existing bundle-size notice. Backend typechecking
and Git whitespace checks pass. No database/Redis behavior changed in this
follow-up, so its verification did not require another integration-suite run.
