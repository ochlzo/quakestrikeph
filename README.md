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

To run the Bulletin locally, use Node.js 22.19 or newer and pnpm 11.11.0:

```powershell
cd apps/quakestrikeph-bulletin
pnpm install --frozen-lockfile
pnpm dev
```

For shared UI source editing, also run these commands from the repository root:

```powershell
pnpm --dir packages/ui install --frozen-lockfile
pnpm --dir packages/ui check
```

The UI package owns its TypeScript configuration and CSS import declarations.

During local development, Astro proxies `/api/v1` requests to
`https://quakestrikeph.com`, so the Bulletin reads live public earthquake
data and requires an internet connection. Production keeps the browser request
same-origin and lets Traefik route `/api/v1/` to the Backend container.

Its Dockerfile builds from the repository root with
`docker build -t quakestrikeph-bulletin -f apps/quakestrikeph-bulletin/Dockerfile .`.

## Your first development session

From the repository root, install Python 3.12 and
[`uv`](https://docs.astral.sh/uv/), then install the locked worker dependencies
and run the unit tests:

```powershell
uv python install 3.12
uv sync --project workers --frozen
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests/unit
```

This path lets you inspect and test the worker code without a model package,
historical PHIVOLCS snapshot, or running services. To test changes involving
PostgreSQL, Redis, bootstrap, ingestion, or dispatch, use the isolated Compose
integration suite in [CONTRIBUTING.md](CONTRIBUTING.md#local-setup-for-contributor-checks).
It requires Docker with Compose v2. Host pytest skips those integration tests
when its test database and Redis variables are absent.

Before changing domain behavior, read [GLOSSARY.md](GLOSSARY.md). Read the
relevant [ADRs](docs/adr/) before changing behavior, architecture, data,
dependencies, queues, runtime, deployment, or interfaces. The specifications
describe the intended system; check the code to see what is implemented.

## When you need the full local runtime

Follow the [local runtime guide](docs/operations/local-runtime.md) to start
PostgreSQL, Redis, the workers, and the scheduler. That workflow needs a
reviewed SEIS 1.0.1 model package and a preserved PHIVOLCS bootstrap snapshot
from a maintainer. It explicitly provisions database roles, applies migrations,
imports history, and checks readiness before polling.

For password changes or private production database access, see
[database maintenance](docs/operations/database-maintenance.md). These are
operator tasks, not prerequisites for a first code change.

## Make a change

Use [CONTRIBUTING.md](CONTRIBUTING.md) for branch names, checks, commits,
pushes, and pull requests. Keep `.env`, model weights, source snapshots, and
generated readiness manifests out of Git.
