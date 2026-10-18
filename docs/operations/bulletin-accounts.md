# Develop and check Bulletin accounts

Use this guide for local account configuration, automated checks, and account behavior reference.
Use [local runtime](local-runtime.md#daily-bulletin-commands) for daily startup and [CI/deployment](continuous-deployment.md) for production releases.

| Task | Section |
| --- | --- |
| Configure local services | [Local configuration](#local-configuration) |
| Run unit, integration, or browser checks | [Automated checks](#automated-checks) |
| Verify live providers before release | [Provider gates](#provider-and-release-gates) |
| Check verification, phone, and device behavior | [Account behavior reference](#account-behavior-reference) |
| Find the retired isolated runtime | [Former runtime](#former-isolated-account-runtime) |

## Local configuration

Accounts use the shared local `infrastructure` Compose project and root `.env`.
Follow [the local web setup](local-runtime.md#9-add-the-local-backend-and-bulletin).
The Bulletin and Backend share the worker database and Redis service.
Provider secrets reach only the Backend. The Bulletin receives the publishable key.
Apply migrations and restricted Backend grants before starting account routes.
Do not include `compose.edge.yml` during local development.

## Automated checks

Run these commands from the repository root after installing locked dependencies:

```powershell
npm --prefix apps/backend-api test
npm --prefix apps/backend-api run typecheck
pnpm --dir apps/quakestrikeph-bulletin check
pnpm --dir apps/quakestrikeph-bulletin build
pnpm --dir apps/quakestrikeph-bulletin generate:api
```

Run worker tests and Ruff from [contributor checks](../../CONTRIBUTING.md#check-before-every-push).
Review generated API changes before committing.

Run the exact disposable Compose commands from CONTRIBUTING.md first. After
the worker migration suite, provision the restricted test role and run Backend
database/Redis checks against that same disposable project:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml exec -T postgres-test sh /opt/quakestrike/provision-roles.sh create-backend
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm backend-test-runner
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

The Python fixtures migrate/truncate only `quakestrike_test`. The Backend
tests require that database name and use test-only provider fixtures. They
check account/audit rollback, uniqueness, ownership and grants, plus Redis
expiry, account/phone fencing, wrong-code exhaustion and sliding limits. They
also check that phone removal clears the number and SMS flag, cancels an
in-flight attempt and writes one `phone_removed` audit row with no number in its
metadata. No live SMS or production API mutation is part of automated tests.

### Browser checks with the Vite fixture

Run these commands from `apps/quakestrikeph-bulletin`. Start the fixture server in one terminal:

```powershell
pnpm exec vite --config tests/accounts/vite.config.mjs
```

In another terminal, run every Vite account check. Stop the sequence if a check fails.

```powershell
foreach ($accountCheckPath in (rg --files tests/accounts -g '*.cjs' -g '!background-saves.cjs' -g '!settings-dialog.cjs')) {
    node $accountCheckPath
    if ($LASTEXITCODE -ne 0) { throw "Account check failed: $accountCheckPath" }
}
node --experimental-strip-types --test tests/accounts/preference-saves.test.mjs
```

`pnpm test:identity` runs the identity protocol and preference queue checks
without a browser or live provider. The identity checks replace raw Clerk
operations below the real production sequencing. Browser checks retain the
Clerk fixture alias and exercise that same sequencing through the screens.

The checks include profile operations, phone operations, phone removal,
devices, authentication, routes, session isolation, preferences, location, and
motion. Phone checks cover replacement refresh failures, attempt deletion
retries, partial success, and responses from former sessions. Device checks
cover session normalization, the current-session guard, provider failures and
responses from former sessions. Authentication checks cover account entry,
email/device codes, enumeration-safe recovery, sensitive credentials, session
tasks, sign-out confirmations, and delayed Clerk successes and failures.
The test-only Clerk adapter can delay or reject individual provider stages and
record their ordering. Unused fixture branches and obsolete
positive actions must not remain in fixture scripts.

As with the existing Bulletin browser checks, expose the bundled Playwright
package via `NODE_PATH` when it is not installed locally. The fixture server
uses a test-only Clerk alias. The production configuration has no fixture alias,
environment toggle or public fixture route. Screenshots and results go to the ignored
`.impeccable/review/accounts` folder. Fixtures validate UI transitions; they
do not prove live Clerk or IPROG success.

### Browser checks with the Astro fixture

Run from `apps/quakestrikeph-bulletin`. Start the Astro fixture in one terminal:

```powershell
$env:PUBLIC_CLERK_PUBLISHABLE_KEY='FIXTURE_ONLY'
pnpm exec astro dev --config tests/accounts/astro.config.mjs --host 127.0.0.1 --port 4333
```

In another terminal, run both regressions:

```powershell
node tests/accounts/background-saves.cjs
node tests/accounts/settings-dialog.cjs
```

Both `background-saves.cjs` and `settings-dialog.cjs` require this Astro fixture
server on port 4333; they do not run against the Vite server.

## Provider and release gates

Local fixtures prove application transitions. They do not prove live Clerk or IPROG success.
Before release, check the target provider instance with an approved recipient and send limit.

1. Verify Clerk signup, Google sign-in, device trust, recovery, and recent verification.
2. Verify IPROG only with explicit authorization for the destination and number of sends.
3. Confirm disposable integration tests ran rather than skipped.
4. Record Docker or provider blockers separately from passing checks.

Missing IPROG credentials make phone verification unavailable. Public reading and email preferences remain usable.
Keep provider tokens in ignored private configuration; do not purchase credits or send verification codes without approval.

### Recorded provider observations

On 2 October 2026, two approved OTP sends verified the live adapter and UI flow.
The UI saved the verified phone, and both alert channels stayed off.
Both sends consumed the approved allowance; that record authorizes no further send or resend.
The token was stored only in the ignored Backend `.env.local` of the former `bulletin-accounts` worktree.
This historical result does not establish readiness of another environment.

## Former isolated account runtime

The former `quakestrike-bulletin-accounts-dev` project is retired from the local
development workflow. Its durable database volume remains recovery evidence.
Configuration copies are preserved under the ignored
`.local/backups/accounts-runtime/` directory in the main checkout.
The former worktree's design files and runtime evidence are archived under
`.local/backups/bulletin-accounts-worktree/` in the main checkout.

Shared runtime setup does not copy account test records or fixture model metadata.
Do not delete the old volume or start both Backends on port 3000.
The separate disposable integration project remains unchanged.

## Account behavior reference

### Clerk instance and password rules

| Setting | Development value or requirement |
| --- | --- |
| App | **QuakeStrike PH Bulletin**, Personal/Hobby. |
| App ID | `app_3K8Qn66bPx5HFT1S1aJQUxveCS0` |
| Instance ID | `ins_3K8Qn2Z9aDmYnNkaBAlmgstZBba` |
| Sign-in | Email/password and Google. |
| Signup | Verified email required. |
| Device Trust | Enabled. |
| Reverification | **5 minutes**, under **Sessions → Session lifetime**. |
| New-password rule | At least eight characters, one lowercase letter, one uppercase letter, and one number. |
| Special characters | Not required. |
| Compromised-password rejection and strength estimator | Off in the recorded development configuration. |
| Email codes | Enabled for device trust and Google-only reverification. |

Set the same five-minute reverification window on the production instance before release.
The Bulletin and Backend use that window for sensitive actions, including other-session sign-out.
Email change/removal is not exposed through hosted profile components.

On 3 October 2026, the user accepted browser-only composition checks for new passwords.
They apply to signup, recovery, required reset tasks, and password addition/change.
Existing-password sign-in and reverification do not apply the new-password rule.
Direct Clerk requests can bypass browser composition checks; Clerk retains its own server-side credential rules.
The implementation requires neither paid composition settings nor a Backend password endpoint.

The recorded development dashboard accepted composition settings without a paid plan change, although Clerk labeled them Pro.
That historical observation does not establish another instance's provider settings.

### Verification window

Sensitive account actions use Clerk's first-factor verification age (`fva[0]`).
The Bulletin refreshes the session token before each freshness check and reads
the claims from Clerk's live session. A numeric age from zero to less than five
minutes qualifies; five minutes, missing claims and negative ages require
reverification. Recent password sign-in or first-factor verification qualifies
without another OTP. Accounts with and without passwords follow the same rule.
When verification expires, the existing email OTP screen requests fresh proof.
The sign-in form retains "Forgot password?" and signed-out email recovery.

### Verification dialog

When proof is missing or expired, the shared gate first shows the masked account
email and a "Send verification code" button. Opening the gate or selecting Back
does not request a code. Only an explicit send opens the code-entry step after
Clerk confirms preparation. Sending disables the button and shows a spinner;
failure leaves the confirmation available for retry. Resend remains explicit.

### Session and proof lifetime

The Bulletin keeps no separate proof cache or verification timestamp in browser
storage. Reload and reopening settings reuse the remaining Clerk verification
window for the same session; neither action restarts that window. Every check
verifies session identity before and after token refresh. Missing tokens and
late responses from another session cannot establish freshness. An explicit
send or resend always requests a code. A provider or Backend reverification
requirement opens the email gate even if the earlier age appeared recent.

The Bulletin checks again before a password save, before replacement phone
send/resend/verification requests and before a mobile-number removal. Expiry
opens email reverification before continuing; a phone SMS OTP remains
independently required for a new number. Password updates omit `currentPassword`
and sign out other sessions. Future email change and account removal must use
this shared gate when implemented; those features remain unavailable in this
release.

### Phone management

Account settings use one Manage action for an existing mobile number. It opens
a compact modal over the account screen without changing `/account`. The modal
contains the heading, description, saved number and two buttons: Remove number
on the left and Change number on the right. Escape and Close dismiss only this modal and restore focus to
Manage. Both actions close the modal and use the shared email verification
gate. Changing screens resets the modal's open state. Back and Cancel return
to Account settings with the modal closed; only Manage opens it again.
Direct removal visits, reloads and history navigation also check proof.
Removal issues `DELETE /api/v1/account/phone`, which returns the updated account,
shows a success notification and returns to Account settings. Removing a number
that is not saved changes nothing, reports no success audit and is not reachable
from the screen because removal redirects when no number exists. Removal always
acquires the shared account lock, rereads the account and cancels pending
verification before deciding whether a saved phone needs clearing. This also
clears a binding committed after the initial read. Start and verification keep
their additional phone lock; an overlapping operation on the same account
reports verification busy.

### Device management

The device screen lists only the signed-in sessions Clerk reports: device type,
browser and a relative last-active time. No city, country, IP address or
hardware identity is shown. The current session is identified as this device and
keeps the existing ordinary sign-out. Other sessions sign out individually or
together through the shared email verification gate, which satisfies Clerk's own
session reverification for the protected action. A stale reverification
requirement reopens the gate and no device action is retried automatically. When
no other sessions exist, the bulk action is hidden.

### Account routes

These account destinations share the settings Dialog and its mobile layout:

| Route | Screen |
| --- | --- |
| `/account/phone` | Existing add/change number and SMS verification flow. |
| `/account/phone/remove` | Mobile-number removal confirmation. |
| `/account/devices` | Signed-in devices with per-device and bulk sign-out. |
| `/account/email` | Unavailable email-change placeholder. |
| `/account/remove` | Unavailable account-removal placeholder. |

Direct visits, reloads and browser history use the same session checks as other
settings routes. Removal without a saved number redirects to `/account`.
The former `/account/phone/manage` page is removed. Change number continues at
`/account/phone`; removal continues at `/account/phone/remove`.
The email-change and account-removal placeholders remain unavailable.

### Server checks

Clerk retains authoritative password/session checks and its own reverification
window. The Backend retains its verified-email, ownership and five-minute
first-factor `fva` checks on authenticated tokens. The browser freshness check
does not replace server authorization. Keep email codes and reverification
enabled; no MFA enrollment is required. Test the target Clerk instance before release.


### Preference saves

This configuration aliases test adapters only. Onboarding Continue commits
channel choices; selected SMS commits only after verification. Switch saves
use a 400 ms debounce. Magnitude Check saves; X discards. Failed background
writes restore confirmed values and show a dismissible error across navigation.

Phone binding and SMS opt-in are separate transactions and have separate
notifications. Successful binding shows "Mobile number verified." immediately.
Selected onboarding SMS then shows "SMS alerts enabled." after its save succeeds.
An opt-in failure shows "SMS alerts could not be enabled." with the Backend reason.
The verified phone remains linked; the existing SMS switch can retry opt-in.
A newer SMS-off edit suppresses the enabled notification. Settings-only phone
verification does not enable SMS.


## Implementation and test reference

Authentication screens use specific views and named workflow operations.
`src/lib/auth` owns all direct Clerk access, including setup, OAuth callbacks,
task widgets, proof selection, activation, provider failures and token handoff.
Its named operations return application steps, safe failures or ignored results.
The account workflow owns form values, password validation, credential clearing,
notifications and navigation. Identity signals credential consumption at the
existing points, including before delayed device proof and task activation.
Form and resend controls invoke an operation directly; the account workflow owns
busy/error handling exactly once. Clerk task widgets retain their configured
`/alerts` destination. The existing native
account sign-out confirmation, shell departure dialog, and immediate profile
cancellation remain distinct.

Identity continuations check both screen lifetime and an opaque session marker.
When the user or session changes, former operations cannot submit follow-up
requests, clear credentials, notify, or navigate. A provider request already
submitted may still complete. This fixes the characterized former-session
password-save notification defect.
Required-task password callbacks also check identity before each request.
This includes Clerk's automatic retry after interactive proof. A former
request's late proof requirement cannot open a new proof dialog. Browser
checks cover successful proof, cancellation, and identity changes before or
during that proof.

`screenRequest` acquires tokens through identity and checks screen/session
lifetime before transport and after its response. `backgroundRequest` checks
only session lifetime, so preference saves continue across Astro navigation.
Both call the existing account HTTP helper; identity imports no account
transport or domain types. The live Clerk client supplies session observations
after an account island unmounts. The account feature retains private-state
reset and preference-queue cancellation. No extra global runtime is required.
First anonymous activation preserves the signup profile handoff. Token refresh
rejection blocks proof continuation; a null refresh retains the existing
continuation, but a later freshness check refuses a missing token.

Account navigation uses a restricted destination operation for Alerts,
Location, and Account. Screen views provide named Back, sensitive-entry,
placeholder, and sign-out operations. The workflow keeps stage transitions,
pending departure callbacks, draft reconciliation, and history coordination
private. The departure dialog receives only its open/error/saving state and
Save, Discard, and Stay actions. Account sign-out retains native discard
confirmation; shell sign-out retains Save/Discard; profile and task sign-out
remain immediate with their existing destinations.

Navigation checks cover dirty Back/Forward, cancel/discard/save/retry,
sensitive history with cleared credentials, shell save-before-sign-out ordering,
and delayed location saves after user or session changes on desktop and mobile.
They also cover guarded settings/public/external links. External destinations
are intercepted by test fixtures; no live external request is required.
Synthetic click checks preserve modified/nonprimary clicks, new-tab links,
downloads, hash links, and the same URL. Synthetic unload checks validate the
handler, not the browser's native unload dialog. Actual Astro navigation checks
continue to verify background-save lifetime and notifications.
