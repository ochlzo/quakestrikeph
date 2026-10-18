# Operate private alert testing

Use the private tool to prepare synthetic forecasts and send approved tests to selected Bulletin accounts.
Use [ordinary alert runtime](alert-runtime.md) for automatic delivery to the full eligible roster.

| Task | Section |
| --- | --- |
| Use an already-configured private tool | [Run a test session](#run-a-test-session) |
| Preview the private UI locally | [Disposable local setup](#local-browser-acceptance-with-disposable-redis) |
| Set up the VPS services | [Services and configuration](#services-and-configuration) |
| Build and activate a tested release | [Private activation](#build-and-activate-after-separate-authorization) |
| End testing, disable ingress, or recover cleanup | [Deactivation and recovery](#deactivation-cleanup-recovery-and-rollback) |
| Run automated fake-provider checks | [Disposable verification](#repeatable-disposable-verification) |
| Inspect public forecast behavior locally | [Public browser fixture](#public-forecast-browser-fixture) |
| Diagnose failures | [Troubleshooting](#troubleshooting) |

**VPS environment:** Bash in `/srv/quakestrikeph` on `quakestrike-vps.tailf8b2fd.ts.net`.
**Local environment:** PowerShell from the repository root.
Setup commands do not authorize production activation or real SMS/email sends.

## Run a test session

**Prerequisites:** An authorized operator device, configured private services, approved recipients, and an explicit send allowance.
The tool uses one shared session with a fixed four-hour deadline. Separate tabs keep independent workspaces.

1. Open <https://quakestrike-vps.tailf8b2fd.ts.net:8443> from a permitted tailnet device.
2. Select **Start Test**.
3. Check the session deadline shown in Philippine time.
4. Open **Testers** and select the approved accounts.
5. Check each selected account's independent email and SMS eligibility.
6. Open **Scenario** and enter the earthquake, forecast, and replay values.
7. Prepare the scenario and inspect the exact observations in the review diagram.
8. Open **Preview forecast** to inspect the public page before sending.
9. If the reviewed scenario and recipients match the allowance, select **Simulate and Send**.
10. Inspect separate channel outcomes in **Results**.
11. Use **History** to reopen earlier scenarios and forecast links.
12. Select **End Test** when finished.
13. Confirm public links close and `closure_phase=complete` before stopping services.

**Accepted** means the provider accepted submission. **Delivered** means delivery evidence was recorded.
Neither a fake-provider result nor a healthy container proves handset or inbox receipt.
If submission is uncertain, retry the same reviewed request and tester selection. Do not create a replacement send.

### Drafts and previews

Inputs, tester selections, and exact prepared replay autosave to the private Redis workspace.
Only the workspace UUID enters browser sessionStorage. Browser storage contains no input values or tester IDs.
Wait for saves before reloading. Failed restoration blocks edits until Retry succeeds; failed saves retain local edits.

Autosave creates no delivery job, queue command, or History entry.
Public preview becomes available after signed preparation persistence succeeds.
Editing scenario values invalidates preparation; changing tester selection preserves the prepared observations.
New scenario creates a fresh preparation while retaining tester selection.

Public links use `/forecasts/{eventId}?test=true` and remain readable only while the owning session is active.
Each preparation has an immutable preview. If a submitted scenario also exists, public reads prefer that scenario.
All workspace, preview, job, and delivery keys expire at the original deadline.

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

6. Generate a preparation key for this disposable session.

   ```powershell
   $env:ALERT_TEST_PREPARATION_KEY = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
   ```

7. Start the private control server.

   ```powershell
   uv run --project workers --frozen quakestrike-alert-testing
   ```

8. Open [the loopback tool](http://127.0.0.1:4341/).

The server binds only to `127.0.0.1:4341` and serves the built app. Rebuild the
private app after UI edits. `--port` changes the loopback port;
`--static-directory` selects another build directory. The server requires an
explicit `ALERT_TEST_REDIS_URL` and never reads root `.env` itself.

Keep the preparation key stable across compatible control restarts. Changing the key invalidates retained signed preparations.
The local control launch does not start a consumer. Use the automated fake-provider workflow for submission checks.
Real transport uses a separately enabled Linux consumer and approved credentials.

When finished, press Ctrl+C in the control terminal, then remove the disposable Redis and process settings:

```powershell
docker stop quakestrike-alert-testing-preview
Remove-Item Env:ALERT_TEST_REDIS_URL
Remove-Item Env:ALERT_TEST_PREPARATION_KEY
Remove-Item Env:ALERT_TEST_DATABASE_URL -ErrorAction SilentlyContinue
```

## Services and configuration

`apps/quakestrikeph-alert-testing/Dockerfile` builds the static Astro UI and
copies only its output into the tested Python worker image. Node stays in the
build stage. `infrastructure/compose.alert-testing.yml` defines four private
services. Normal deployment automation never includes this additional file.

| Service | Purpose and admission |
| --- | --- |
| `alert-test-control` | Python controls and static UI; `alert-testing` profile; no provider secrets. |
| `alert-test-relay` | Pinned incumbent Traefik image; namespace shared with Python; host `127.0.0.1:4341` maps to relay 4342. |
| `alert-test-redis` | Separate temporary Redis instance; either private profile; no host port, snapshots, or AOF. |
| `alert-test-consumer` | Worker image; `alert-testing-consumer` profile and explicit `ALERT_TEST_CONSUMER_ENABLED=true`. |

Python remains bound to namespace loopback 4341. The relay forwards to that
endpoint and preserves Host and Origin. Python retains exact admission checks,
including the port. Neither private service joins public ingress networks.
No public Traefik route, Cloudflare route, Docker socket, dashboard, access
log, proxy identity trust, or provider request from a control handler is added.
The relay makes the namespace-loopback service reachable through the host loopback mapping.

The relay health check probes its loopback ping. Control health reads the
session through the relay; an unreadable Redis dependency fails the probe.
Consumer health requires a live PID and bounded Redis connectivity.
It does not verify batch progress, account grants, or provider access.
Health checks never create sessions or establish actual message receipt.
Containers use bounded logs, memory limits, and restart policies.

Configure these values in the target's private managed environment, never Git:

| Setting | Required value or owner |
| --- | --- |
| `ALERT_TEST_IMAGE_TAG` | Full tested Git SHA for both private images; independent of ordinary worker enablement. |
| `ALERT_TEST_REDIS_URL` | Same explicit test instance for control, consumer, and Backend; packaged value `redis://alert-test-redis:6379/0`. |
| `ALERT_TEST_DATABASE_URL` | `postgresql+psycopg://quakestrike_alert_testing:<URL-encoded-password>@postgres:5432/<database>`; restricted account reads only. |
| `ALERT_TEST_ORIGIN` | Exactly `https://quakestrike-vps.tailf8b2fd.ts.net:8443`. |
| `ALERT_TEST_PUBLIC_BULLETIN_URL` | Approved public Bulletin origin; frozen on each submitted job. |
| `ALERT_TEST_PREPARATION_KEY` | Stable server-only key of at least 32 bytes; retain across compatible control restarts. |
| `ALERT_TEST_CONSUMER_ENABLED` | `false` until separately authorized activation. |
| `ALERT_TEST_IPROG_TOKEN` | Approved ordinary IPROG sender credential; consumer only. |
| `ALERT_TEST_BREVO_API_KEY`, `ALERT_TEST_BREVO_SENDER_EMAIL`, `ALERT_TEST_BREVO_SENDER_NAME` | Approved transactional sender/domain and credentials; consumer only. |
| `BREVO_CALLBACK_TOKEN` | Existing Backend authentication for `/api/v1/callbacks/brevo`; no new bypass. |

The Backend's normal Compose file passes the optional test Redis URL.
Without configuration, synthetic requests remain unavailable and ordinary
reads remain independent. Repeat Backend releases preserve the configured URL.
The private Redis shares only the private data network, never production queues.
Synthetic events, jobs, recipients, attempts, and history stay outside PostgreSQL.
Redis loss discards the test. Do not recreate uncertain submissions automatically.
Messages already submitted and provider-held records cannot be erased by cleanup.


## VPS prerequisites

Before activation, the operator must verify:

- The reviewed main release includes the required features and passed application checks.
- The VPS checkout is clean and both private images carry that exact tested SHA.
- PostgreSQL migrations and existing application health pass the [release checks](continuous-deployment.md#routine-release-sequence).
- The restricted `quakestrike_alert_testing` login has only the documented account column grants.
- Backend, control, and consumer select the same separate test Redis.
- Tailnet HTTPS certificates and Serve are available on the VPS.
- Tailnet policy permits only named authorized test operators to the VPS on TCP 8443.
- Broader existing grants and device-sharing rules do not admit unintended operators on 8443.
- PgAdmin's existing 443 listener still forwards to `http://127.0.0.1:5050`.
- Approved IPROG coverage, Brevo sender/domain, destinations, callback authentication, and budgets exist.
- The user separately authorized initial activation and any controlled real sends.

Bulletin account login and Console admission do not admit test operators.
Tailnet administration must review effective access; a new narrow rule alone
does not restrict an existing broad allow rule. Testers open public forecast
links without Tailscale. Do not expose private controls through Funnel.

Follow [database maintenance](database-maintenance.md) for passwords and private access.
After separately authorized role provisioning, run the existing
`create-alert-testing` command with `ALERT_TEST_DB_PASSWORD` supplied privately
to the provisioning process. Never pass an administrator or migration URL to
the private runtime. Do not recreate PostgreSQL merely to inject that password.
Use the host maintenance lock and existing grant procedures for target changes.

One concrete provisioning command, after separate authorization, is:

```bash
read -rsp 'Restricted testing login password: ' testDbPassword
sudo -n flock -w 120 --close /run/quakestrike-postgres-backup.lock docker compose --env-file .env -f infrastructure/compose.yml exec -T -e "ALERT_TEST_DB_PASSWORD=$testDbPassword" postgres sh /opt/quakestrike/provision-roles.sh create-alert-testing
unset testDbPassword
```

Run from `/srv/quakestrikeph` with the already-running PostgreSQL container.
This command neither recreates PostgreSQL nor runs migrations.
Store the matching URL-encoded password in the private account connection.

## Build and activate after separate authorization

These Bash commands run in `/srv/quakestrikeph` on the named VPS.
Set `ALERT_TEST_IMAGE_TAG` in the managed `.env` to the clean tested checkout's
full SHA first. Do not print resolved Compose configuration containing secrets.

```bash
cd /srv/quakestrikeph
test -z "$(git status --porcelain --untracked-files=all)"
releaseSha=$(git rev-parse HEAD)
```

Use existing tested `quakestrike-workers:$releaseSha` when available.
Verify its `org.opencontainers.image.revision` label equals `$releaseSha`.
If an image with that tag exists, never overwrite it. If absent, build it:

```bash
docker build --label "org.opencontainers.image.revision=$releaseSha" -t "quakestrike-workers:$releaseSha" -f workers/Dockerfile .
```

Apply the same absent-tag and revision checks to the private UI/control image:

```bash
docker build --build-arg "BASE_IMAGE_TAG=$releaseSha" --label "org.opencontainers.image.revision=$releaseSha" -t "quakestrike-alert-testing:$releaseSha" -f apps/quakestrikeph-alert-testing/Dockerfile .
```

Retain both compatible previous images and the protected previous environment.
Do not label an uncommitted local build as a tested Git release.
Local packaging checks use the disposable `ticket63-local` tag instead.

Define a scoped Compose helper, then validate configuration without printing secrets:

```bash
private_compose() {
  docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.alert-testing.yml --profile alert-testing --profile alert-testing-consumer "$@"
}
private_compose config --quiet
```

After existing PostgreSQL health is verified, start only the named private services.
`--no-deps` prevents these commands from recreating production dependencies.

```bash
private_compose up -d --wait --no-deps alert-test-redis alert-test-relay
private_compose up -d --wait --no-deps alert-test-control
```

Recreate the Backend through the established Backend rollout only after its
managed test Redis setting is configured. Preserve production service states
and existing sender/callback settings. No additional public control route exists.

Verify host loopback with the exact configured Host:

```bash
curl --fail --silent --show-error -H 'Host: quakestrike-vps.tailf8b2fd.ts.net:8443' http://127.0.0.1:4341/api/test/session
tailscale serve status --json
```

Record the existing 443 configuration privately before adding only 8443.
After admission and activation authorization are verified, run:

```bash
sudo tailscale serve --bg --https=8443 http://127.0.0.1:4341
tailscale serve status --json
```

Verify both listeners and test permitted and denied operator devices.
Verify pgAdmin still opens through 443. Open the private tool at
`https://quakestrike-vps.tailf8b2fd.ts.net:8443` from an admitted device.
Verify exact Host and Origin rejection, static pages, and session state.
Only after separate consumer authorization, set enablement to `true` and run:

```bash
private_compose up -d --wait --no-deps alert-test-consumer
```

The official [Serve CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve)
and [Serve access rules](https://tailscale.com/docs/features/tailscale-serve)
were checked on 14 October 2026. The CLI supports a specified HTTPS port,
background serving, status JSON, and scoped removal with the original flags.
Those documentation checks do not verify the VPS's installed version or access.

## Deactivation, cleanup recovery, and rollback

Before a routine main deployment, schema maintenance, or private image change,
end the shared test and confirm `closure_phase=complete`. Keep private services
deactivated throughout the normal application rollout. Private images do not
update automatically with the ordinary deployment script.

1. Select End Test through the private UI.
2. Confirm public links become invalid before cleanup completes.
3. Wait for authorized calls and session-owned deletion to complete.
4. If cleanup fails, restore Redis access and select Retry cleanup for the same session.
5. Confirm `closure_phase=complete` before stopping the control service.

The call grace period is at most 15 seconds. Failed cleanup stays closed.
Retry cannot extend retention or revive an expired scenario.
Keep the control service available while resolving cleanup failure.
If Redis remains unavailable, record cleanup as unverified rather than complete.
Do not flush Redis, remove another session's keys, or delete production queues.
Original child TTLs and the fixed tombstone deadline remain deletion safeguards.

Remove only the testing listener and stop only the private runtimes:

```bash
sudo tailscale serve --bg --https=8443 off
tailscale serve status --json
private_compose stop alert-test-consumer alert-test-control alert-test-relay
```

Compare 443 with the recorded configuration and verify pgAdmin remains usable.
Never use `tailscale serve reset`, global Compose `down`, or Funnel here.
After cleanup is verified and no test is active, the operator may also stop
`alert-test-redis`. Stopping that nonpersistent instance discards its tombstone.
Configure consumer enablement back to `false` before removing the test environment.

For rollback, keep private ingress disabled and the consumer stopped.
If the database revision is unchanged and verified, restore the compatible
previous private image tag and preparation key in the managed environment.
Recreate relay and control together because they share a network namespace.
Verify health, loopback admission, and a fresh session before authorized reactivation.
If the schema revision changed or is unverified, retain the target checkout
and repair forward. Never downgrade or restore the live database.
Stopping a container does not recall provider submissions or prove cleanup.

## Repeatable disposable verification

Use only `quakestrike-data-ingestion-test`. Worker and Backend fixtures migrate
and truncate their database and share the control key; run them serially.
The following sequence expands the required contributor procedure before teardown:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml exec -T postgres-test sh /opt/quakestrike/provision-roles.sh create-backend
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile backend run --build --rm backend-test-runner
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile alert-testing-workflow up --build -d --wait alert-testing-backend-fixture
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm -e TEST_ALERT_BACKEND_URL=http://alert-testing-backend-fixture:3000 test-runner pytest --config-file workers/pyproject.toml workers/tests/release/test_alert_testing_workflow.py -q
```

The release cases enter through private HTTP, use the real session Stream,
restricted PostgreSQL account reads, selected account fixtures, and fake providers.
The actual Backend HTTP app authenticates early email callbacks and reads the
Python-produced scenario. SMS polls use injected fake outcomes; existing provider
tests cover authenticated requests.
The fixture has no live provider adapter or account mutation routes.
Closure and expiry reject public detail/replay before physical cleanup.
Late callbacks acknowledge without revival; unrelated queues and accounts survive.

When the approved model bundle exists, run its separate documented check:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile prediction-smoke run --build --rm prediction-smoke-runner pytest --config-file workers/pyproject.toml workers/tests/integration/test_prediction_worker.py -k test_real_seis -s
```

Check packaging using local tags, without secrets or production runtime configuration:

```powershell
uv run --project workers python infrastructure/scripts/check-alert-testing-compose.py
docker build -t quakestrike-workers:ticket63-local -f workers/Dockerfile .
docker build --build-arg BASE_IMAGE_TAG=ticket63-local -t quakestrike-alert-testing:ticket63-local -f apps/quakestrikeph-alert-testing/Dockerfile .
uv run --project workers python infrastructure/scripts/smoke-alert-testing-package.py ticket63-local
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile alert-testing-workflow down -v
```

The smoke command refuses occupied host port 4341. It uses only disposable
services and separate Redis, with provider credentials empty and consumer
egress isolated. It verifies real relay/control/consumer health, pages/assets,
exact admission, and Start/End without any job submission. It removes its four
temporary private containers afterward. Final teardown removes only the test project.
The smoke command also removes its two empty private networks.
Use the isolated test configuration for these checks.
CI adds the workflow and packaging checks as prerequisites to ordinary deployment,
without adding private services to deployment automation.

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

## Public forecast browser fixture

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

These steps verify local fixture behavior only. Check public links without Tailscale after an authorized deployment.
They do not verify provider delivery.

## Manual acceptance

Run desktop and mobile checks in a fake-provider environment first. Real sends require a separate allowance.

1. Check keyboard focus, calendar dismissal, dialogs, tables, and mobile Results.
2. Compare the shared deadline across two tabs.
3. Select testers across searches and pages.
4. Confirm the header checkbox affects only visible rows.
5. Change filters or page size and confirm pagination returns to page one.
6. Inspect independent channel settings, verification, and provisional eligibility.
7. Prepare inside, spillover, and background observations.
8. Check map clicks, pin dragging, place search, manual coordinates, and randomization against the same draft.
9. Confirm device location is requested only after **Use my location**.
10. Navigate with internal links, Back, and Forward.
11. Confirm each tab retains its independent workspace.
12. Wait for autosave and reload to confirm workspace recovery.
13. Edit scenario values while a preparation response is delayed.
14. Confirm the stale response cannot replace the edited scenario.
15. Confirm selection-only edits preserve the exact reviewed replay.
16. Submit the reviewed scenario and inspect queued, skipped, accepted, delivered, failed, and unknown outcomes.
17. Retry an unchanged uncertain submission and confirm no duplicate logical provider calls.
18. Change fixture account settings after queueing and confirm consumption respects the changes.
19. Open the forecast without Tailscale and compare the normal layout, wording, and controls.
20. Play, seek, reload, and retry replay while retaining `test=true` and exact saved observations.
21. Confirm **PHIVOLCS** opens the real index and **Back to earthquakes** opens `/` without test mode.
22. Confirm synthetic events do not appear in ordinary lists or reads without `test=true`.
23. Create another scenario and confirm earlier session links remain readable.
24. End the session during a fake provider call.
25. Confirm all operators see closure before waiting and deletion finish.
26. Exercise cleanup failure and **Retry cleanup** while public access remains closed.
27. Confirm expiry or replacement clears private state and invalidates already-open public pages.
28. Confirm dependency failure reports unavailable rather than inactive or successful cleanup.

Initial History, Results, and Testers failures use persistent Retry panels.
A missing Results scenario offers History. Later read failures retain loaded data and show short Retry feedback.
Numeric fields show their validation explanation beside the control.

## Troubleshooting

| Symptom | Check or action |
| --- | --- |
| Private page is unreachable | Check tailnet admission, Serve 8443, relay/control health, and exact Host/Origin configuration. |
| pgAdmin stops working after activation | Compare Serve 443 with its recorded settings; preserve the independent listener. |
| Testers reports unavailable | Check the restricted account URL, grants, schema, and PostgreSQL health. |
| Reload cannot restore a draft | Restore test Redis access; use Retry before editing. |
| Save fails or conflicts | Retain local edits; restore connectivity. Do not overwrite another stored revision manually. |
| Public test link returns unavailable | Confirm Backend, control, and consumer use the same explicit test Redis. |
| Public test link is invalid | Check active session ownership, original deadline, and matching scenario identity. |
| Consumer refuses startup | Check `ALERT_TEST_CONSUMER_ENABLED=true`, explicit URLs, and restricted account grants. |
| Provider response is uncertain | Preserve the same event identity and selected accounts; do not create another send. |
| Cleanup fails | Keep the control available, restore Redis, and retry cleanup for the owning session. |
| Map worker is empty or place search returns 404 | Rebuild the private image; run its map-asset verification and package smoke. |

Inspect private service status and bounded logs after defining `private_compose` in the activation section:

```bash
private_compose ps
private_compose logs --tail 100 alert-test-control alert-test-relay alert-test-consumer
```

Health checks verify process/dependency readiness. They do not establish provider access or batch progress.
Never flush Redis, reset attempts, recreate uncertain sends, or use production queues to repair a test.

## Runtime reference

### Session lifecycle and cleanup

Redis time sets the original four-hour deadline. Repeated Start requests do not extend that deadline.
End requires the owning UUID and closes public reads, creation, and reservations before deletion.
Expiry closes access even if physical cleanup fails.

Cleanup scans only the owning session prefix, in at most ten scan batches per pass.
The control advances pending cleanup every five seconds. A ten-second lease permits recovery after process loss.
A token rejects stale cleanup completion. New starts wait until prior cleanup completes.
The call grace period is at most 15 seconds; it is not a live count of provider calls.

The control tombstone retains bounded lifecycle metadata until 24 hours after the original deadline.
Polling and retries never extend child retention or the tombstone deadline.
Redis loss discards the test. Submitted messages and provider-held records cannot be recalled by End Test.

### Scenario values and public reads

The forecast spans exactly 24 elapsed hours. Past anchors generate observations through preparation time or forecast end, whichever comes first.
Future anchors retain future timestamps within that window.
Depth is 0–700 km; replay spread is 0–100 percent.
The radius must remain below Earth's maximum great-circle distance, approximately 20,015.11 km, so outside observations can exist.
Optional quantiles must be finite, ordered, and either all present or all absent.

Named places use the local attributed GeoNames index. Remote pins fall back to coordinate descriptions.
The location picker contains no account preference or nearby-distance controls.
Map and search failures use toaster feedback; map startup shows a centered spinner.

Synthetic JSON and HTML use `no-store`. Open pages check validity every 15 seconds, on focus/visibility restoration, and at expiry.
Invalidation clears replay data and reloads the normal invalid-link or unavailable state.
Back/forward cache restoration also reloads. Without JavaScript, validity checks occur on page requests; open-page polling and replay need JavaScript.

### Submission and delivery evidence

Simulate and Send validates the signed preparation, session ownership, original deadline, forecast expiry, and selected account IDs.
The event UUID identifies the logical submission. An unchanged retry reuses that identity; changed values or selection cannot reuse it.
Control handlers never contact providers. The separate consumer reads only selected accounts and rechecks channel eligibility before transport.
Synthetic records stay in separate Redis and never become PostgreSQL events, jobs, attempts, or history.
Real provider adapters require the Linux main-thread context for their 12-second elapsed deadline.

Brevo authenticates callbacks before test/ordinary routing. Test tags use `quakestrike-attempt:test:<session>:<event>:<attempt>`.
Early callbacks use a pre-call attempt index. Duplicate or older evidence cannot regress delivered outcomes.
Reference collisions report conflict. Closed, expired, replaced, or deleted sessions acknowledge late authenticated callbacks without reviving records.
Redis failure or missing active correlation returns HTTP 429 with `Retry-After: 60`.
Ordinary callbacks retain their normal PostgreSQL path.

The consumer polls one known SMS reference per pass. Each claim delays its next poll by 60 seconds, including interrupted or unknown results.
Polling never submits another message. Timestamp-free results do not invent a provider event time.
Unknown submissions without references stay unknown. Forecast expiry is checked again immediately before transport authorization.

### Privacy and diagnostics

Results show masked destinations and bounded conflict notes. Full references, message content, credentials, and complete destinations remain private.
Logs retain allowlisted operations, categories, and event/job/attempt UUIDs; they exclude raw exceptions and provider payloads.
Dependency and polling diagnostics report one warning per outage and one verified recovery event.
Repeated failures stay quiet until a usable response proves recovery; ordinary unknown results do not prove recovery.
Suppression resets when the consumer restarts.

### Static assets and contracts

The private UI is static Astro output served by Python. Node remains in the Docker build stage.
Build checks require a nonempty MapLibre worker and the bundled places index.
Python explicitly allows `/assets/accounts/philippine-places.json`; it rejects unrelated paths and traversal.
Package smoke requests the places JSON through the relay.

The [private HTTP and record contracts](../../packages/contracts/alert-testing/README.md) define headers, ownership, responses, and projection rules.

## Recorded verification and remaining limits

The following results are historical observations from **14 October 2026**, not new checks of this checkout or VPS.

| Check | Recorded result |
| --- | --- |
| Release packaging baseline | `7ade071ccb0288732710fa489a75bf35136c4264`; implementation review reported no findings. |
| Isolated worker integration before autosave amendment | 384 passed; two expected model skips. |
| Isolated Backend integration | Seven passed; no skips. |
| Complete private-to-Backend workflow | Two passed; no skips; closure and expiry exercised. |
| Separate approved-model checks | Two passed; no skips or retry attempts. |
| Actual packaged smoke | Four private services healthy; pages/assets, exact admission, Start/End; no provider calls or jobs. |
| Autosave amendment integration | 386 passed; two artifact-dependent skips. |
| Final private UI checks after map correction | 46 tests passed; check/build passed; six existing deprecation hints and bundle advisory. |
| Final host worker suite after map correction | 506 passed; 401 expected integration/platform skips. |
| Map correction target verification | Remained pending until the reviewed private image rollout. |

An earlier model replica check failed its 30-second readiness deadline; later separate model checks passed.
An earlier local-isolation assertion failed against a concurrent configuration edit.
The later explicit local API defaults and `CI=true` adjustment passed that checker.
The packaged relay initially lacked `--ping=true`; its corrected container smoke passed.
These are historical corrections, not unresolved failures inferred for this release.

Host skips without test URLs do not establish integration verification.
Target admission, installed Serve behavior, sender setup, real receipt, and user desktop/mobile acceptance require environment-specific checks.
Fake-provider evidence does not authorize activation or prove real receipt.
