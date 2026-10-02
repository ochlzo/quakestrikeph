# Bulletin account development and checks

This branch adds local account implementation. It does not deploy account
routes or enable automatic earthquake delivery.

## Local configuration

In `apps/quakestrikeph-bulletin/.env.local`, set only the development
`PUBLIC_CLERK_PUBLISHABLE_KEY` and `ACCOUNT_API_TARGET=http://127.0.0.1:3000`.
Account requests use that local proxy; public earthquake reads keep the
existing read-only target. Do not set a production account target during tests.

In `apps/backend-api/.env.local`, set `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`
(the same publishable key as the Bulletin; required for session verification),
`CLERK_AUTHORIZED_PARTIES=http://localhost:4321,http://127.0.0.1:4321`,
`ACCOUNT_REDIS_URL`, `IPROG_API_TOKEN`, the restricted Backend `DATABASE_URL`
and registered `MODEL_RELEASE_ID`. All environment files are ignored by Git.
Migrations and role grants are explicit setup steps; the Backend does neither
at startup. Apply migration head and rerun `create-backend` in the development
database before enabling the new routes. Do not use a development database
for the integration test commands below.

Build with `npm ci`, `npm run build` and start with
`node --env-file=.env.local dist/src/server.js` in `apps/backend-api`.
Run `pnpm install --frozen-lockfile` and `pnpm dev --host 127.0.0.1`
in the Bulletin. Docker builds accept only `PUBLIC_CLERK_PUBLISHABLE_KEY`
as the frontend build argument. Provider secrets go only to the Backend.

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
node tests/accounts/flows.cjs
node tests/accounts/signup.cjs
node tests/accounts/passwords.cjs
```

As with the existing Bulletin browser checks, expose the bundled Playwright
package via `NODE_PATH` when it is not installed locally. The fixture server
uses a test-only Clerk alias; Astro has no such alias, environment toggle or
public fixture route. Screenshots and results go to the ignored
`.impeccable/review/accounts` folder. Fixtures validate UI transitions; they
do not prove live Clerk or IPROG success.

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

## Prepared local account runtime

The ignored `.impeccable/runtime/accounts/compose.yml` and its ignored `.env`
prepare the separate `quakestrike-bulletin-accounts-dev` project. It is not the
disposable integration project. It has a durable local volume, private database
and Redis, restricted Backend grants, and a localhost-only API port. Start it
from the worktree with:

```powershell
docker compose --env-file .impeccable/runtime/accounts/.env -f .impeccable/runtime/accounts/compose.yml up -d postgres redis backend
```

Its migrations are already applied. The `account-ui-fixture` model metadata
is solely for account UI startup, never for forecasts. No prediction worker runs.
The current user-owned Bulletin dev server runs on `http://localhost:4321`
(IPv6 loopback); do not assume it also binds `127.0.0.1` or restart it without
need. Avoid `down -v`
on this development project when retaining account test data.
