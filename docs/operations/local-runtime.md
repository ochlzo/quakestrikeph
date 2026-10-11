# Local runtime enablement

These steps use PowerShell from the repository root. They start the local data
services, initialize the database and model release, import preserved history,
and check whether the runtime is ready. Initialization is explicit: starting
containers alone does not migrate or bootstrap an empty database.

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
Copy-Item .env.example .env
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

## 5. Initialize the database and model release

For an existing database, stop all work producers and consumers before these
release steps. Let in-flight prediction attempts finish before stopping the
workers when possible:

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

The reissue command handles durable `SEIS 1.0` prediction work that cannot
produce a v2 forecast. It creates new `SEIS 1.0.1` jobs and dispatches from
preserved input snapshots, closes eligible old jobs and dispatches, and audits
the linked IDs. It accepts old `pending` and `retry_wait` jobs, and old
`failed` jobs with `unsupported_schema` or `release_mismatch` errors. It
refuses a running job or active attempt; let that work settle and rerun the
command. It skips successful, cancelled, and unrelated failed work. Reruns are
safe, but a conflicting existing replacement fails for investigation. Check
that the command prints `"status": "completed"` and inspect its `reissued`
and `reused` counts before starting Dispatcher or Prediction Worker. Each
reissue cancels the old job with `reissued_for_release` and writes a
`prediction_backlog_reissued` audit linking the old and new job and dispatch
IDs. No alert is sent by reissue itself. See
[ADR 0028](../adr/0028-legacy-prediction-backlog-reissue.md) for the
transaction and identity rules.

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
& infrastructure/scripts/enable-beat.ps1
```

The Beat enable command checks both consumer health states before starting it.
Compose also enforces both as healthy dependencies and the command checks again
after Beat becomes healthy, stopping it if a consumer failed during startup. Each process
also evaluates its read-only startup gates. Beat waits for the strictly next
UTC wall-clock boundary of `POLL_INTERVAL_SECONDS` (five minutes by default).
It does not poll on startup or replay missed boundaries. Beat has no automatic
restart policy; enable it explicitly again after a stack restart.

To consume prediction work, start the separate Prediction image before creating
a poll. It loads and verifies the `SEIS 1.0.1` bundle before consuming the queue.
The model files remain on the read-only artifact mount.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction up -d --wait prediction-worker
```

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

For one early poll, use the separate operator command. It first checks both
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
[the issue #13 report](../reports/issue-13-local-enablement-2026-09-19.md).
The identifier-only alert runtime defaults to disabled. The Dispatcher uses
`ALERT_RESOLUTION_ENABLED`; submission requires `ALERT_DELIVERY_ENABLED` as well.
The explicit `alerts` profile adds the Alert Worker and independent reconciliation.
Follow [alert operations](alert-runtime.md) for rollout, legacy retirement, and finite verification.
Provider verification and production activation remain separate gates.

## 8. Stop local services

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml down
```

This stops the containers and retains their volumes. Do not add `-v` unless
you intend to delete the local PostgreSQL and Redis data.

## 9. Add the local Backend and Bulletin

Use the same `infrastructure` project and root `.env` for local web development.
Do not include `compose.edge.yml`; that file enables the production edge.
The local override publishes only `127.0.0.1:3000` and `127.0.0.1:4321`.
PostgreSQL and Redis remain private. See [ADR 0043](../adr/0043-shared-local-compose-runtime.md).

Set `BACKEND_DB_PASSWORD`, a matching `BACKEND_DATABASE_URL` with the
`quakestrike_backend` login, and the registered `MODEL_RELEASE_ID` in root `.env`.
Set `BACKEND_IMAGE_TAG` for the shared Backend file; the local override uses
the development-only `quakestrike-backend:local` image instead.
Set `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `PUBLIC_CLERK_PUBLISHABLE_KEY`,
`CLERK_AUTHORIZED_PARTIES=http://localhost:4321,http://127.0.0.1:4321`,
`ACCOUNT_REDIS_URL=redis://redis:6379/0`, and `IPROG_API_TOKEN` for account features.
The Bulletin receives only the publishable key and local proxy targets.

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

The Bulletin mounts application source for development. After a lockfile
change, rebuild its image and renew only its dependency volume with
`docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --no-deps --force-recreate -V bulletin`.
The command renews anonymous volumes; the Bulletin dependency mount must be
anonymous so it never changes the shared PostgreSQL or Redis volumes.
