# QuakeStrike PH

QuakeStrike PH is a Philippine earthquake information, forecasting, review,
and alert platform. It is designed to ingest PHIVOLCS bulletins, preserve
event revisions, build versioned prediction inputs, publish approved public
information, and support protected review and alert workflows.

> Current repository status: this checkout contains the Python worker
> scaffold, the six-table ingestion migration, and local PostgreSQL/Redis
> infrastructure. Phase 3 model packaging, registration, and release verification
> are implemented. Scheduled durable ingestion dispatch and the explicit,
> resumable historical bootstrap workflow are implemented through Issue #10.
> Prediction execution and alert delivery remain planned work. Services still
> fail closed until every configured startup gate is ready.

## Architecture

The intended system uses three Astro applications, one shared Node.js Backend,
Python background workers, PostgreSQL for durable state, Redis for queue
transport, and Cloudflare Tunnel plus Traefik at the public edge.

![QuakeStrike PH system and layered architecture](docs/system-design/ARCHITECTURE/system-architecture-layers.png)

The written [architecture specification](docs/system-design/ARCHITECTURE/ARCHITECTURE.md)
and accepted [architecture decision records](docs/adr/) control the design.
The image is a quick system view, not a replacement for those documents.

## Main system components

| Component | Responsibility | Status in this repository |
| --- | --- | --- |
| PHIVOLCS source | Provides earthquake bulletins and bulletin details. | External dependency. The adapter is planned beyond the current scaffold. |
| Scheduler Beat | Creates one durable ingestion run on the five-minute schedule. | One local schedule creates or reuses the PostgreSQL run and dispatch atomically. |
| Dispatcher | Claims PostgreSQL dispatch records and publishes identifier-only commands to Redis. | Bounded leased claims, acceptance fencing, retry, and expired-claim recovery are implemented. |
| Data Ingestor | Retrieves, validates, reconciles, and persists PHIVOLCS events and revisions. | Shared normalization/reconciliation and resumable snapshot bootstrap are implemented; live queue operation remains gated. |
| PostgreSQL | Source of truth for events, revisions, runs, jobs, dispatches, audits, and other durable records. | The first six-table migration and transaction adapters are implemented. |
| Redis | Carries typed Celery commands between worker processes. | Pinned local service and queue contracts exist. |
| Prediction Worker | Loads the verified `SEIS 1.0` artifacts and records forecast results. | Deferred. |
| Alert Worker | Creates and delivers approved SMS alert jobs. | Deferred. |
| Backend API | Serves the versioned HTTP interface and enforces application authorization. | Planned. |
| Web applications | Bulletin, PHIVOLCS Monitoring, and Operations Console interfaces. | Planned. |
| Public edge | Cloudflare Tunnel and Traefik routing for the web applications and API. | Planned. |

The intended first-slice flow is:

```text
PHIVOLCS
   -> Scheduler Beat
   -> PostgreSQL ingestion run and dispatch records
   -> Dispatcher
   -> Redis ingestion command
   -> Data Ingestor
   -> PostgreSQL event and revision state
   -> immutable feature snapshot and prediction dispatch
```

PostgreSQL remains the durable source of truth. Redis carries commands and is
not a replacement for durable job state. Queue messages contain stable database
identifiers, not scraped HTML, complete event payloads, or CSV paths.

## Repository layout

```text
quakestrikeph/
├── workers/
│   ├── pyproject.toml              # Python 3.12 project and tool settings
│   ├── uv.lock                     # locked Python dependencies
│   ├── Dockerfile                  # worker image scaffold
│   ├── src/quakestrike/            # worker package
│   └── tests/                      # unit and queue-contract tests
├── packages/contracts/queue/       # versioned JSON queue schemas
├── infrastructure/compose.yml     # local PostgreSQL and Redis services
├── docs/                           # architecture, ADRs, diagrams, plan
├── CONTEXT.md                      # ingestion glossary and invariants
├── AGENTS.md                       # repository working instructions
├── .env.example                    # local configuration template
├── README.md
└── CONTRIBUTING.md
```

The full architecture document describes planned `apps/`, Backend, database,
model-artifact, and production infrastructure paths. They are not all present
yet, so do not assume that the planned tree is already runnable.

## Prerequisites

Install these tools before starting:

- Git
- Python 3.12.x
- `uv` for the Python environment and locked dependencies. The worker image
  currently pins `uv` 0.11.32.
- Docker Desktop or Docker Engine with Docker Compose v2

Node.js is not needed for the current repository slice because the planned web
applications and Backend API have not been added.

## Quick start

Run the following from the repository root in PowerShell.

### 1. Create local configuration

```powershell
Copy-Item .env.example .env
```

Review `.env` before using it. Replace placeholder values where needed. Keep
`.env` local. It is ignored by Git.

The worker settings require `DATABASE_URL`, `REDIS_URL`,
`PHIVOLCS_CATALOG_URL`, and `MODEL_RELEASE_ID`. `DATABASE_URL` must use the
`postgresql+psycopg` scheme. `PHIVOLCS_CATALOG_URL` must use HTTPS. The
remaining settings and their allowed ranges are in
`workers/src/quakestrike/infrastructure/settings.py`.

### 2. Install the locked worker environment

```powershell
uv python install 3.12
uv sync --project workers --frozen
```

`--frozen` prevents `uv` from changing `workers/uv.lock` during setup.

### 3. Run the local checks

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests
uv run --project workers ruff check workers
uv run --project workers ruff format --check workers
git diff --check
```

These checks do not need live PHIVOLCS access. The current test suite uses
sanitized inputs and in-memory fakes for health checks. PostgreSQL integration
tests skip unless `TEST_DATABASE_URL` points to an isolated test database.

Run the Phase 2 PostgreSQL tests without publishing a database port:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Use the fixed `quakestrike-data-ingestion-test` project name for this shared
test environment. It matches the currently running PostgreSQL and Redis test
containers and keeps the locally built `test-runner` image under one stable
name. Compose can reuse the existing containers and image cache; it only needs
to build a new image when the build inputs change. Use another project name
only when you intentionally want a separate test environment.

The final command removes only the disposable
`quakestrike-data-ingestion-test` project and its resources.

## Start PostgreSQL and Redis locally

The Compose file starts only the local data services. It does not start the
Python worker processes, and it does not publish PostgreSQL or Redis ports to
the host.

```powershell
docker compose --env-file .env -f infrastructure/compose.yml up -d
docker compose --env-file .env -f infrastructure/compose.yml ps
docker compose --env-file .env -f infrastructure/compose.yml exec postgres pg_isready -U quakestrike -d quakestrike
docker compose --env-file .env -f infrastructure/compose.yml exec redis redis-cli ping
```

The health checks should report PostgreSQL as accepting connections and Redis
as returning `PONG`. The Compose service names are `postgres` and `redis`.
Those names work from containers on the private Compose network. A Python
process running directly on the host cannot use them unless the team adds a
separate local development override with deliberate port mappings.

Apply and inspect migrations from a container attached to an isolated test
database with:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --rm test-runner alembic -c workers/alembic.ini upgrade head
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --rm test-runner alembic -c workers/alembic.ini current
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --rm test-runner alembic -c workers/alembic.ini downgrade base
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --rm test-runner alembic -c workers/alembic.ini upgrade head
```

Stop the services without deleting their named volumes with:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml down
```

Do not use `docker compose down -v` as a normal cleanup command. It deletes the
local PostgreSQL and Redis volumes.

## Validate the worker entry points

The command-line entry point and the three worker entry points are fail-closed
checks at this stage:

```powershell
uv run --project workers quakestrike --help
uv run --project workers quakestrike startup-check
uv run --project workers quakestrike-beat
uv run --project workers quakestrike-dispatcher
uv run --project workers quakestrike-ingestor
```

The scheduler, dispatcher, and ingestor still return exit code `2` until every
startup gate is ready. The bootstrap command is an explicit operator action and
does not run through the ingestion queue:

```powershell
uv run --project workers quakestrike bootstrap --snapshot .\bootstrap-snapshots\historical.json
uv run --project workers quakestrike bootstrap-readiness
```

The default run manifest is `database/initialization/bootstrap-readiness.json`.
Set `BOOTSTRAP_RUN_MANIFEST` or pass `--run-manifest` to override the readiness
sidecar used by startup checks. Set `BOOTSTRAP_REQUIRED_AVAILABLE_THROUGH` to
the independently verified latest PHIVOLCS catalog cutoff for the bootstrap.
If a failed run reaches its retry limit, use
`quakestrike bootstrap-recover` to requeue that same run identity before
rerunning `bootstrap`. The source envelope must declare `source.retrieved_at`
and `source.available_through`; the declared endpoint must reach the configured
September cutoff, and coverage must include it. The command copies the exact source bytes into the ignored,
hash-addressed `bootstrap-snapshots/source-snapshots/` evidence directory. Raw
imports also bind the derived enrichment-cache hash to the durable backfill run.
The sidecar is mutable operator state and remains ignored by Git.
The bootstrap creates prediction jobs and durable prediction dispatches for
eligible events, but automatic alert work is explicitly suppressed.

Build the current worker image with:

```powershell
docker build -f workers/Dockerfile -t quakestrike-workers:local workers
```

The image is a build artifact for the worker scaffold. A complete Compose
worker service will be added with the later ingestion and deployment phases.

## SEIS 1.0 local release

The selected training package is
`C:\Projects\quakestrikeph\redo\quakestrikeph-training\baselines\attempt-2\stratified-baseline-02\chosen-models\balanced-selection-anchor-exploratory-01`.
From the repository root, copy `.env.example` to `.env` if needed. Set
`POSTGRES_PASSWORD` and the password in `DATABASE_URL` to the same value.
Keep `DATABASE_URL` pointed at `postgres:5432`, the private Compose service.
Set `MODEL_RELEASE_ID` to the reviewed manifest's release ID. The package
command needs the source package on the host. The release initialization
container runs migrations and registration on the private network:

```powershell
uv run --project workers quakestrike package-model-release --source-package "C:\Projects\quakestrikeph\redo\quakestrikeph-training\baselines\attempt-2\stratified-baseline-02\chosen-models\balanced-selection-anchor-exploratory-01"
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait postgres redis
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml build release-init
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init alembic -c alembic.ini upgrade head
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike register-model-release
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres psql -U quakestrike -d quakestrike -Atc "SELECT count(*) FROM model_releases;"
```

The final command prints `1` on a fresh local database. Run the registration
command again to check replay; the count remains `1`. If you change
`POSTGRES_USER` or `POSTGRES_DB`, use those values in the `psql` command.
The release initialization container is an operator command, not a running
worker service. It mounts the host artifact bundle read-only.

The reviewed policy is
`workers/model-release-manifests/seis-1.0/manifest.json`. The package command
checks its exact canonical bytes and all eight weight hashes before publishing
the local bundle. Registration checks the existing bundle, then inserts the
immutable PostgreSQL release row. An exact replay succeeds without changing the
row; reuse of a release ID or version label with changed data fails. Startup
checks the configured ID, reviewed policy, bundle, weights, and row without
changing them. Any failed check blocks service work. Model weights remain
outside Git and worker image builds. Future
worker services must bind the host path set by
`MODEL_ARTIFACT_HOST_DIRECTORY` to `/app/model-artifacts` read-only. Inside
those containers, set `MODEL_ARTIFACT_DIRECTORY=/app/model-artifacts`.

## Development rules

Before changing behavior, read these documents in this order:

1. [`AGENTS.md`](AGENTS.md) for repository instructions.
2. [`CONTEXT.md`](CONTEXT.md) for ingestion terms and invariants.
3. The relevant [architecture](docs/system-design/ARCHITECTURE/ARCHITECTURE.md),
   [database contract](docs/system-design/ERD/DATABASE-DESIGN.md), and ADRs.
4. [`docs/implementation-plan.md`](docs/implementation-plan.md) for the
   current phase and its review checkpoint.

Keep these boundaries intact:

- Domain rules do not import Celery, SQLAlchemy, Redis, HTTP clients, or
  provider SDKs.
- Queue handlers adapt messages into application use cases. They do not become
  the place for business policy.
- PostgreSQL owns durable state. Redis only transports commands and provides
  short-lived coordination.
- Database migrations, model registration, bootstrap, and readiness checks are
  explicit operator actions. Service startup must not perform them silently.
- Tests must not depend on the live PHIVOLCS website.
- Do not commit `.env` files, model weights, datasets, bootstrap snapshots, or
  raw source HTML. The repository `.gitignore` already covers the expected
  local paths.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the branch, testing, review, and
pull request workflow.

## Documentation map

- [Architecture specification](docs/system-design/ARCHITECTURE/ARCHITECTURE.md)
- [Architecture image](docs/system-design/ARCHITECTURE/system-architecture-layers.png)
- [Database design](docs/system-design/ERD/DATABASE-DESIGN.md)
- [Context glossary](CONTEXT.md)
- [Implementation plan](docs/implementation-plan.md)
- [Architecture decision records](docs/adr/)
- [Context and data-flow diagrams](docs/system-design/CFD-DFD/)
