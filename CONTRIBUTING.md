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
for tests, and `chore/` for maintenance.
Push only to a branch you own. Changes reach `main` through a reviewed pull
request.

Read [GLOSSARY.md](GLOSSARY.md) before changing domain behavior. Read the
relevant [ADRs](docs/adr/) before changing behavior, architecture,
dependencies, data, queues, runtime, deployment, or interfaces. For changes to
schema, ownership, or module boundaries, consult the matching specification in
[docs/system-design](docs/system-design/).

## Local setup for contributor checks

Run the commands below in PowerShell from the repository root.

Install [`uv`](https://docs.astral.sh/uv/) first. Unit tests and lint checks do not need `.env` or running containers.

### Prepare Python

1. Install the Python version used by the workers.

```powershell
uv python install 3.12
```

2. Install worker dependencies from the lockfile, keeping their recorded versions.

```powershell
uv sync --project workers --frozen
```

You can now run the Python tests and lint commands under [Check before every push](#check-before-every-push).

### Run database and Redis checks

For integration tests, start Docker with Compose v2. Run these three steps in order.
Integration tests check the application against PostgreSQL and Redis in a separate, disposable environment.

Use the exact project name below. Test fixtures migrate and clear data; never point them at a development or production database.

1. Start the test database and Redis in the background. `--wait` waits until both services are healthy.

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
```

2. Build the test image and run the integration suite. `--rm` removes the runner container after it exits.

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
```

Check the pytest summary for failures and confirm integration tests ran.
The runner supplies its test database and Redis URLs. Host pytest without those URLs skips integration tests.

3. After inspecting the results, remove the disposable containers, network, and volumes. This command targets only the named test project.

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```


The standard runner skips two real-model tests because it excludes model artifacts and prediction dependencies.
If the approved `SEIS 1.0.1` bundle is available, also run [the real-model checks](docs/operations/local-runtime.md#real-model-integration-checks).
Report those results separately; standard-runner skips do not mean your local model bundle is missing.

## Check before every push

Run checks that match your change:

| Change                                                        | Required check                                            |
| ------------------------------------------------------------- | --------------------------------------------------------- |
| Any change, including docs                                    | Inspect the diff and run the Git whitespace checks below. |
| Python worker code or tests                                   | Run the worker tests and Ruff checks below.               |
| PostgreSQL, Redis, bootstrap, ingestion, or dispatch behavior | Also run the isolated integration suite above.            |

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests
uv run --project workers ruff check workers database
uv run --project workers ruff format --check workers database
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
