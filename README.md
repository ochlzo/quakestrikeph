# QuakeStrike PH

QuakeStrike PH is a Philippine earthquake information, forecasting, and alert
project. It reconciles PHIVOLCS bulletins into earthquake records, prepares
versioned prediction inputs, and records forecasts.

This README is the starting point for a developer joining the project. For the
rules to follow before pushing any change, including documentation, use
[CONTRIBUTING.md](CONTRIBUTING.md).

## What is implemented

The current code includes the Python worker and data pipeline. It includes the
scheduler, bulletin ingestion, event revision history, prediction jobs, a
Prediction Worker, PostgreSQL migrations, Redis queues, and local Compose
configuration. A read-only Backend API now has event search and detail routes
with current forecast reads; its [VPS setup](docs/operations/backend-api.md)
is explicit. The public Bulletin app, Operations Console, automatic SMS
delivery, and production monitoring are still planned.

The main flow is:

```text
PHIVOLCS bulletin -> ingestion run -> event and revision -> prediction job
                  -> Prediction Worker -> forecast
```

PostgreSQL stores durable records. Redis carries commands that identify those
records. The [architecture specification](docs/system-design/ARCHITECTURE/ARCHITECTURE.md)
describes the intended full system; its diagram includes components that are
not implemented yet.

The planned Bulletin uses Clerk email/password or Google sign-in for personal
email and SMS alert settings. IPROG SMS handles separate phone verification
and SMS delivery; Brevo sends alert email. The separate Operations Console is
protected by Cloudflare Access and reads selected PostgreSQL records on its
server. See the
[Console ADR](docs/adr/0035-cloudflare-access-operations-console.md),
[Bulletin auth ADR](docs/adr/0037-clerk-free-bulletin-authentication.md), and
[alert channel ADR](docs/adr/0038-email-and-sms-alert-preferences.md).

![System and layered architecture](docs/system-design/ARCHITECTURE/system-architecture-layers.png)

## Find your way around

| Path | What is there now |
| --- | --- |
| `workers/src/quakestrike/` | Scheduling, ingestion, prediction, and shared application code. |
| `workers/tests/` | Unit and integration tests. |
| `workers/migrations/` | PostgreSQL schema migrations. |
| `packages/contracts/queue/` | Versioned ingestion and prediction command schemas. |
| `packages/contracts/openapi.yaml` | Public Backend HTTP contract. |
| `apps/backend-api/` | Read-only Node/Express/TypeScript earthquake and forecast API. |
| `infrastructure/` | Compose files and operator scripts. |
| `docs/adr/` | Accepted decisions that govern implementation. |
| `docs/system-design/` | Intended architecture, database design, and data flows. |

The planned web applications do not have code under `apps/` yet.

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

Before changing domain behavior, read [CONTEXT.md](CONTEXT.md). Read the
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
