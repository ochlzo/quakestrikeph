# Run the application locally

Run PowerShell commands from the repository root. Local Bulletin and workers share PostgreSQL and Redis in the `infrastructure` Compose project.

| Your task | Start here |
| --- | --- |
| Start Bulletin after setup | [Daily Bulletin commands](#daily-bulletin-commands) |
| Set up Bulletin and the Backend | [Local web setup](#9-add-the-local-backend-and-bulletin) |
| Set up the full worker pipeline | [Worker prerequisites](#1-gather-the-prerequisites) |
| Start initialized workers | [Start consumers](#7-start-consumers-then-enable-beat) |
| Check predictions or recover queued work | [Prediction operations](#prediction-worker-operations) |
| Remove local test accounts | [Remove local test accounts](#remove-local-test-accounts) |
| Test with the actual model | [Real-model checks](#real-model-integration-checks) |
| Stop local workers | [Stop local services](#8-stop-local-services) |

Container startup does not initialize an empty database. Complete the matching setup before using daily commands.

## Daily Bulletin commands

**Prerequisite:** Complete [local web setup](#9-add-the-local-backend-and-bulletin) once.

1. Start the data and web services.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --wait postgres redis backend-api bulletin
```

2. Open <http://127.0.0.1:4321>.
3. If startup fails, inspect service status and recent logs.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml ps postgres redis backend-api bulletin
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml logs --tail 100 backend-api bulletin
```

4. When finished, stop only the web services.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml stop bulletin backend-api
```

PostgreSQL and Redis remain available to workers. Source edits appear through the Bulletin source mount; Backend edits require an image rebuild.

### Rebuild after code or dependency changes

For Backend changes, rebuild and replace only the Backend.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml build backend-api
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --wait --no-deps backend-api
```

For Bulletin dependency changes, rebuild the image before renewing its dependency volume.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml build bulletin
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --wait --no-deps --force-recreate -V bulletin
```

`-V` renews the Bulletin's anonymous dependency volume. These targeted commands preserve the shared database and Redis volumes.

## Remove local test accounts

This command deletes disposable accounts from the local development database.
It is not an account-removal product route. It also deletes the audit and
delivery evidence for the selected accounts, so never run it against a database
that holds real users.

**Prerequisite:** Start PostgreSQL and Redis. Set `CLERK_SECRET_KEY` and
`ACCOUNT_REDIS_URL` in the root `.env`.

1. Preview the five default addresses. This step deletes nothing.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.local.yml run --build --rm account-cleanup
```

2. Delete the default addresses.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.local.yml run --build --rm account-cleanup quakestrike delete-accounts --apply
```

3. Replace the default list with your own addresses. Separate addresses with commas.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.local.yml run --build --rm account-cleanup quakestrike delete-accounts --apply --emails "first@example.test,second@example.test"
```

The command deletes the `audit_logs`, `alert_delivery_attempts`, and
`alert_recipients` rows for each account. It then deletes the `users` row, the
matching Clerk users, and the Redis phone keys.
Redis cleanup includes the saved number and any pending verification number.
If a Clerk deletion fails, `clerk_users_failed` lists its email and Clerk user ID.

| Exit code | Meaning |
| --- | --- |
| `0` | The plan ran. A preview returns `0` and deletes nothing. |
| `1` | No supplied address matched a database row or a Clerk user. |
| `2` | The command refused to start, or a delete failed partway. |

The command runs with the migration login, because the application roles cannot
delete users. The `account-cleanup` service joins a separate egress network for
the Clerk API calls.

## First-time worker setup

Complete sections 1–6 before starting recurring workers.

## 1. Gather the prerequisites

Install Git, Docker Desktop (or Docker Engine with Compose v2), Python 3.12,
and [`uv`](https://docs.astral.sh/uv/). You also need two inputs kept
outside Git:

1. The approved `SEIS 1.0.1` model package, including its weight files. Ask the
   project maintainer for the reviewed package.
2. A preserved raw or enriched PHIVOLCS bootstrap snapshot. It must include
   source IDs and URLs, retrieval metadata, counts, and the required August
   25–31, 2026 lookback plus available September records. A cleaned CSV alone
   is not a valid bootstrap input. Ask the maintainer for the preserved
   snapshot or collect a new one from PHIVOLCS with the project scraper.

The snapshot may be copied into the ignored `bootstrap-snapshots/` directory
for the import below.

## 2. Configure the local environment

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv python install 3.12
uv sync --project workers --frozen
```

Edit `.env` before continuing:

- Set distinct `POSTGRES_PASSWORD`, `MIGRATION_DB_PASSWORD`, and
  `WORKER_DB_PASSWORD`. Match the last two in `MIGRATION_DATABASE_URL` and
  `DATABASE_URL`, respectively. If this database already has a Docker volume,
  follow [the password change steps](database-maintenance.md#change-database-passwords-on-an-existing-volume)
  after editing `.env`.
- Set `WORKER_IMAGE_TAG` to the tested Git commit SHA. Keep the previous tested
  image tag available for rollback; do not prune it during enablement.
- Keep `DATABASE_URL` pointed at `postgres:5432` and `REDIS_URL` at
  `redis:6379`; these are private Compose service names.
- Set `PHIVOLCS_CATALOG_URL` to the official HTTPS catalog URL.
- Set `MAX_RESPONSE_BYTES` high enough for the current catalog while keeping a
  finite limit. The default is 20,000,000 bytes; oversized catalog responses
  fail the run.
- Set `MODEL_RELEASE_ID` to the ID in the reviewed model manifest.
- Set `MODEL_ARTIFACT_HOST_DIRECTORY` to the host directory where the
  packaged model will live. The default is the ignored `model-artifacts/`
  directory in this repository.
- Set `BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH` to the independently verified
  latest source time that your snapshot must cover.

Do not commit `.env`, model weights, or source data.

## 3. Package the model and prepare the snapshot

Replace the two example paths with the inputs you obtained in step 1:

```powershell
$sourcePackage = 'C:\path\to\reviewed-model-package'
$snapshotPath = 'C:\path\to\preserved-bootstrap-snapshot.json'
New-Item -ItemType Directory -Force bootstrap-snapshots | Out-Null
Copy-Item -LiteralPath $snapshotPath -Destination bootstrap-snapshots/input.json
uv run --project workers quakestrike package-model-release --source-package $sourcePackage
```

The package command verifies the selected release and artifact hashes. Do not
edit the collected snapshot.

## 4. Start PostgreSQL and Redis

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait postgres redis
& infrastructure/scripts/build-worker-image.ps1
& infrastructure/scripts/build-prediction-image.ps1
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create
```

The services stay on a private Docker network. PostgreSQL uses a persistent
Docker volume. The image command requires a clean checkout at the full SHA
configured in `.env` and refuses to replace an existing image tag. Keep the
previous tested image tag for rollback. The containers do not run migrations
or import history for you.

Database scripts now live in `database/initialization/`; migrations live in
`database/migrations/` and use `database/alembic.ini`. Worker images build from
the repository root. When adopting this layout, rebuild the worker images and
refresh PostgreSQL's bind mount through the Compose `up` command above. Stop
producers and consumers before recreating an existing PostgreSQL container.
The named database volume remains attached; do not remove it.

## 5. Initialize the database and model release

For an existing database, stop all work producers and consumers before these release steps.
If web services are running, stop Bulletin and Backend with [the daily web commands](#daily-bulletin-commands).
If alerts are active, follow [alert shutdown](alert-runtime.md#rollback-and-evidence-limits) before migrations.
Let in-flight predictions finish before stopping workers when possible:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile beat --profile prediction stop beat data-ingestor dispatcher prediction-worker
```

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike migrate
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh grant-worker
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike register-model-release
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike verify-model-release
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike reissue-legacy-predictions
```

Registration verifies the packaged model before storing its immutable release
reference. Role provisioning and grants are explicit, repeatable actions. The
init container uses the migration role; long-running workers use the worker
role, which can read model releases but cannot change the registry or schema.
PostgreSQL mounts the role-script directory so a checked-out script update is
visible before the explicit grant command runs.
On an existing local database, role provisioning transfers only the known
worker tables, enum types, and snapshot functions to the migration role.
This permits later migrations to replace administrator-owned legacy functions.
An exact registration repeat is safe.

### Legacy prediction reissue reference

`reissue-legacy-predictions` replaces eligible `SEIS 1.0` work with `SEIS 1.0.1` jobs from preserved input snapshots.
It closes eligible old work and audits the linked job and dispatch IDs. Reissue itself sends no alert.

| Existing job | Result |
| --- | --- |
| `pending` or `retry_wait` | Eligible for replacement. |
| `failed` with `unsupported_schema` or `release_mismatch` | Eligible for replacement. |
| Running job or active attempt | Refused; let work settle before rerunning. |
| Successful, cancelled, or unrelated failure | Skipped. |
| Matching replacement already exists | Reused; reruns are safe. |
| Conflicting replacement exists | Fails for investigation. |

Before starting Dispatcher or Prediction Worker, confirm `"status": "completed"` and inspect `reissued` and `reused` counts.
Each replacement cancels the old job with `reissued_for_release`.
The `prediction_backlog_reissued` audit links old and new job/dispatch IDs.

## 6. Import history and check readiness

The ignored snapshot directory is mounted into the one-off initialization
container and read-only into the runtime services:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike bootstrap --snapshot /app/bootstrap-snapshots/input.json --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
```

The last command exits with `0` and prints `"ready": true` when all gates
pass. It checks migrations, PostgreSQL and Redis, the model release and hashes,
the preserved source evidence, the completed backfill, and usable seven-day
history. A failed gate leaves Beat disabled; inspect its diagnostic, correct
the cause, and run the check again. The generated manifest and hash-named
source copy stay in ignored `bootstrap-snapshots/`.

If you later replace the PostgreSQL volume, the imported records disappear.
Starting the containers again will **not** reimport them. Keep the model
package and preserved snapshot. Archive the old
`bootstrap-snapshots/bootstrap-readiness.json` before repeating steps 4–6
against the fresh database: it names a run from the old database. A fresh
manifest gets a new run identity. You do not need to scrape again while the
snapshot remains valid and available.

## 7. Start consumers, then enable Beat

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait dispatcher
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait data-ingestor

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction up -d --wait prediction-worker

& infrastructure/scripts/enable-beat.ps1
```

The Beat enable command checks both consumer health states before starting it.
Compose also enforces both as healthy dependencies and the command checks again
after Beat becomes healthy, stopping it if a consumer failed during startup. Each process
also evaluates its read-only startup gates. Beat waits for the strictly next
UTC wall-clock boundary of `POLL_INTERVAL_SECONDS` (five minutes by default).
It does not poll on startup or replay missed boundaries. Beat has no automatic
restart policy; enable it explicitly again after a stack restart.

The Prediction Worker loads and verifies `SEIS 1.0.1` before consuming work. Model files remain on the read-only artifact mount.

The default is one healthy Prediction Worker container with one Celery child.
To run two identical replicas on the same prediction queue, scale the service:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction up -d --wait --scale prediction-worker=2 prediction-worker
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction ps prediction-worker
```

Set `--scale prediction-worker=1` to return to one replica. Each container has
its own health check for PostgreSQL, Redis, migrations, the selected model
release and artifact hashes, output schema, and local queue consumption. The
worker uses a 300-second soft limit and 360-second hard limit by default; set
`PREDICTION_SOFT_TIME_LIMIT_SECONDS` and
`PREDICTION_HARD_TIME_LIMIT_SECONDS` in `.env` only with soft < hard < the
900-second prediction processing lease. A hard limit terminates the stuck
child; durable lease recovery retries the same job and dispatch after expiry.
Watch memory use on the VPS before keeping additional replicas running.

### Prediction worker operations

Run these commands from the repository root with the release `.env`. Start one
replica, or set `--scale prediction-worker=2` for the measured scale-out option:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction up -d --wait --scale prediction-worker=1 prediction-worker
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction ps prediction-worker dispatcher
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml logs --since 10m --tail 100 prediction-worker dispatcher
```

`--wait` requires every started replica to be healthy. Each prediction health
check verifies PostgreSQL, Redis, migrations, the selected release and model
hashes, the output contract, and consumption of its local queue. Check both
replicas in `ps` after scaling. For memory on the deployment host, run
`docker stats` for the prediction containers and compare with the 512 MiB
per-container limit in `infrastructure/compose.release.yml`.

Stop all prediction replicas for maintenance without deleting PostgreSQL work:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction stop prediction-worker
```

Wait for in-flight predictions to finish before a planned stop when possible.
Stopping a worker during inference leaves its processing attempt leased until
expiry. The shared Dispatcher and database retain the job and dispatch IDs.
To resume and requeue eligible durable work, first restore healthy PostgreSQL,
Redis, Dispatcher, and the verified model bundle, then start the worker again:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait dispatcher
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction up -d --wait --scale prediction-worker=1 prediction-worker
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec postgres psql -U quakestrike -d quakestrike -c "SELECT p.job_id, p.status AS job_status, p.next_attempt_at, p.last_error_code, d.dispatch_id, d.status AS dispatch_status, d.next_dispatch_at, d.last_dispatched_at, f.forecast_id FROM prediction_jobs p JOIN job_dispatches d ON d.prediction_job_id = p.job_id LEFT JOIN forecasts f ON f.job_id = p.job_id ORDER BY p.requested_at DESC LIMIT 20;"
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml logs --since 30m --tail 200 dispatcher prediction-worker
```

Use your configured `POSTGRES_USER` and `POSTGRES_DB` if different. Dispatcher
publishes due `pending` dispatches, due processing retries, and work whose
processing lease expired. It also republishes an `enqueued` prediction that
remains `pending` for 900 seconds after its last submission, such as when Redis
lost the command. An expired running attempt is abandoned before its job is
retried, usually after the 30-second first retry delay. These paths reuse the
same `job_id` and `dispatch_id`; do not insert replacement rows or publish
commands by hand. `failed` and `cancelled` jobs are terminal and are not
automatically requeued. Diagnose their recorded error before any separate,
reviewed recovery action. Confirm the existing job reaches `succeeded`, its
dispatch reaches `stopped`, and a forecast exists for that job.

The isolated one-versus-two-replica results and reproduction details are in
[the prediction benchmark report](../benchmarks/prediction-worker-issue-21.md).

### Run one poll and inspect work

Use the separate operator command for an early poll. It first checks both
consumer health states and then checks readiness before creating or reusing a
durable run and dispatch. A reused run may have been created by Beat.
The command runs inside the Dispatcher container so it can verify that the
Dispatcher process is still alive; calling it in the init container fails closed.

```powershell
& infrastructure/scripts/poll-now.ps1
```

Each action prints a bounded result. Inspect recent durable work with:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec postgres psql -U quakestrike -d quakestrike -c "SELECT run_id, trigger_type, status, requested_at, events_found, events_rejected FROM ingestion_runs ORDER BY requested_at DESC LIMIT 5;"
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec postgres psql -U quakestrike -d quakestrike -c "SELECT dispatch_id, ingestion_run_id, prediction_job_id, status, attempt_count FROM job_dispatches ORDER BY created_at DESC LIMIT 10;"
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml logs --tail 100 dispatcher data-ingestor beat
```

Use your configured `POSTGRES_USER` and `POSTGRES_DB` if they differ from the
example. The ignored bootstrap readiness manifest retains the source and
release proof.

The poll command proves only that a durable run exists. Confirm processing by
checking whether that run reaches `succeeded` or a diagnosed terminal state,
then compare its event, revision, prediction-job, and dispatch counts with the
counts before the poll. A pending run with zero attempts may be waiting for
Dispatcher to drain due prediction dispatches. Inspect bounded JSON logs by
`event_code`, `message_id`, `run_id`, `dispatch_id`, and `correlation_id`:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml logs --since 30m --tail 200 dispatcher data-ingestor beat
```

The isolated proof in `workers/tests/integration/test_local_enablement.py` uses
sanitized source fixtures and the disposable Compose project described in
[CONTRIBUTING.md](../../CONTRIBUTING.md#local-setup-for-contributor-checks). It does
not contact PHIVOLCS. Keep the hash-addressed source snapshot, generated
readiness manifest, and verified model artifacts outside Git through handoff;
archive them outside Git afterward. Docker's existing `local` logging driver
retains five approximately 20 MiB files per container. Logs can rotate and are
not a replacement for durable run and dispatch records.

The local enablement execution record is in
[the issue #13 report](https://github.com/ochlzo/quakestrikeph/blob/813ef6cd5312b373614c2d8bba506e43b035f554/docs/reports/issue-13-local-enablement-2026-09-19.md).
The identifier-only alert runtime defaults to disabled. The Dispatcher uses
`ALERT_RESOLUTION_ENABLED`; submission requires `ALERT_DELIVERY_ENABLED` as well.
The explicit `alerts` profile adds the Alert Worker and independent reconciliation.
Follow [alert operations](alert-runtime.md) for rollout, legacy retirement, and finite verification.
Provider verification and production activation remain separate gates.


### Real-model integration checks

The standard integration runner omits model artifacts and prediction
dependencies, so it skips the two real-model tests. A skip in that runner does
not mean the host lacks the model bundle. The `prediction-smoke-runner` installs
the locked prediction dependencies and mounts `MODEL_ARTIFACT_HOST_DIRECTORY`
read-only. The default host directory is the repository's `model-artifacts/`.
It must contain `seis-1.0.1/manifest.json` and the verified weights.

To run both real-model tests against the disposable database, run:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile prediction-smoke run --build --rm prediction-smoke-runner pytest --config-file workers/pyproject.toml workers/tests/integration/test_prediction_worker.py -k test_real_seis -s
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Confirm the summary shows two passed tests and no skipped tests. The checks
verify a known persisted forecast and measure one versus two worker replicas.
If either test skips, check the reported manifest path, host mount, and
prediction dependencies before reporting the bundle as missing.

To run only the replica benchmark, use the same isolated test project and
replace the test command with:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile prediction-smoke run --build --rm prediction-smoke-runner pytest --config-file workers/pyproject.toml workers/tests/integration/test_prediction_worker.py -k test_real_seis_replica_benchmark -s
```

The benchmark reports throughput, p95 completion time, retry attempts, and
parent/child peak resident memory for ten jobs at each replica count. These
local measurements are a baseline; measure on the VPS before choosing its
steady replica count.

## 8. Stop local services

Stop scheduled publication before stopping consumers.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile beat stop beat
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml stop dispatcher
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction stop data-ingestor prediction-worker
```

If alerts are active, follow [alert shutdown](alert-runtime.md#rollback-and-evidence-limits) before stopping their dependencies.
Leave PostgreSQL and Redis running when local web services still need them.
Avoid project-wide `down` for an application-specific stop. `down -v` deletes the shared data volumes.

## 9. Add the local Backend and Bulletin

Use the same `infrastructure` project and root `.env` for local web development.
Do not include `compose.edge.yml`; that file enables the production edge.
The local override publishes only `127.0.0.1:3000` and `127.0.0.1:4321`.
PostgreSQL and Redis remain private.

### Prepare a new local web environment

If the root `.env` and packaged model already exist, check the settings table below.
Otherwise, obtain the approved `SEIS 1.0.1` package. Replace the example package path before running these commands:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv python install 3.12
uv sync --project workers --frozen
$sourcePackage = 'C:\path\to\reviewed-model-package'
uv run --project workers quakestrike package-model-release --source-package $sourcePackage
```

Set `MODEL_ARTIFACT_HOST_DIRECTORY` to the packaged model's host directory; the default is the ignored `model-artifacts/` folder.

| Settings in root `.env` | Required value |
| --- | --- |
| `POSTGRES_PASSWORD`, `MIGRATION_DB_PASSWORD`, `WORKER_DB_PASSWORD` | Distinct passwords; match migration/worker URLs to their respective logins. |
| `MIGRATION_DATABASE_URL`, `DATABASE_URL`, `REDIS_URL` | Private Compose hosts `postgres:5432` and `redis:6379`. |
| `PHIVOLCS_CATALOG_URL` | Official HTTPS catalog URL, also required by `local-init`. |
| `MODEL_RELEASE_ID` | ID from the approved packaged model manifest. |
| `BACKEND_DB_PASSWORD`, `BACKEND_DATABASE_URL` | Matching credentials for `quakestrike_backend` at `postgres:5432`. |
| `BACKEND_IMAGE_TAG` | Nonempty tag required by the shared file; local override uses `quakestrike-backend:local`. |
| `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `PUBLIC_CLERK_PUBLISHABLE_KEY` | Development Clerk credentials; only the public key reaches Bulletin. |
| `CLERK_AUTHORIZED_PARTIES` | `http://localhost:4321,http://127.0.0.1:4321` |
| `ACCOUNT_REDIS_URL` | `redis://redis:6379/0` |
| `IPROG_API_TOKEN` | Approved credential when phone verification is needed. |

Web-only startup does not need a history import. For live ingestion and prediction, complete [worker setup](#first-time-worker-setup).

### Initialize or update the local web database

For an existing shared database, back up data and stop web services and all work producers/consumers before migrations.
If database passwords changed, follow [password rotation](database-maintenance.md#change-database-passwords-on-an-existing-volume).

1. Match `MODEL_RELEASE_ID` to the verified `SEIS 1.0.1` bundle.
2. Back up the shared database before applying pending migrations.
3. Provision migration and worker roles.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml up -d --wait postgres redis
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create
```

4. Apply migrations explicitly from the development checkout.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml run --build --rm local-init
```

5. Register and verify the selected model release.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml run --rm local-init quakestrike register-model-release
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml run --rm local-init quakestrike verify-model-release
```

6. Provision the Backend role after migrations.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend
```

7. Build the local web images.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml build backend-api bulletin
```

8. If another Bulletin server uses port 4321, stop that server before starting the container.
9. Start the local web services.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --wait postgres redis backend-api bulletin
```

Open `http://127.0.0.1:4321`. Both public and account API requests reach the
local Backend. Account records created in the former isolated database remain
in its original volume; configuration consolidation does not transfer them.
Keep that volume and the ignored configuration backup until its data is no
longer needed. Never use `down -v` to retire the old account environment.

For source and dependency changes, use [the rebuild commands](#rebuild-after-code-or-dependency-changes).

### Local development reference

The local override launches Astro directly with `--ignore-lock`. Docker manages the server process.
This avoids a stale PID in host-mounted `.astro/dev.json` blocking a replacement container.
The command also avoids automatic package installation before server startup.

`LOCAL_API_TARGET` and `LOCAL_ACCOUNT_API_TARGET` default to `http://backend-api:3000`.
Change these values privately only when you deliberately need another API target.
Do not include the production edge file during local development.
