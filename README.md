# QuakeStrike PH

QuakeStrike PH is a Philippine earthquake information, forecasting, review,
and alert platform. It is designed to ingest PHIVOLCS bulletins, preserve
event revisions, build versioned prediction inputs, publish approved public
information, and support protected review and alert workflows.

> Current repository status: this checkout contains the first Python worker
> scaffold and local PostgreSQL/Redis infrastructure. The web applications,
> Backend API, database migrations, model registration, bootstrap workflow,
> prediction execution, and alert delivery are planned work. The Phase 1
> worker entry points fail closed until their later startup gates exist.

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
| Scheduler Beat | Creates one durable ingestion run on the five-minute schedule. | Entry point exists; durable scheduling is planned. |
| Dispatcher | Claims PostgreSQL dispatch records and publishes identifier-only commands to Redis. | Entry point and queue configuration exist; durable dispatch is planned. |
| Data Ingestor | Retrieves, validates, reconciles, and persists PHIVOLCS events and revisions. | Entry point exists; ingestion behavior is planned. |
| PostgreSQL | Source of truth for events, revisions, runs, jobs, dispatches, audits, and other durable records. | Pinned local service exists; migrations are planned. |
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
sanitized inputs and in-memory fakes for health checks.

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

Stop the services without deleting their named volumes with:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml down
```

Do not use `docker compose down -v` as a normal cleanup command. It deletes the
local PostgreSQL and Redis volumes.

## Validate the Phase 1 scaffold

The command-line entry point and the three worker entry points are read-only
checks at this stage:

```powershell
uv run --project workers quakestrike --help
uv run --project workers quakestrike startup-check
uv run --project workers quakestrike-beat
uv run --project workers quakestrike-dispatcher
uv run --project workers quakestrike-ingestor
```

The last four commands are expected to return exit code `2` for now. Phase 1
deliberately reports the migration-state, model-release, and bootstrap-
readiness gates as unavailable, then refuses to perform work. This protects a
partially initialized environment from running as if it were ready.

Build the current worker image with:

```powershell
docker build -f workers/Dockerfile -t quakestrike-workers:local workers
```

The image is a build artifact for the worker scaffold. A complete Compose
worker service will be added with the later scheduler and ingestion phases.

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
