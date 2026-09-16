# Contributing to QuakeStrike PH

This guide is for the team working on QuakeStrike PH. The repository is still
in the first worker implementation slice, so a small, well-tested change is
more useful than a large change that skips the project contracts.

## Start with the project rules

Read these files before changing behavior:

1. [`AGENTS.md`](AGENTS.md)
2. [`CONTEXT.md`](CONTEXT.md)
3. The relevant [architecture specification](docs/system-design/ARCHITECTURE/ARCHITECTURE.md)
4. The [database design](docs/system-design/ERD/DATABASE-DESIGN.md) for any
   persistence or schema work
5. The relevant records in [`docs/adr/`](docs/adr/)
6. [`docs/implementation-plan.md`](docs/implementation-plan.md) for the active
   phase and checkpoint

These documents define the vocabulary, ownership rules, and accepted runtime
decisions. If a change conflicts with one of them, stop and resolve the
conflict in an ADR or an approved document update before coding around it.

## Local setup

From the repository root:

```powershell
Copy-Item .env.example .env
uv python install 3.12
uv sync --project workers --frozen
```

The current project uses Python 3.12 and `uv`. The lock file is
`workers/uv.lock`. Do not update it as a side effect of an unrelated change.

PostgreSQL and Redis are available through:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml up -d
```

The base Compose file keeps those services on an internal network and does not
publish host ports. It is safe for local service storage, but it is not a
complete worker orchestration file yet.

## Branches and commits

Create a branch from the current integration branch. Use a short prefix that
describes the work:

```powershell
git switch -c feat/ingestion-reconciliation
git switch -c fix/queue-contract-validation
git switch -c docs/developer-setup
```

Keep commits focused. A suggested subject format is `type: short description`,
using types such as `feat`, `fix`, `docs`, `test`, `refactor`, or `chore`.

## Code boundaries

The worker package follows these responsibilities:

- `workers/src/quakestrike/domain/` contains domain rules and value concepts.
- `workers/src/quakestrike/application/` coordinates use cases and ports.
- `workers/src/quakestrike/infrastructure/` implements database, queue, HTTP,
  model, logging, and other external adapters.
- `workers/src/quakestrike/scheduler/` owns Beat and dispatcher entry points.
- `workers/src/quakestrike/data_ingestor/` owns the ingestion worker boundary.
- `packages/contracts/queue/` contains versioned message schemas. It is not a
  shared bucket for executable business logic.

Keep dependencies pointing inward. Domain and application code must not import
Celery, SQLAlchemy, Redis, HTTP clients, or provider SDKs. Worker code must not
call the Backend's public HTTP routes for internal data access.

When adding or changing a queue message, update all of these together:

1. The JSON schema under `packages/contracts/queue/`.
2. The Python binding under `workers/src/quakestrike/infrastructure/queues/`.
3. Contract tests under `workers/tests/contract/`.
4. Any ADR or documentation that changes the message's ownership or delivery
   rules.

Queue commands should contain stable database identifiers and correlation
context. They should not carry scraped HTML, full event payloads, secrets, or
CSV paths.

## Database and ingestion changes

Read the database design before changing tables, indexes, PostgreSQL enums,
constraints, transactions, retention, or ownership. PostgreSQL is the live
source of truth. Redis is a broker, not the job store.

Preserve the ingestion invariants:

- A stable event identity survives later PHIVOLCS corrections.
- Changed source data creates a new immutable revision instead of editing the
  old revision in place.
- Duplicate delivery is expected and must be safe to repeat.
- Prediction work needs a complete, canonical feature snapshot and the required
  history coverage.
- Migrations, model release registration, and bootstrap readiness are explicit
  steps. Do not hide them in service startup.

If a change affects architecture, data ownership, security, runtime versions,
queue semantics, deployment, or an external interface, add or update an ADR
before merging the implementation.

## Testing and formatting

Run the complete current check set from the repository root:

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests
uv run --project workers ruff check workers
uv run --project workers ruff format --check workers
git diff --check
```

The tests must remain deterministic. Do not make CI or unit tests call the live
PHIVOLCS website. Use sanitized fixtures and fakes for external systems. Add a
local PostgreSQL/Redis integration test only when the test owns its setup and
cleanup.

When a test exposes a bug, prefer a failing test first, then the smallest fix
that satisfies the relevant contract. Keep tests near the boundary they
protect. Queue shape tests belong in `workers/tests/contract/`; pure rules
belong in unit tests; database behavior belongs in integration tests when that
layer exists.

## Logging and local data

Use the structured logging helpers already in the worker package. Never log
secrets, passwords, raw HTML, large source payloads, model weights, or complete
connection URLs. Include available run, dispatch, correlation, worker, event,
revision, and message identifiers.

Keep these files and directories local and untracked:

- `.env` and `.env.local`
- `model-artifacts/`
- `bootstrap-snapshots/`
- `datasets/` and `data/`
- local readiness manifests and source snapshots

If a fixture is needed for a test, sanitize it first and commit only the small
fixture required to explain the behavior.

## Pull requests

A pull request should explain the behavior it changes and the evidence that it
works. Include links to the issue, plan checkpoint, or ADR when one exists.

Before requesting review, check:

- [ ] The change stays within the current implementation phase.
- [ ] `pytest`, Ruff lint, Ruff format check, and `git diff --check` pass.
- [ ] Tests cover the changed contract or regression.
- [ ] Documentation and diagrams are updated when behavior or ownership
      changed.
- [ ] A relevant ADR exists for architecture, schema, security, runtime,
      queue, or deployment changes.
- [ ] No credentials, model artifacts, datasets, raw PHIVOLCS payloads, or
      generated local output are included.
- [ ] The pull request states any deferred work or known limitation.

Reviewers should check the requested behavior against the project documents,
then check the dependency direction and failure behavior. In particular, a
worker should fail closed when required readiness gates are unavailable, and a
duplicate queue delivery should not create a second logical record.
