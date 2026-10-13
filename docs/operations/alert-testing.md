# Private alert-testing session, draft, and preparation controls

## Ticket 62 P3 Standards correction: polling diagnostics, 14 October 2026

The polling workflow now reports normalized operational errors instead of
discarding them. The existing runtime logger emits structured JSON warnings
for unavailable SMS polling and information events for verified recovery.
Context includes the service, operation, provider, event/job UUID, attempt UUID,
and an allowlisted error category. Logs exclude provider references, complete
destinations, message content, raw exceptions, credentials, and payloads.

One in-memory failure category bounds diagnostics to one warning per outage
and one recovery event. Repeated failures, including changes in error category,
remain quiet until a verified accepted, failed, or delivered provider response.
Ordinary unknown responses without operational errors remain quiet and cannot
prove recovery. No due candidate or inactive session can establish recovery.
Provider exceptions become the fixed `provider_transport_uncertain` category.
The report callback receives normalized outcomes, never the private row.

The fix changes only `application/reconciliation.py`, `consumer_runtime.py`,
the existing consumer runtime unit test, this record, and the new
`workers/tests/unit/test_alert_testing_reconciliation.py`. Poll scheduling,
Redis authorization, accepted/delivered meanings, and the no-resubmission rule
remain unchanged. All ticket 62 and unrelated edits remain uncommitted and
unstaged on `codex/alert-testing-reconciliation`.

Verification for this correction:

| Command/check | Result |
| --- | --- |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests/unit/test_alert_testing_reconciliation.py workers/tests/unit/test_alert_testing_consumer_runtime.py -q` | Seven passed. |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests -q` | 496 passed; 397 expected skips (386 integration cases without test URLs and 11 Windows platform cases). |
| `uv run --project workers ruff check workers database` | Passed. |
| `uv run --project workers ruff format --check workers database` | Passed; 229 files formatted. |
| Exact isolated Compose integration sequence below | 384 passed; two expected real-model skips. All 20 reconciliation and 33 delivery cases ran and passed. |
| Separate real-model checks below | Two passed; 24 deselected; no skips or retry attempts. |
| Unstaged, staged, and new-file whitespace checks | Passed; nothing staged. |

The focused regressions exercise each operational category, exceptions,
unrecognized error sanitization, ordinary unknown responses, missing candidates,
category changes during an outage, accepted/failed/delivered recovery,
correlation fields, privacy, runtime wiring, and no submission calls.

Suppression uses process memory and resets when the consumer restarts. A
recovery event confirms a usable provider status response, not handset receipt.

The disposable checks use the required project and fake providers:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile prediction-smoke run --build --rm prediction-smoke-runner pytest --config-file workers/pyproject.toml workers/tests/integration/test_prediction_worker.py -k test_real_seis -s
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Backend and private-app checks were not repeated because this correction changes
only Python diagnostics and its tests. Their earlier ticket 62 results remain
recorded below. Manual browser acceptance, independent re-review, and controlled
provider verification remain separate. No live provider calls or target
activation belong to this correction.

The documented `down -v` completed after verification and removed only the
disposable project's PostgreSQL, Redis, and network. Existing local services
remain untouched. The correction is ready for independent re-review.

## Ticket 62: evidence reconciliation and session closure, 14 October 2026

Branch: `codex/alert-testing-reconciliation`.
Baseline: `93e8903af5ae2a77174e9fc2e857b2ba56256753`.
Implementation re-review passed with zero Standards and Spec findings. Dependency PRs
66–69 remain the starting implementation; their earlier checks do not verify
this slice. Unrelated Bulletin and local Compose edits remain preserved.

The Backend authenticates Brevo callbacks before inspecting the test marker.
Test callbacks update only active session-owned Redis attempts. Ordinary
callbacks keep the established PostgreSQL route, authentication, response
mapping, and narrow write capability. Early callbacks use the pre-call attempt
index; duplicate and older evidence cannot regress delivered outcomes.
Reference collisions return conflicts. Submission responses merge with early
evidence. Closed, expired, replaced, or deleted test sessions acknowledge late
authenticated callbacks without restoring children. Redis outages and missing
active correlation retain 429 with `Retry-After: 60`, never false absence.

The isolated consumer polls one known SMS reference per pass. Each claim
postpones the attempt's next poll by 60 seconds, including unknown responses
and interrupted processes. Polling uses the existing authenticated IPROG
adapter and never submits messages. Delivered and failed evidence strengthen
outcomes without automatic resend. Timestamp-free polls do not invent a
provider event time. Private Results display masked destinations and bounded
reference-conflict notes; references and message content remain private.

End Test closes creation, reservations, and public reads before cleanup.
The private UI presents server-confirmed call waiting, record deletion,
cleanup failure/retry, ended, and expired states across separate pages.
Waiting uses the conservative maximum 15-second authorization grace period,
not a count of calls. Closure and completion timestamps remain bounded
lifecycle metadata until the existing tombstone expires. Polling and retries
never extend metadata or child retention. Cleanup removes only the owning
UUID's keys, including attempts, references, poll scheduling, and Stream state.
Unfinished inputs and preparation remain only in browser memory.

### Configuration and verification setup

The Backend's `ALERT_TEST_REDIS_URL` must select the same explicit Redis
instance as the control and consumer. The existing `BREVO_CALLBACK_TOKEN`
authenticates `/api/v1/callbacks/brevo` before production or test routing.
Test email submissions retain
`quakestrike-attempt:test:<session>:<event>:<attempt>` in `X-Mailin-custom`.
A missing test connection returns a retry response and cannot use PostgreSQL.
IPROG polling uses the existing `ALERT_TEST_IPROG_TOKEN`; no additional provider
credential or activation setting is added. Runtime packaging remains ticket 63.

Run the exact disposable Compose integration procedure in CONTRIBUTING.md.
After worker migrations and checks finish, run the Backend integration runner
against those same disposable services:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml exec -T postgres-test sh /opt/quakestrike/provision-roles.sh create-backend
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile backend run --build --rm backend-test-runner
```

The first command provisions only the disposable database's restricted Backend
role, using its configured integration-only password. The worker suite creates
and migrates the database but does not provision that login password.

Backend integration files run serially because the public-reader and callback
fixtures both own the shared control key in disposable Redis. Tests refuse a
pre-existing active fixture. Never run worker and Backend fixtures concurrently.
Run the separate documented real-model checks when the local bundle exists.
Finish the isolated project with the documented `down -v` command.

### Ticket 62 checks

| Check | Observed result |
| --- | --- |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests -q` | 490 passed; 397 skipped. Host skips include 386 integration cases and 11 Windows platform cases. |
| Exact isolated Compose worker integration procedure | 384 passed; two expected real-model skips. All 20 reconciliation cases and 33 existing delivery cases executed. |
| Focused reconciliation file through disposable Compose with source/test mounts | 20 passed. |
| Backend integration runner after disposable role provisioning | Seven passed; none skipped. Ordinary PostgreSQL callbacks, test Redis callbacks, account grants, and public reads all executed. |
| Separate documented `prediction-smoke-runner` with `-k test_real_seis -s` | Two passed; 24 deselected; none skipped. Known forecast and replica benchmark passed with no retry attempts. |
| Backend unit files through `node --test` | 35 passed; none skipped. |
| Backend build and `typecheck` | Passed. |
| Private app `check`, `test`, and `build` | Passed; 24 tests, zero errors/warnings, four incumbent Select hints, four static pages. |
| Worker Ruff check and format check | Passed; 228 files formatted. |
| Python producer/consumer with actual authenticated Backend callback | Passed: early delivered email survived its acceptance response; known-reference SMS polling delivered; closure waited; late callbacks acknowledged without revival. |
| Local desktop and 390px mobile inspection | Real waiting/deletion pages and cleanup failure/retry/ended states inspected with disposable Redis. Retry invoked the actual cleanup endpoint. |
| Unstaged, staged, and new-file whitespace checks | Passed; nothing staged. |

The first full worker integration run exposed two reference-conflict paths that
shared the session-conflict result code: 373 passed, two failed, two skipped.
Using a separate bounded reference-conflict result corrected both paths.
The 20-case focused rerun and final 384-case full rerun passed afterward.

The initial Backend integration run lacked the disposable Backend login
password. Four existing checks failed authentication or dependent assertions.
The new Redis case also exposed a timing-sensitive TTL assertion, which now
checks the exact absolute expiry instead of comparing separate clock reads.
The documented disposable role provisioning step supplies the existing
integration-only password and grants before the final Backend rerun.

The local compatibility smoke and browser fixture used a separate disposable
Redis container, read-only fictional accounts, and fake providers. Preview
servers, the browser tab, and the container were stopped afterward.
No live provider call or target-environment action occurred. The screenshot
`C:/Users/cholo/AppData/Local/Temp/ticket62-ended-ui.png` records the real cleanup
page after its server action. Browser inspection does not replace the user's
full manual acceptance or controlled handset/inbox verification.

The final `docker compose ... down -v` completed successfully for
`quakestrike-data-ingestion-test`. Its PostgreSQL, Redis, and network were
removed. Existing local services and unrelated edits remain preserved.

Host integration skips do not establish Redis verification. Fake acceptance or
delivery reports do not prove handset or inbox receipt.

### Ticket 62 review scope

The 24 changed files for this ticket, including the P3 correction, are:

| Directory | Files |
| --- | --- |
| `apps/backend-api/` | `package.json`; `src/application/alerts/brevo.ts`; `src/interface/http/routes/brevo.ts`; `src/ports/alertDelivery.ts`; `src/server.ts`; new `src/infrastructure/redis/testBrevo.ts`; `tests/unit/brevo.test.ts`; `tests/integration/brevo.test.ts`. |
| `apps/quakestrikeph-alert-testing/src/features/` | `delivery/DeliveryPages.tsx`; `sessions/Workspace.tsx`; `sessions/use-session.ts`. |
| `packages/contracts/alert-testing/` | `README.md`; `session-v1.ts`; `delivery-v1.ts`. |
| `workers/src/quakestrike/alert_testing/` | New `application/reconciliation.py`; `consumer_runtime.py`; `domain/sessions.py`; `infrastructure/deliveries.py`; `infrastructure/redis.py`. |
| `workers/tests/` | New `integration/test_alert_testing_reconciliation.py`; new `unit/test_alert_testing_reconciliation.py`; `unit/test_alert_testing_consumer_runtime.py`. |
| `docs/` | `adr/0050-private-alert-testing-session-runtime.md`; `operations/alert-testing.md`. |

Outdated DFDs do not control this review. Written specifications, the glossary,
and accepted ADRs govern the implementation. The ignored prototype remains
unchanged and supplies only the accepted visual reference. The private app
uses real lifecycle controls and excludes simulated completion actions.

### Remaining manual acceptance

1. End a session during an authorized call on desktop and mobile.
2. Confirm every operator sees closure and bounded waiting before deletion.
3. Confirm public links fail immediately, including already-open replay pages.
4. Confirm expired sessions show cleanup progress without accepting new work.
5. Exercise cleanup failure and Retry cleanup while other operators remain closed.
6. Confirm no simulated completion or preview controls appear in the private app.
7. Verify controlled provider callback behavior under separate authorization.

Submitted messages and provider-held history cannot be recalled or deleted by
End Test. No target activation, Serve configuration, production account write,
live provider call, commit, push, PR, or deployment belongs to this slice.

## Ticket 61 review corrections, 14 October 2026

The final Redis authorization gate now reads the submitted scenario's immutable
forecast deadline before allowing transport. Session ownership and reservation
lifetime remain separate checks. The new regression test expires only the
forecast fixture between reservation and authorization, while retaining an
active session and its original deadline. Neither provider receives a submission.

The isolated consumer uses the existing JSON logging adapter for sanitized
dependency-failure and recovery events. Repeated failures in the same dependency
reuse the existing outage state rather than logging every retry. Routine
`SessionConflict` handling stays quiet. Redis recovery requires a successful
Redis pass; account recovery requires successful consumption. An inactive
session cannot establish account recovery. Messages and context contain fixed
event names and dependency categories, never raw exception text, destinations,
message bodies, credentials, or private payloads.

These fixes change only `consumer_runtime.py`, `infrastructure/deliveries.py`,
the delivery integration test, the new `test_alert_testing_consumer_runtime.py`,
and this operations record. All other ticket 61 changes and unrelated Bulletin
and Compose edits remain preserved, uncommitted, and unstaged.

Review-fix verification:

- Host worker suite: 490 passed, 377 skipped because integration URLs were unset
  or Windows did not support the platform-specific checks.
- Consumer diagnostics regression: passed after the account-recovery refinement.
- Required isolated Compose integration suite: 364 passed, two expected real-model
  skips. All 33 delivery workflow cases ran and passed.
- Ruff check and format check: passed; 226 files formatted.
- Unstaged and staged whitespace checks: passed; no files staged.
- Separate real-model forecast and replica benchmark: two passed, 24 deselected;
  no skips. Both replicas completed without retry attempts.

Commands used the documented `up -d --wait`, `run --build --rm test-runner`,
separate `--profile prediction-smoke` runner, and `down -v` sequence with the
`quakestrike-data-ingestion-test` Compose project. The disposable services were
removed after verification. No target-server changes or live provider calls
were performed by these corrections. Manual browser acceptance remains separate;
these review fixes change no UI behavior.

## Ticket 61: local submission and delivery implementation

Branch: `codex/alert-testing-delivery`.
Review baseline: `61a0c219bed299f89830e14aaca2104edd77726b`.
Dependency PRs 66–68 were open and unmerged when this branch was created.
Implementation review passed with zero Standards and Spec findings.

Simulate and Send authenticates the browser-held preparation, saves its exact
values, freezes selected account IDs, and queues the event identity. The
control process never renders messages or contacts providers. The isolated
consumer reads only selected accounts and rechecks each channel immediately
before transport. History and Results follow the accepted prototype, with
desktop tables and stacked mobile outcomes. History pages retain older links.
Accepted confirms submission only; delivered evidence belongs to ticket 62.

### Local control setup

Use the existing disposable Redis and private-app setup below. Never select a
development or production database for migrating or truncating test fixtures.
The account connection, when configured, must use the restricted
`quakestrike_alert_testing` login; the adapter rejects broader grants.

1. Build the private application.

   ```powershell
   pnpm --dir apps/quakestrikeph-alert-testing build
   ```

2. Generate the local preparation key.

   ```powershell
   $env:ALERT_TEST_PREPARATION_KEY = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
   ```

3. Set `ALERT_TEST_REDIS_URL` to the disposable Redis instance.
4. Set `ALERT_TEST_DATABASE_URL` to the restricted account connection, when account reads are needed.
5. Set `ALERT_TEST_PUBLIC_BULLETIN_URL` to the public or local Bulletin origin.
6. Start the loopback control process.

   ```powershell
   uv run --project workers python -m quakestrike.alert_testing.runtime --port 4341
   ```

Keep the same preparation key across control restarts. Generating another key
invalidates unfinished preparations; it does not change saved scenarios.
Both control and consumer must use the same explicit test Redis connection.
Message links use the origin frozen on the submitted job, even if a later
consumer configuration changes. The Backend's `ALERT_TEST_REDIS_URL` must
select that instance for public synthetic reads.

### Consumer runtime and fake-provider verification

The separate runtime is `python -m quakestrike.alert_testing.consumer_runtime`.
It refuses startup unless `ALERT_TEST_CONSUMER_ENABLED=true`. It requires
explicit test Redis and restricted account URLs. Real transport additionally
uses `ALERT_TEST_IPROG_TOKEN`, `ALERT_TEST_BREVO_API_KEY`,
`ALERT_TEST_BREVO_SENDER_EMAIL`, and `ALERT_TEST_BREVO_SENDER_NAME`.
Existing adapters require the Linux main thread for their 12-second deadline.
No production environment variable or queue enables this consumer implicitly.
This ticket does not authorize setting those credentials, running live sends,
or activating a target environment. Packaging and Serve remain ticket 63.

Reproduce the authorized fake-provider workflow checks from the repository root:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

`workers/tests/integration/test_alert_testing_delivery.py` starts the private
HTTP API with disposable Redis, read-only account fixtures, and injected fake
providers. It consumes the actual isolated Stream. It covers unchanged reviewed
observations, request and command duplicates, interrupted storage, queue outages,
concurrent reservations, lost responses, malformed or stale preparation, changed
settings, SMS uncertainty, forecast expiry, closure, replacement, and late writes.
It also checks masked Results projections, independent channels, frozen content,
the original public URL, and earlier links across History pages.

No test account adapter offers a write interface. PostgreSQL synthetic writes
and production queue publication are absent from this module. Queue isolation
checks retain unrelated commands. Diagnostic output excludes destinations,
saved coordinates, content, provider credentials, and complete provider responses.

### Verification on 14 October 2026

| Check | Observed result |
| --- | --- |
| Required Compose integration suite | 362 passed; two expected real-model skips. |
| Final delivery workflow regression checks with source/test mounts | 32 passed. |
| Separate real-model smoke and replica checks | 2 passed; 24 deselected; no skips. |
| Host worker unit and contract checks | 487 passed; 11 Windows-specific skips. |
| Final host worker suite (`workers/tests`) | 489 passed; 376 skips for unconfigured integration services and Windows restrictions. |
| New preparation-signature unit checks | 2 passed. |
| Linux transport and signature checks with source/test mounts | 12 passed. |
| Ruff check and format check | Passed; 225 files formatted. |
| Private app check | Zero errors/warnings; four incumbent Select deprecation hints. |
| Private app tests | 24 passed. |
| Private app static build | Passed; four separate pages. |
| Backend build and actual producer/reader compatibility | Passed; reader loaded the submitted scenario and all 22 observations. |
| Local desktop and 390px mobile inspection | History rows, Results table, and stacked outcomes inspected with fake providers. |
| Unstaged, staged, and new-file whitespace checks | Passed; nothing staged. |

An additional repo-wide Linux unit run in the integration image produced
16 failures, 472 passes, and 10 skips. That image omits deployment scripts and
Git context required by unrelated repository tests. A focused rerun confirmed
missing `infrastructure/scripts/deploy-workers.sh` and the absent Git context
for the preserved-snapshot check. The supported host checks passed; the focused
Linux deadline checks passed. No runtime or deployment code was changed to
accommodate that image limitation.

The local preview used a separate disposable Redis container, fictional accounts,
and fake providers. The preview process and Redis container were stopped.
The user still performs manual browser acceptance. No live provider calls,
actual sends, target-server edits, deployment, commit, push, or PR occurred.

### Review scope

The worker changes are confined to `workers/src/quakestrike/alert_testing/`:
`application/scenarios.py`, new `application/submissions.py` and
`application/delivery.py`, `domain/testers.py`, `infrastructure/redis.py`, new
`infrastructure/preparation.py` and `infrastructure/deliveries.py`,
`interface/http.py`, new `interface/consumer.py`, `runtime.py`, and new
`consumer_runtime.py`. Production worker implementations and account grants
remain unchanged. The restricted account reader is reused without modification.

The private app changes cover `ScenarioForm.tsx`, browser workspace memory and
its hook, `lib/api.ts`, `pages/history.astro`, new `pages/results.astro`, new
`features/delivery/DeliveryPages.tsx`, `styles/tool.css`, and new
`styles/delivery.css`. No prototype or public Bulletin component was edited
for ticket 61.

Contracts add `packages/contracts/alert-testing/delivery-v1.ts` and amend
`scenarios-v1.ts` and its README. ADR 0050 records signing, retry, consumer,
reservation, and bounded cleanup decisions. Tests add
`workers/tests/integration/test_alert_testing_delivery.py` and
`workers/tests/unit/test_alert_testing_preparation.py`, amend the control-runtime
unit fixture, and extend the private app's `workspace-memory.test.mjs`.

Preserved unrelated edits include `infrastructure/compose.local.yml`, the
Bulletin's `astro.config.mjs`, and Bulletin component, event-result, cache,
stylesheet, and test edits that appeared during implementation. They are outside
ticket 61's review scope. Nothing is staged. Review this scoped change against
the baseline above; the branch contains all three dependency implementations.

### Manual acceptance

Use a separately authorized fake-provider fixture environment for these checks.

1. Start Test and select fixture accounts on Testers.
2. Prepare a scenario and inspect its reviewed observation diagram.
3. Select Simulate and Send and confirm navigation to Results.
4. Confirm email and SMS have separate outcomes and masked destinations.
5. Open History and revisit each saved Results and forecast link.
6. Inspect the desktop table and stacked mobile outcomes.
7. Interrupt the submission response and retry the same reviewed request.
8. Confirm that an uncertain submission blocks edits until its result is resolved.
9. After confirmed acceptance, prepare another replay and confirm a new event identity.
10. Change fixture settings after queueing and confirm the consumer respects those changes.
11. End Test during a fake call and confirm the session closes before cleanup completes.
12. Confirm that late outcomes cannot restore records or affect a replacement session.

Closure may retain the metadata's 15-second authorization grace after calls
finish. Business records always keep the original session deadline. Full
callback reconciliation and closure presentation remain ticket 62. The
incumbent tailnet-origin validator does not yet accept HTTPS 8443; ticket 63
owns that packaging/configuration change. This ticket configured no Serve route.

## Ticket 60: public forecast reads and local acceptance

Branch: `codex/alert-testing-public-forecasts`.
Starting commit: `a68023fd3c98a627da79d34c691e846efb26a95e`.
PRs 66 and 67 were open and unmerged when the branch was created.
The ticket 60 implementation remains uncommitted for coordinating review.

The Backend reads submitted records through `SyntheticScenarioReader` and a
read-only Redis adapter. The contract is documented in
[the submitted-record contract](../../packages/contracts/alert-testing/README.md#submitted-public-record-version-1-ticket-60).
Ticket 61 supplies the producer: validate the reviewed scenario, persist the
exact values once under the owning active session, and queue its identity.
No save action, submission endpoint, queue consumer, history, or provider
workflow is implemented by ticket 60.

The Bulletin preserves `test=true` through server detail, observation pages,
retry, and reload. Back to earthquakes opens `/` without dummy selection.
The existing layout, copy, map, and replay controls remain in use.
The PHIVOLCS link opens the real bulletin index. Synthetic responses and HTML
use `no-store`. JavaScript checks open-page validity every 15 seconds, on
focus/visibility restoration, and at expiry. Invalidation clears replay data
and reloads the existing invalid-link or service-unavailable state.
Back/forward cache restoration also reloads. Without JavaScript, validity is
checked on each page request; open-page polling and replay require JavaScript.

### Disposable browser fixture

This test-only harness needs no production database, accounts, or providers.
It binds only to loopback and refuses any Redis URL other than the disposable
instance below. Normal fixture lists are empty. It adds no public write route.
Do not use development or production Redis for fixture seeding.

1. Create the disposable Redis container.

   ```powershell
   docker run --rm --detach --name quakestrike-alert-testing-preview --publish 127.0.0.1:6387:6379 redis:7.4.11-bookworm redis-server --save "" --appendonly no
   ```

2. Build the Backend fixture code.

   ```powershell
   pnpm --dir apps/backend-api build
   ```

3. Start the fixture API in a separate terminal.

   ```powershell
   $env:TEST_REDIS_URL = 'redis://127.0.0.1:6387/0'
   node apps/backend-api/dist/tests/fixtures/previewSynthetic.js
   ```

4. Start the Bulletin with the fixture API in another terminal.

   ```powershell
   $env:API_TARGET = 'http://127.0.0.1:4312'
   pnpm --dir apps/quakestrikeph-bulletin dev --host 127.0.0.1 --port 4321
   ```

5. Open [the synthetic forecast](http://127.0.0.1:4321/forecasts/11111111-1111-4111-8111-111111111111?test=true).
6. Play and seek past 30 minutes to inspect inside, spillover, and background observations.
7. Reload the page and confirm that values and observation identities remain unchanged.
8. Confirm that replay stops at Now and retains the forecast's original 24-hour window.
9. Check the map, disclosures, replay controls, and navigation at desktop and mobile widths.
10. Open PHIVOLCS and confirm that the bulletin index loads.
11. Use Back to earthquakes and confirm that `/` has no dummy selection or test mode.
12. Open the same event without `test=true` and confirm that no synthetic data appears.
13. Close the fixture session while leaving its scenario key present.

   ```powershell
   docker exec quakestrike-alert-testing-preview redis-cli HSET quakestrike:alert-testing:session lifecycle closed cleanup failed
   ```

14. Confirm that the open page changes to Invalid earthquake link within 15 seconds plus request time.
15. Reload the link and confirm that the invalid-link state remains.
16. Stop disposable Redis and reload the link to check service-unavailable and its test-preserving retry URL.

   ```powershell
   docker stop quakestrike-alert-testing-preview
   ```

Stop both local terminals with Ctrl+C after acceptance. Remove process-scoped
`TEST_REDIS_URL` and `API_TARGET` from those terminals if you reuse them.
The fixture harness also deletes its own keys on ordinary shutdown.

These loopback steps establish fixture-backed behavior only. They do not
establish access from outside Tailscale or an end-to-end send. The user must
verify public access without Tailscale after a separately authorized deployment
and ticket 61 submission. No Tailscale configuration, deployment, provider
send, or production operation occurred during ticket 60 implementation.

### Contributor verification for public reads

Run the three isolated Compose commands in `CONTRIBUTING.md` first. Before
teardown, provision only the disposable Backend role and run its integration
runner:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml exec -T postgres-test sh /opt/quakestrike/provision-roles.sh create-backend
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile backend run --build --rm backend-test-runner
```

Then run the documented `down -v` command. Never run the Backend fixtures
against a development or production database. The synthetic Redis workflow
requires the isolated Compose hostname `redis-test` and refuses a pre-existing
control hash. It covers repeated detail reads, paging, privacy, missing and
unsubmitted records, closure before cleanup, failed-cleanup gating, expiry,
replacement, corrupt storage, dependency failure, and production isolation.

Host verification uses Backend typecheck/build/unit tests and Bulletin
check/build, `test:forecast`, `test:forecast-replay`, and
`test:forecast-navigation`. The navigation script needs Playwright and Edge;
the bundled runtime can supply Playwright through `NODE_PATH` without adding
a project dependency. Git whitespace and full-diff inspection complete the
local checks. Browser acceptance remains the user's verification.

The shared checkout also contains an unrelated edit to
`infrastructure/compose.local.yml`. Ticket 60 preserves that edit.

### Ticket 60 verification record

| Check | Result |
| --- | --- |
| Backend `typecheck` and `build` | Passed. |
| Backend build plus `node --test apps/backend-api/dist/tests/unit/*.test.js` | 32 passed; no skips. Equivalent to `test` because host npm is unavailable. |
| Exact worker Compose integration procedure in `CONTRIBUTING.md` | 331 passed; two expected real-model skips. Integration cases executed. |
| Isolated Backend role provisioning and `backend-test-runner` | Six passed; no skips, including the submitted-scenario Redis workflow. |
| Bulletin `check` | Zero errors/warnings; seven existing hints. |
| Bulletin `build` | Passed; existing large-chunk warning. |
| Bulletin `test:forecast` | Passed, including synthetic routes, canonical query, invalid links, retry, and escaping. |
| Bulletin `test:forecast-replay` | 20 passed, including six new validity/source/cache checks. |
| Bulletin `test:forecast-navigation` with bundled Playwright via `NODE_PATH` | Passed desktop/mobile navigation, replay, accessibility interactions, and error rendering. |
| `git diff --check` and `git diff --cached --check` | Passed. |

The initial navigation invocation could not resolve `playwright`; the bundled
runtime supplied that existing test prerequisite without a project dependency.
No worker code or tests changed, so separate worker unit/Ruff checks were not
required. The real-model runner was not run; model behavior is outside ticket 60.
The fixture preview harness is provided for manual acceptance; no deployed
end-to-end send or user browser acceptance is claimed.

The package runner created an untracked Bulletin `.pnpm-store/` cache.
Automatic approval review blocked both recursive cache removal and deletion
of the identified cache file, without a more specific reason. The generated
cache remains on disk. A repository-local `.git/info/exclude` entry prevents
accidental staging; no shared ignore file changed.

Issue [57](https://github.com/ochlzo/quakestrikeph/issues/57) implements the
shared session only. Starting creates no scenario, queue command, or provider
request. Issue [58](https://github.com/ochlzo/quakestrikeph/issues/58) adds
restricted account search and independent drafts in browser memory. Consumer,
provider credentials, public control routes, and production deployment remain
outside these slices.

Issue [59](https://github.com/ochlzo/quakestrikeph/issues/59) adds validated
scenario preparation and the review diagram. Preparation remains in browser
memory and creates no scenario record or sending work.

Container packaging and release-readiness work belong to
[issue 63](https://github.com/ochlzo/quakestrikeph/issues/63).

The private UI has separate Scenario, Testers, and History pages, one shared
Astro layout, and the accepted prototype's shell and session presentation.
The shell receives page content and never switches between screens.
Later-ticket features remain
explicitly unavailable. The tool reuses the Bulletin theme and React Aria
controls from `packages/ui`; the Bulletin retains its existing import paths.

Architecture and runtime boundaries are recorded in
[ADR 0050](../adr/0050-private-alert-testing-session-runtime.md).
The [private HTTP contract](../../packages/contracts/alert-testing/README.md)
defines request headers, responses, ownership, and errors.

## Local browser acceptance with disposable Redis

Run these commands from the repository root. Do not source the production or
development `.env`. This example creates an independent, disposable Redis
container with persistence disabled. It does not start the full worker stack.
If Docker is unavailable, stop at the Docker command and report the error.

1. Install the locked private UI dependencies.

   ```powershell
   pnpm --dir apps/quakestrikeph-alert-testing install --frozen-lockfile
   ```

2. Build the private UI.

   ```powershell
   pnpm --dir apps/quakestrikeph-alert-testing build
   ```

3. Create the disposable Redis container.

   ```powershell
   docker run --rm --detach --name quakestrike-alert-testing-preview --publish 127.0.0.1:6387:6379 redis:7.4.11-bookworm redis-server --save "" --appendonly no
   ```

4. Select that disposable Redis instance.

   ```powershell
   $env:ALERT_TEST_REDIS_URL = 'redis://127.0.0.1:6387/0'
   ```

5. If tester search is required, configure the restricted account connection.

   ```powershell
   $env:ALERT_TEST_DATABASE_URL = 'postgresql+psycopg://quakestrike_alert_testing:<URL-encoded-password>@127.0.0.1:<disposable-port>/<disposable-database>'
   ```

   Use a separately migrated disposable PostgreSQL database with illustrative
   Bulletin accounts for browser acceptance. Provision the role described
   below first. Without this variable, sessions and scenario drafts work;
   account search reports dependency-unavailable.

6. Start the private control server.

   ```powershell
   uv run --project workers --frozen quakestrike-alert-testing
   ```

7. Open [the loopback tool](http://127.0.0.1:4341/).

The server binds only to `127.0.0.1:4341` and serves the built app. Rebuild the
private app after UI edits. `--port` changes the loopback port;
`--static-directory` selects another build directory. The server requires an
explicit `ALERT_TEST_REDIS_URL` and never reads root `.env` itself.

## Restricted account connection

The PostgreSQL container mounts `database/initialization` at
`/opt/quakestrike`. Supply `ALERT_TEST_DB_PASSWORD` through that container's
managed environment. In the chosen disposable database container, run:

```sh
sh /opt/quakestrike/provision-roles.sh create-alert-testing
```

This explicit command creates or updates the `quakestrike_alert_testing`
login and grants SELECT only on the account columns used by the tool.
The reader refuses a login with broader application privileges. It never
falls back to worker, Backend, observer, or migration credentials.
Provisioning does not migrate the schema or create accounts. Keep test
fixture mutations and migration credentials in the disposable setup process.
Never supply those credentials to the control server or browser.

The control server uses a pool of two PostgreSQL connections and read-only
transactions. Connection, pool, and query waits each have two-second bounds.
Search text is parameterized, capped at 100 characters, and matched literally.
Account responses have at most 50 rows. Name and email search stays private;
the browser receives names and masked destinations, not complete destinations
or saved coordinates. SMS support remains unknown; the server makes no
provider request to determine support.

## Browser memory and ticket 58 acceptance

The user amended ticket 58 on 13 October 2026: unfinished inputs and tester
selection stay in browser memory only. Redis draft persistence, autosave,
revision checks, recovery storage, and unsaved-navigation guards are removed.
This amendment replaces the published ticket's Redis draft and reload-recovery
criteria. Session state still uses the existing Redis session contract.

Specifically, the amendment supersedes ticket 58's Redis draft saves,
reload recovery, failed-save navigation behavior, and draft-persistence API
checks. It also supersedes the parent specification's Save draft workflow
and ticket 59's Redis storage of unsubmitted preparation. Internal continuity,
independent workspaces, separate pages, restricted account reads, and session
ownership still apply. Submitted scenario storage and queueing remain ticket 61.

Separate Scenario, Testers, and History Astro pages share the Astro ClientRouter.
Internal navigation, Back, and Forward retain the tab's memory workspace.
Reloading, closing the tab, or leaving the tool may discard unfinished edits.
Separate tabs have independent inputs and selections. Session closure, expiry,
or replacement resets the workspace. No draft save request or synthetic record
is created by edits, tester selection, or internal navigation.

Scenario fields, presets, tester controls, table, numbered pagination, footer,
and mobile styles reuse the accepted prototype. Randomize replay, the prepared
replay diagram, public preview, and Simulate and Send remain unavailable.
Ticket 59 owns preparation, which will also remain in browser memory.
Ticket 61 owns scenario submission and queueing. This amendment does not
implement those later tickets. Simulate and Send is the future explicit
save/freeze boundary, rather than a draft save.

1. Start a disposable session.
2. Confirm that Testers initially shows five rows.
3. Select rows across searches, filters, and numbered pages.
4. Confirm that the header checkbox changes only visible rows.
5. Change search, filters, and page size; confirm page one opens.
6. Inspect independent settings, verification, and provisional eligibility.
7. Change Scenario inputs and the forecast preset.
8. Navigate between Scenario and Testers; confirm inputs and selections remain in memory.
9. Use Back and Forward; confirm the same tab's workspace remains intact.
10. Open another tab; confirm each tab has independent inputs and selections.
11. Reload the page; confirm unfinished inputs and selections reset.
12. Inspect desktop and mobile table, pagination, footer, calendar, and back navigation.
13. End the session; confirm a new session starts with an empty selection.

Browser acceptance remains the user's check. API tests do not prove visual
parity or browser history behavior on the user's devices.

## Manual acceptance steps

1. Confirm the inactive state and use keyboard navigation to reach Start Test.
2. Start Test and confirm the active state and deadline in Philippine time.
3. Open a second browser tab and confirm the same session and deadline.
4. Navigate between Scenario, Testers, and History and confirm the shared header.
5. Use End Test, confirm the dialog, and check closure and completed cleanup.
6. Start another session and confirm its new identity through the private API.
7. Stop the disposable Redis container and confirm dependency-unavailable, rather than inactive or successful cleanup.
8. Check the layout at desktop and mobile widths.

The API integration tests cover concurrent starts, repeated starts, forced
expiry, cleanup failure/retry, closure before deletion, recovery of a lost
cleanup lease, stale UUID rejection, origin checks, and unrelated-key
preservation. These cases require real disposable Redis. The browser does not
offer fake success, forced-expiry, or failure-injection controls.

After acceptance, press Ctrl+C in the server terminal. Remove the disposable
container and process-scoped setting:

```powershell
docker stop quakestrike-alert-testing-preview
Remove-Item Env:ALERT_TEST_REDIS_URL
```

## Tailscale boundary

A configured `--origin https://<machine>.<tailnet>.ts.net` accepts that exact
Host and browser Origin while preserving the loopback bind. Authorized
Tailscale Serve configuration must forward that Host to the control server.
Use Serve only; Funnel would expose controls publicly and is prohibited.
Tailnet policy admits test operators; Bulletin and Console identity do not.
No Serve, Funnel, Traefik, Cloudflare, account, or target-environment changes
are performed by the launch command. Target-environment activation remains
an explicit operator action under existing runtime gates.

## Contributor verification

Run the exact disposable integration procedure in `CONTRIBUTING.md`:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Confirm that integration cases execute. Host pytest without the test URLs
skips integration cases; those skips are not verification. Never supply a
development or production database URL to these fixtures.

Affected checks also include the worker suite and Ruff, private Astro check
and build, Bulletin check/build and affected tests, Backend unit tests and
typecheck, and Git whitespace checks.

## Lifecycle and recovery

One Redis control hash coordinates one shared active session. Redis time
determines the fixed four-hour deadline; repeated starts do not extend it.
End requires the owning UUID and closes access before deleting children.
Expiry closes access independently of physical cleanup.

Cleanup scans only the owning UUID's tool prefix, in at most ten scan batches
per pass. The server advances pending cleanup every five seconds. Failed
cleanup keeps the session closed and exposes Retry cleanup. A ten-second
lease recovers a lost cleanup process; a token fences stale completions.
Start refuses a closed session whose cleanup has not completed.

The control tombstone contains only bounded lifecycle metadata. It expires
24 hours after the original deadline, without extending retention on polling
or retry. Future business records must expire at the original deadline and
enforce the atomic active-session gate. No provider-call coordination is
implemented or needed until a later ticket adds a consumer.

## Ticket 57 review record â€” 13 October 2026

Starting HEAD: `46356db3fef9b0a17c03d3525366bce43c6159da`.
The implementation uses `main` in
`C:/Projects/quakestrikeph/redo/quakestrikeph`. The initial handoff left changes
uncommitted for review. The user subsequently authorized a local commit.
No worktree, implementation branch, push, merge, ticket closure, or deployment
was performed.

The changed areas are:

- `workers/src/quakestrike/alert_testing/`: private HTTP mapping, Application
  workflows, Domain session values, Redis coordination, and explicit runtime
  wiring. Existing production worker implementations remain unchanged.
- `apps/quakestrikeph-alert-testing/`: separate Astro pages, the accepted
  prototype's sidebar/header/session/dialog presentation, and real private
  HTTP actions. Prototype simulation actions are excluded.
- `packages/ui/`: eight existing controls, their existing mobile hook, theme,
  and mobile-sidebar CSS. Bulletin source paths become compatible re-exports.
  An exact comparison against starting HEAD confirmed unchanged control
  implementations, apart from internal import paths.
- Bulletin package/lockfile, Dockerfile, and local Compose mount: shared UI
  packaging. This adds no private-tool route to the public application.
- `packages/contracts/alert-testing/`: private version-1 response type and
  HTTP contract; `workers/pyproject.toml` and lockfile: explicit Redis dependency
  and isolated CLI entry point. Redis remains at the already locked 6.4.0.
- Nine private HTTP integration cases and ten origin-validation unit cases.
- ADR 0050, architecture source map, glossary, and this operations guide.

Verification performed:

| Command/check | Result |
| --- | --- |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests/unit` | 407 passed, 11 platform skips. |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests` | 416 passed, 328 skipped. All integration cases skipped without test URLs; this is not Redis verification. |
| New integration file with `--collect-only -q` | Nine cases collected successfully. |
| Exact Compose integration procedure above | 315 passed, two expected real-model skips. All nine private session workflow cases executed and passed. |
| Private session regression file through disposable Compose | Nine passed, including a synchronized connection burst. |
| Private origin unit tests through disposable Compose | Ten passed. |
| Documented `prediction-smoke-runner` command with `-k test_real_seis -s` | One passed, one failed, 24 deselected. The persisted-forecast check passed; the existing replica benchmark failed its 30-second worker readiness deadline. No tests skipped. |
| Bulletin Docker image build | Passed with the shared UI package included; existing hints and large-chunk warning remain. |
| `uv run --project workers ruff check workers database` | Passed. |
| `uv run --project workers ruff format --check workers database` | Passed, 206 files. |
| Private Astro `check` and `build` | Passed, zero diagnostics; three static pages. |
| Bulletin Astro `check` and `build` | Passed; zero errors/warnings, 11 existing hints, existing large-chunk build warning. |
| Bulletin identity, SMS enrollment, location edit, event-results, and forecast-replay scripts | Passed. |
| Backend TypeScript build and four existing unit files via `node --test` | 29 passed. `npm` is absent from this shell; equivalent build/test commands used pnpm and Node. |
| `pnpm --dir apps/backend-api run typecheck` | Passed. |
| `git diff --check` and `git diff --cached --check` | Passed. |
| Shared control provenance comparison | Eight controls and mobile hook match starting HEAD, with import-path changes only. |

Docker was unavailable during the initial handoff. The original error was:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

The initial Windows worker invocation emitted a WMI resource exception but
continued to the passing unit summary. The later full host suite also passed
its executable cases. Existing platform skips cover unavailable symlink
creation and Linux-only provider deadlines. Bulletin's existing
`openapi-typescript@7.13.0` peer constraint requests TypeScript 5, while the
repository pins TypeScript 6.0.2; its checks and build passed without changing
those versions.

Docker became available before the authorized commit. The integration run
verified Redis concurrency, fixed expiry, closure before deletion, cleanup
failure/recovery, stale ownership, and isolation. Its first run exposed an
intermittent connection reset during concurrent starts. A synchronized burst
reproduced the failure while acceptance paused briefly. Setting the private
server's connection backlog to 16 fixed the regression; handler concurrency
remains bounded at 16. The full integration rerun passed.

The separate real-model runner mounted the approved local bundle read-only.
Its forecast check passed. The replica benchmark reported
`Prediction Worker replicas did not become ready.` at its existing 30-second
deadline. That benchmark remains failed; production prediction code and its
timeout were not changed for this session-control ticket.

Browser inspection established presentation and dependency-unavailable
behavior during the initial Redis outage; the manual
Start/End, active sidebar, and confirmation-dialog checks remain for the user.

No specification deviation is intended. The prototype's simulated queue,
provider activity, and completion buttons are excluded because issue 57 adds
only real session controls. Text identifies later-ticket features as
unavailable. Tailscale Serve admission and target activation remain explicit
operator actions. No real SMS/email submission or production data write occurs
in this slice.

## Ticket 58 implementation record — 13 October 2026

Source branch: `codex/alert-testing-tester-drafts`.
Starting commit: `6988320d65d0277f569305c715f13c9b657e3ade`.
Implementation changes remain uncommitted for review.

The final slice implements restricted account search, independent channel
settings and provisional eligibility, real status/onboarding labels, and
selection across filters and pagination. Separate Scenario and Testers React
components reuse the prototype markup, calendar, form controls, table, footer,
and responsive stylesheet. Shared controls move to `packages/ui`, with
Bulletin re-exports retaining its import paths. The accepted stylesheet also
retains preparation, replay, History, and Results rules for later tickets.

Astro ClientRouter preserves the tab's memory inputs and selected account
IDs during internal navigation. There is no draft HTTP route, Redis draft,
autosave coordinator, revision handling, recovery storage, or navigation guard.
The user amendment above intentionally supersedes older published persistence
criteria. Ticket 59 preparation and ticket 61 submission remain unimplemented.
No target activation, Tailscale Serve, account mutation, queue publication,
provider credentials, or actual provider submission was performed.

| Check | Result |
| --- | --- |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests` | 424 passed, 330 skipped. Host skips comprise 319 integration cases and 11 existing platform cases. |
| Exact isolated Compose integration procedure in CONTRIBUTING.md | 317 passed, two expected real-model skips. The integration cases executed against disposable PostgreSQL and Redis. |
| Documented `prediction-smoke-runner` command with `-k test_real_seis -s` | Both real-model cases passed; 24 deselected, none skipped. The known forecast and replica benchmark both succeeded. |
| `uv run --project workers ruff check workers database` | Passed. |
| `uv run --project workers ruff format --check workers database` | Passed; 212 files already formatted. |
| `pnpm --dir apps/quakestrikeph-alert-testing check` and `build` | Passed; no errors or warnings, four Select deprecation hints. |
| `pnpm --dir apps/quakestrikeph-alert-testing test` | Seven session request coordinator cases passed. |
| `pnpm --dir apps/quakestrikeph-bulletin check` and `build` | Passed; no check errors or warnings, seven existing hints. Build reports the large-chunk warning. |
| `create-alert-testing` in the disposable PostgreSQL container, twice | Both calls returned ready; provisioning is repeatable. |
| `git diff --check` and `git diff --cached --check` | Passed; no changes staged. |

The API checks exercise literal bounded search, pagination, selected identities,
masked destinations, returned status and onboarding, independent eligibility,
denied account writes, denied unrelated reads, broad-login refusal, inactive
and expired ownership, replacement sessions, closure during account reads,
absence of Redis child records and production jobs, and removed draft routes.
The pure eligibility tests cover magnitude equality, account state, incomplete
onboarding, nearby rejection, invalid event input, channel independence, and
unknown SMS support. Production eligibility code remains unchanged.

Desktop/mobile presentation, internal Back/Forward continuity, independent
tabs, and reload discard still require the user's manual acceptance steps
above. The automated results do not establish that browser acceptance.
Use the documented disposable setup and loopback launch commands; configuring
a runtime or database URL does not authorize target activation.

### P3 Standards correction — 13 October 2026

Account-load failure now replaces the table and pagination with the incumbent
shadcn Empty composition, a Lucide CircleX icon, and Retry accounts. The error
composition stays visible during retry and clears only after a successful
account response. Selected IDs remain in the browser workspace throughout.
Exceeding the selection limit now uses the shared error toast with a stable
ID, rather than changing the section's account-load state. Repeated limit
failures update the same toast. The existing prototype toast placement applies.

Empty and toast controls move unchanged to `packages/ui`, with Bulletin
re-exports preserving its callers. The shared package uses the Bulletin's
existing Base UI 1.8.0 dependency. Browser-memory behavior, separate pages,
private server behavior, and session request protections remain unchanged.

Private app and Bulletin checks/builds passed again. The private app's seven
session request coordinator tests passed. Whitespace checks passed. The checks
retain the four private-app and seven Bulletin hints; Bulletin still reports
its large-chunk build warning. No worker or integration rerun was needed for
this UI correction. Manual error-state acceptance remains unverified.

For manual acceptance, block `/api/test/testers` after selecting accounts.
Change the search and confirm the dedicated error composition replaces rows.
Unblock requests and use Retry accounts. Confirm the selected IDs remain
selected after the accounts return. If enough accounts are available, exceed
500 selections and confirm one error toast appears without disabling rows.

## Ticket 59 implementation record — 13 October 2026

Source branch: `codex/alert-testing-scenario-preparation`.
Starting commit: `6b6199053e8d81c5eafd32e0653c504f1a9a62f5`.
PR [66](https://github.com/ochlzo/quakestrikeph/pull/66) remained open when
implementation began. This branch depends on its ticket 58 implementation.
Ticket 59 changes remain uncommitted for the coordinating session's review.

The Scenario page preserves the accepted prototype controls and styles.
Prepare scenario validates edited values and generates the exact observations
shown in the review diagram. Randomize replay changes replay settings and
requests fresh positions, including when visible settings repeat.
Field errors appear beside their controls. Preparation failures also use the
existing action toast. Public preview and Simulate and Send remain unavailable.

The isolated Domain modules validate values and generate frozen observations
from supplied time and randomness. Application checks session ownership before
and after generation. The private preparation endpoint returns event, forecast,
replay settings, and exact observation values without writing scenario records
or publishing commands. Browser memory freezes that response recursively.
Scenario edits invalidate preparation. Tester selection edits preserve it.
Request identities and workspace revisions reject older responses.
Closure, expiry, and replacement clear the browser workspace.

The forecast covers exactly 24 elapsed hours. Past anchors generate successors
through preparation time or forecast end, whichever occurs first.
Future anchors retain future timestamps within the same forecast window.
Ticket 61 must validate an unexpired forecast before submission and preserve
the reviewed observations unchanged.

The geometry validation adds an upper radius bound below Earth's maximum
great-circle distance, approximately 20,015.11 km. Larger radii cannot have
outside observations. Depth is bounded to 0–700 km; replay spread is 0–100
percent. These private fixture bounds do not change production forecasts.
Optional quantiles retain production's finite, ordered, all-or-none rule.

| Check | Result |
| --- | --- |
| Worker pytest command in CONTRIBUTING.md | 487 passed, 344 skipped. Host skips include 333 integration cases and 11 existing platform cases. |
| Exact isolated Compose integration procedure | 331 passed, two expected real-model skips. All 14 preparation API cases executed against disposable Redis. |
| Final preparation API rerun after adding observation location descriptions | 14 passed against disposable Redis. |
| Documented `prediction-smoke-runner` command with `-k test_real_seis -s` | Both model cases passed; 24 deselected, none skipped. The known forecast and replica benchmark succeeded. |
| `uv run --project workers ruff check workers database` | Passed. |
| `uv run --project workers ruff format --check workers database` | Passed; 217 files formatted. |
| Private app `check` and `build` | Passed; zero errors or warnings, four existing Select deprecation hints. |
| Private app `test` | 19 passed, including 12 browser-memory cases. |
| `git diff --check` and `git diff --cached --check` | Passed; nothing staged. |

The tests cover field errors, optional quantiles, geometry near poles and the
date line, exact spillover counts, unique identities, valid depths and
magnitudes, location descriptions, ordered timestamps, and edited event clocks.
API checks cover private request protections, bounded bodies, active ownership,
closure during generation, replacement, expiry, and absence of scenario records
or queue publication. Browser-memory tests cover retained immutable values,
input invalidation, repeated settings, older failures, closure, deadlines, and
independent tabs.

A temporary local server used only a separate disposable Redis container.
Desktop and 390px mobile inspection showed the prepared diagram and accepted
responsive layout. The server and preview container were stopped afterward.
This inspection does not establish the user's manual browser acceptance.
No account connection, provider call, target-server operation, production
activation, commit, push, or pull request occurred for ticket 59.

### Ticket 59 manual acceptance

Use the disposable setup above. Complete these checks on desktop and mobile.

1. Start Test and confirm the default event time is approximately one hour ago in Philippine time.
2. Open the calendar and change the event date and time.
3. Use Done and Escape to check calendar dismissal and keyboard focus.
4. Select each forecast preset and edit individual values.
5. Enter zero radius, unordered probabilities, and partial quantiles, then select Prepare scenario.
6. Confirm field errors identify each problem and the optional estimates expand when invalid.
7. Correct the inputs and select Prepare scenario.
8. Confirm the diagram contains inside observations, requested spillover, and distant background observations.
9. Select Randomize replay repeatedly and confirm the settings and observation positions change.
10. Navigate to Testers and return through internal links, Back, and Forward.
11. Confirm the prepared diagram retains its exact positions through navigation and tester selection changes.
12. Edit one scenario value and confirm the diagram clears until preparation succeeds again.
13. Delay the preparation response using a browser debugging proxy or request interception tool.
14. While that response waits, edit one scenario value and then release the response.
15. Confirm the old response does not restore the diagram or replace the edited value.
16. Repeat the delayed-response check while ending or replacing the session.
17. Confirm the workspace clears and the old response cannot restore preparation.
18. Open a second tab and confirm its draft and preparation remain independent.
19. Reload the private page and confirm the unfinished workspace may reset.
20. Confirm public preview and Simulate and Send remain unavailable.
