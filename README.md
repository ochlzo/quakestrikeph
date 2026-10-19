# QuakeStrike PH

QuakeStrike PH is a Philippine earthquake information, forecasting, and alert
project. It reconciles PHIVOLCS bulletins into earthquake records, prepares
versioned prediction inputs, and records forecasts.

This README is the starting point for a developer joining the project. For the
rules to follow before pushing any change, including documentation, use
[CONTRIBUTING.md](CONTRIBUTING.md).

The main flow is:

```text
PHIVOLCS bulletin -> ingestion run -> event and revision -> prediction job
                  -> Prediction Worker -> forecast
```

![System and layered architecture](docs/system-design/ARCHITECTURE/system-architecture-layers.png)

## Find your way around

| Path                              | What is there now                                                                |
| --------------------------------- | -------------------------------------------------------------------------------- |
| `workers/src/quakestrike/`        | Scheduling, ingestion, prediction, and shared application code.                  |
| `workers/tests/`                  | Unit and integration tests.                                                      |
| `database/migrations/`            | PostgreSQL schema migrations.                                                    |
| `database/initialization/`        | Explicit role provisioning and release preparation scripts.                      |
| `database/maintenance/`           | Backup, restore-test, and retention scripts with host scheduler units.           |
| `packages/contracts/queue/`       | Versioned ingestion, prediction, and alert command schemas.                      |
| `packages/contracts/openapi.yaml` | Public Backend HTTP contract.                                                    |
| `apps/backend-api/`               | Read-only Node/Express/TypeScript earthquake and forecast API.                   |
| `apps/quakestrikeph-bulletin/`    | Astro/React/TypeScript public Bulletin with API-backed event and forecast views. |
| `infrastructure/`                 | Compose files and operator scripts.                                              |
| `docs/adr/`                       | Accepted decisions that govern implementation.                                   |
| `docs/system-design/`             | Intended architecture, database design, and data flows.                          |

The Operations Console does not have code under `apps/` yet.

## Start the project locally

These instructions start Bulletin, the Backend, PostgreSQL, Redis, and the ingestion/prediction workers on Windows.
Run commands in PowerShell from the repository root after cloning. Stop the sequence if a command fails.

### 1. Prepare the prerequisites

Install Git, PowerShell 7, Docker Desktop with Linux containers and Compose v2, and [`uv`](https://docs.astral.sh/uv/).
Start Docker Desktop before running Docker commands. The steps below install Python 3.12 through `uv`.
Docker builds provide Node and pnpm; a separate host installation is unnecessary for this workflow.

Ask the maintainer for these private files and settings before starting:

| Item | What you need |
| --- | --- |
| Repository access | Access to the private GitHub repository. |
| Local environment | Approved development settings for root `.env`, including the official PHIVOLCS catalog URL and any account-provider credentials. |
| Model weights | The reviewed `SEIS 1.0.1` source package and referenced weights, with their original folder structure preserved. |
| Local earthquake data | The preserved raw/enriched PHIVOLCS JSON snapshot and its independently verified coverage cutoff. |
| Historical CSV, if supplied | Keep the approved CSV as source/reference material. The runtime does not import a cleaned CSV directly. |

The import snapshot must contain source bulletin IDs, source URLs, retrieval metadata, row counts, and validated history coverage.
The current bootstrap requires the 25–31 August 2026 lookback plus the available demonstration records.
Ask for the matching JSON snapshot if your handoff contains only a cleaned CSV.
Do not use test fixtures as local demonstration data.

### 2. Clone the repository

Open PowerShell in your chosen parent folder, then clone the repository:

```powershell
git clone https://github.com/ochlzo/quakestrikeph.git
cd quakestrikeph
uv python install 3.12
uv sync --project workers --frozen
```

Use a maintainer-approved commit whose checks passed. Worker image builds require a clean checkout at that commit.
Keep local configuration and data in the ignored locations below so they do not make the checkout dirty.

### 3. Configure the environment

If the maintainer supplied a local `.env`, place it at the repository root.
Otherwise, create the file from the template:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
git rev-parse HEAD
```

The Git command prints the full commit SHA. Set `WORKER_IMAGE_TAG` to that value in `.env`.
Check these settings before continuing; template placeholders are not working credentials.

| Settings | Local value or requirement |
| --- | --- |
| `POSTGRES_PASSWORD`, `MIGRATION_DB_PASSWORD`, `WORKER_DB_PASSWORD`, `BACKEND_DB_PASSWORD` | Distinct local passwords. |
| `MIGRATION_DATABASE_URL` | Migration login and matching password at `postgres:5432/quakestrike`. |
| `DATABASE_URL` | Worker login and matching password at `postgres:5432/quakestrike`. |
| `BACKEND_DATABASE_URL` | `quakestrike_backend` login and matching password at `postgres:5432/quakestrike`. |
| `REDIS_URL`, `ACCOUNT_REDIS_URL` | `redis://redis:6379/0` |
| `PHIVOLCS_CATALOG_URL` | Maintainer-approved official HTTPS catalog URL; replace `example.invalid`. |
| `MODEL_RELEASE_ID` | ID from the approved model manifest. |
| `MODEL_ARTIFACT_DIRECTORY` | `model-artifacts`, for the host packaging command. |
| `MODEL_ARTIFACT_HOST_DIRECTORY` | `../model-artifacts`, resolved from `infrastructure/` to the repository's model folder. |
| `BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH` | Independently verified source cutoff for the supplied snapshot, including its time-zone offset. |
| `WORKER_IMAGE_TAG` | Full tested SHA from `git rev-parse HEAD`. |
| `BACKEND_IMAGE_TAG` | Keep a nonempty value; the local override uses `quakestrike-backend:local`. |
| `PUBLIC_BULLETIN_BASE_URL` | `http://127.0.0.1:4321` for links generated by this local worker. |
| `ALERT_RESOLUTION_ENABLED`, `ALERT_DELIVERY_ENABLED` | Keep both `false` for this setup. |

For account features, configure the development Clerk keys: `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, and `PUBLIC_CLERK_PUBLISHABLE_KEY`.
Set `CLERK_AUTHORIZED_PARTIES=http://localhost:4321,http://127.0.0.1:4321`.
Phone verification additionally requires the approved `IPROG_API_TOKEN`; obtaining a token does not authorize a real SMS send.

This Compose workflow reads root `.env` and forwards each service's required settings. Separate app `.env.local` files are unnecessary.
Keep provider secrets on the Backend; Bulletin receives only its public key.
Do not include `compose.edge.yml` for local development.

### 4. Place the model and local data

Replace both example paths with the files supplied by the maintainer. Keep the source package's referenced weight files in their original locations:

```powershell
$sourcePackage = 'C:\path\to\reviewed-model-package'
$snapshotPath = 'C:\path\to\preserved-bootstrap-snapshot.json'
New-Item -ItemType Directory -Force bootstrap-snapshots | Out-Null
Copy-Item -LiteralPath $snapshotPath -Destination bootstrap-snapshots/input.json
uv run --project workers quakestrike package-model-release --source-package $sourcePackage
```

**Expected result:** The package command reports `"status": "packaged"`.
The model manifest and verified weights appear under `model-artifacts/seis-1.0.1/`.
Keep any accompanying historical CSV in ignored `datasets/` or `data/`.

Your local files now include:

```text
quakestrikeph/
  .env
  model-artifacts/seis-1.0.1/   # Packaged manifest and weights.
  bootstrap-snapshots/input.json
  datasets/                   # Optional historical CSV/reference files.
```

Keep `.env`, model weights, source snapshots, and generated readiness files outside Git.

### 5. Start data services and build worker images

The initialization steps below are for a new local database.
For an existing database, follow [the runtime update procedure](docs/operations/local-runtime.md#5-initialize-the-database-and-model-release) before migrations.
Back up existing data and stop applications and workers before changing its schema.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait postgres redis
& infrastructure/scripts/build-worker-image.ps1
& infrastructure/scripts/build-prediction-image.ps1
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create
```

**Expected result:** PostgreSQL and Redis are healthy; the image helpers report `built` or `reused` for the configured SHA.
These commands provision separate migration and worker logins. They do not initialize tables or import history.

### 6. Initialize the database and import history

Run these commands once for the new database, in order:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike migrate

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh grant-worker

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike register-model-release

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike verify-model-release

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike bootstrap --snapshot /app/bootstrap-snapshots/input.json --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
```

**Expected result:** Model verification reports `"status": "verified"`; the final check exits successfully and reports `"ready": true`.
If readiness fails, correct the reported cause before starting workers.
The generated `bootstrap-snapshots/bootstrap-readiness.json` belongs to this database. Do not copy another machine's readiness file.

### 7. Start the Backend and Bulletin

If another local server uses port 3000 or 4321, stop that server first.
Provision the Backend login after migrations, then build and start the local web services:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml build backend-api bulletin

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --wait postgres redis backend-api bulletin
```

Open <http://127.0.0.1:4321>. Bulletin sends public and account requests to your local Backend at `http://127.0.0.1:3000`.
An empty earthquake list after initialization needs investigation; check the bootstrap result and Backend logs.

### 8. Start workers, then the schedule

Start each service and wait for its health check before continuing:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait dispatcher

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait data-ingestor

docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction up -d --wait prediction-worker

& infrastructure/scripts/enable-beat.ps1
```

**Expected result:** The services become healthy and the helper reports `"status":"enabled"`.
Beat creates scheduled ingestion work at the next five-minute boundary by default. It does not poll immediately on startup.
Live ingestion needs internet access to PHIVOLCS. Ordinary alert delivery stays disabled.

To request an early poll after startup, run:

```powershell
& infrastructure/scripts/poll-now.ps1
```

### 9. Start again after the first setup

Keep the same root `.env`, model files, bootstrap files, and Docker data volumes.
Start the data and web services:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml up -d --wait postgres redis backend-api bulletin
```

For live ingestion and prediction, repeat [step 8](#8-start-workers-then-the-schedule).
For Bulletin-only work, the web startup command is enough.
Do not repeat migrations, registration, or history import for an ordinary restart.
For dependency or Backend code changes, use [the rebuild procedure](docs/operations/local-runtime.md#rebuild-after-code-or-dependency-changes).

### Check or stop the local runtimes

Check web status and recent logs:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml ps postgres redis backend-api bulletin
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml logs --tail 100 backend-api bulletin
```

Check worker status and recent logs:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction --profile beat ps
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml logs --tail 100 dispatcher data-ingestor prediction-worker beat
```

To stop application work, stop the schedule before the workers, then stop the web services:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile beat stop beat
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml stop dispatcher
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile prediction stop data-ingestor prediction-worker
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.local.yml stop bulletin backend-api
```

PostgreSQL and Redis remain available with their data. Local web services and workers share these services.
Do not use `down -v` for an ordinary stop; that command deletes shared data volumes.

For detailed recovery and other tasks, use the [operations index](docs/operations/README.md) or [visual operations handbook](docs/operations/pretty-operations-documentation.html).
Use [CONTRIBUTING.md](CONTRIBUTING.md) for tests, branches, and checks before pushing.
