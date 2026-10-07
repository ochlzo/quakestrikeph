# Bulletin account development and checks

This branch adds local account implementation. It does not deploy account
routes or enable automatic earthquake delivery.

## Local configuration

Accounts use the shared local `infrastructure` Compose project and root `.env`.
Follow [the local web setup](local-runtime.md#9-add-the-local-backend-and-bulletin).
The Bulletin and Backend share the worker database and Redis service.
Provider secrets reach only the Backend. The Bulletin receives the publishable key.
Apply migrations and restricted Backend grants before starting account routes.
Do not include `compose.edge.yml` during local development.

The development Clerk app is **QuakeStrike PH Bulletin** in Personal/Hobby:
`app_3K8Qn66bPx5HFT1S1aJQUxveCS0`, instance
`ins_3K8Qn2Z9aDmYnNkaBAlmgstZBba`. Email, verified email signup, password
and Google are enabled. Device Trust remains enabled. The user-approved password
policy is at least 8 characters, including one lowercase letter, one uppercase
letter and one number. Compromised-password rejection and the strength estimator
are off; special characters are not required. These settings were saved and
verified in the development dashboard. Clerk labels character-composition rules
as Pro; this development instance accepted them without a paid plan change.
On 3 October 2026 the user accepted UI-only composition checks on signup,
recovery, required password-reset session tasks and password addition/change.
These browser checks can be bypassed through direct Clerk requests; the user
accepts that limitation. Clerk owns credentials and applies its own server-side
rules. Custom paid composition settings and a Backend password endpoint are
not required. Existing-password sign-in and reverification do not apply the
new-password composition rule. See [ADR 0042](../adr/0042-bulletin-account-implementation.md).
Keep email-code
capability enabled for device trust and Google-only reverification. Account
email change/removal is not exposed through hosted profile components.

## Automated checks

Run `npm test` and `npm run typecheck` in the Backend; run `pnpm check`,
`pnpm build` and `pnpm generate:api` in the Bulletin. Run the worker tests,
Ruff lint and Ruff formatting checks from CONTRIBUTING.md.

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
expiry, account/phone fencing, wrong-code exhaustion and sliding limits.
No live SMS or production API mutation is part of automated tests.

For browser checks, start the separate fixture server in the Bulletin:

```powershell
pnpm exec vite --config tests/accounts/vite.config.mjs
```

In another terminal, run every Vite account check. Stop the sequence if a check fails.

```powershell
foreach ($accountCheckPath in (rg --files tests/accounts -g '*.cjs' -g '!background-saves.cjs')) {
    node $accountCheckPath
    if ($LASTEXITCODE -ne 0) { throw "Account check failed: $accountCheckPath" }
}
node --experimental-strip-types --test tests/accounts/preference-saves.test.mjs
```

The checks include profile operations, phone operations, authentication,
routes, session isolation, preferences, location, and motion. Phone checks
cover replacement refresh failures, attempt deletion retries, partial success,
and responses from former sessions. Authentication checks cover account entry,
email/device codes, enumeration-safe recovery, sensitive credentials, session
tasks, sign-out confirmations, and delayed Clerk successes and failures.
The test-only Clerk adapter can delay or reject individual provider stages and
record their ordering. Unused fixture branches and obsolete
positive actions must not remain in fixture scripts.

Authentication screens use specific views and named workflow operations.
The workflow owns Clerk requests, activation, credential clearing, notifications,
and operation-specific transitions. Form and resend controls invoke an operation
directly; each operation owns busy/error handling exactly once. Clerk task
widgets retain their configured `/alerts` destination. The existing native
account sign-out confirmation, shell departure dialog, and immediate profile
cancellation remain distinct.

Authentication continuations check both workflow lifetime and Clerk identity.
When the user or session changes, former operations cannot submit follow-up
requests, clear credentials, notify, or navigate. A provider request already
submitted may still complete. This fixes the characterized former-session
password-save notification defect. General navigation restructuring remains
separate work.
Required-task password callbacks also check identity before each request.
This includes Clerk's automatic retry after interactive proof. A former
request's late proof requirement cannot open a new proof dialog. Browser
checks cover successful proof, cancellation, and identity changes before or
during that proof.

As with the existing Bulletin browser checks, expose the bundled Playwright
package via `NODE_PATH` when it is not installed locally. The fixture server
uses a test-only Clerk alias. The production configuration has no fixture alias,
environment toggle or public fixture route. Screenshots and results go to the ignored
`.impeccable/review/accounts` folder. Fixtures validate UI transitions; they
do not prove live Clerk or IPROG success.

For saves across Astro navigation, start the isolated Astro configuration in
another terminal, then run its browser regression:

```powershell
$env:PUBLIC_CLERK_PUBLISHABLE_KEY='FIXTURE_ONLY'
pnpm exec astro dev --config tests/accounts/astro.config.mjs --host 127.0.0.1 --port 4333
node tests/accounts/background-saves.cjs
```

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

## Provider and release gates

The user's existing Google-linked IPROG account was accessed on 2 October
2026. With explicit approval, its existing API token was saved only in the
ignored Backend `.env.local` in the `bulletin-accounts` worktree. No new
token was created or credits purchased. The user then approved up to two OTP
messages to their nominated number. Both approved sends have now been used:
the live adapter and subsequent UI flow passed network support, attempt-bound
HMAC and provider verification checks. The UI flow saved the verified phone
binding, and both alert channels stayed off. No further send or resend is
authorized. Do not buy credits,
send a test code, or enable a real destination without that authorization.
Setup alone does not prove delivery. Missing credentials show verification
unavailable while email preferences and public reading remain usable.

Before a release, verify live Clerk signup/Google/device trust/recovery and
recent proof; verify IPROG with an approved recipient and send cap. Confirm
the disposable integration tests actually ran rather than skipped. Report
Docker/provider blockers explicitly. No production migration, deployment,
merge or alert-send action is authorized by this implementation request.

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
