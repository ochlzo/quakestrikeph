# Contributing to QuakeStrike PH

This guide covers how to make and submit changes. For the system overview and
local runtime setup, start with [README.md](README.md).

## Work on your own branch

Create a branch for each change from the current shared base branch. Use a
short name that describes the work:

```powershell
git switch main
git pull --ff-only
git switch -c feat/ingestion-reconciliation
```

Use `feat/` for features, `fix/` for bug fixes, `docs/` for documentation,
`test/` for tests, and `chore/` for maintenance. Codex-created branches use
`codex/`. Keep unrelated changes on separate branches.

Push only to a branch you own. Do not push directly to `main` or to another
contributor's branch. Bring changes into `main` through a reviewed pull
request.

## Make focused commits

Use a short subject in the form `type: summary`, such as:

```text
feat: add ingestion dispatch retry
fix: preserve bulletin revision identity
docs: clarify local bootstrap steps
```

Prefer one purpose per commit. Before committing, inspect `git status` and
`git diff --staged` so generated files, credentials, model weights, and
source datasets do not enter the commit.

## Local setup for contributor checks

From the repository root, install the locked Python dependencies:

```powershell
Copy-Item .env.example .env
uv python install 3.12
uv sync --project workers --frozen
```

The full local runtime setup is in the [README](README.md#get-started-locally).
For database and Redis integration tests, use the separate disposable Compose
project below. Its test runner sets `TEST_DATABASE_URL` and `TEST_REDIS_URL`;
running the same tests on the host without those variables skips them.

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Use this exact project name. The test database is isolated from the local
development database and uses temporary storage. The last command removes
only the test project's resources. Check the pytest summary to confirm the
integration tests ran rather than being skipped.

## Check your change

Run the checks that cover the files you changed. For Python worker changes,
the standard checks are:

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests
uv run --project workers ruff check workers
uv run --project workers ruff format --check workers
git diff --check
```

Run the integration suite above when changing PostgreSQL, Redis, bootstrap,
ingestion, or dispatch behavior. Keep automated tests independent of the live
PHIVOLCS website; use sanitized fixtures. Do not point
`TEST_DATABASE_URL` at the development database: the test fixtures migrate
and truncate their database.

## Open a pull request

Push your branch and open a pull request into the shared base branch. In the
description, include:

- What changed and why.
- How you verified it, including commands and results.
- Any setup needed to reproduce the behavior.
- Any known limitation or follow-up work.

Review the diff before requesting review. Keep secrets, `.env` files,
model artifacts, raw source snapshots, and local readiness manifests out of
Git. Address review feedback on your own branch, then wait for the required
review before merging.
