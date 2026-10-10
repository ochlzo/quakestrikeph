# Contributing to QuakeStrike PH

Follow this guide before pushing any change from your machine, including code,
tests, documentation, and configuration. If you are new to the project, start
with the [README](README.md) for the current scope and repository map. The
[local runtime guide](docs/operations/local-runtime.md) is for running the
complete worker pipeline.

## Start on your own branch

Update `main` and create a branch for one focused change:

```powershell
git switch main
git pull --ff-only
git switch -c feat/ingestion-reconciliation
```

Use `feat/` for features, `fix/` for fixes, `docs/` for documentation, `test/`
for tests, and `chore/` for maintenance. Codex-created branches use `codex/`.
Push only to a branch you own. Changes reach `main` through a reviewed pull
request.

Read [CONTEXT.md](CONTEXT.md) before changing domain behavior. Read the
relevant [ADRs](docs/adr/) before changing behavior, architecture,
dependencies, data, queues, runtime, deployment, or interfaces. For changes to
schema, ownership, or module boundaries, consult the matching specification in
[docs/system-design](docs/system-design/).

## Local setup for contributor checks

For Python worker checks, install [`uv`](https://docs.astral.sh/uv/) and the
locked dependencies from the repository root:

```powershell
uv python install 3.12
uv sync --project workers --frozen
```

The unit tests and lint checks do not need `.env` or the full runtime. For
database and Redis integration tests, install Docker with Compose v2 and run
this disposable test project from the repository root:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Use this exact project name. The test runner sets `TEST_DATABASE_URL` and
`TEST_REDIS_URL`; host pytest without them skips integration tests. Confirm the
pytest summary shows that integration tests ran. The fixtures migrate and
truncate their database, so never point `TEST_DATABASE_URL` at a development
database. The final command removes only the test project's resources.

The standard `test-runner` does not mount model artifacts or install the
prediction dependencies. It skips two real-model tests by design. These skips
do not establish that the model bundle is missing from the host. If the approved
`SEIS 1.0.1` bundle is available locally, also run both checks with
[`prediction-smoke-runner`](docs/operations/local-runtime.md#real-model-integration-checks).
Report standard integration results and real-model results separately.

## Check before every push

Run checks that match your change:

| Change | Required check |
| --- | --- |
| Any change, including docs | Inspect the diff and run the Git whitespace checks below. |
| Python worker code or tests | Run the worker tests and Ruff checks below. |
| PostgreSQL, Redis, bootstrap, ingestion, or dispatch behavior | Also run the isolated integration suite above. |

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests
uv run --project workers ruff check workers
uv run --project workers ruff format --check workers
```

The Python commands apply when you change worker code or tests. Keep automated
tests independent of the live PHIVOLCS website; use sanitized fixtures.

Before committing, check both unstaged and staged changes:

```powershell
git status --short
git diff --check
git diff --cached --check
git diff
git diff --cached
```

Review the actual files and contents for secrets, `.env` files, model weights,
raw source snapshots, generated readiness manifests, and unrelated changes.
After committing, check `git status --short` again before pushing.

## Commit, push, and open a pull request

Use a short commit subject in the form `type: summary`, for example
`fix: preserve bulletin revision identity` or
`docs: clarify local bootstrap steps`. Prefer one purpose per commit.

Push your branch with `git push -u origin HEAD` and open a pull request into
`main`. In its description, state what changed and why, list the verification
commands and results, note any setup needed to reproduce the behavior, and
identify known limitations or follow-up work. Review the pull request diff
before requesting review. Address feedback on your branch and wait for the
required review before merging.
