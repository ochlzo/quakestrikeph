# Prediction Worker implementation handoff

Date: 2026-09-23

This handoff tracks the Prediction Worker implementation sequence. Issue #15's
schema foundation is implemented on `app/prediction-worker`; the worker runtime
and later tickets remain unfinished.

## Where the work lives

The authoritative parent specification is GitHub issue [#14: Spec: Prediction Worker](https://github.com/ochlzo/quakestrikeph/issues/14).

The implementation tickets are:

| Issue | Title | Blocked by |
| --- | --- | --- |
| [#15](https://github.com/ochlzo/quakestrikeph/issues/15) | Correct the forecast output contract and persistence model | Implemented on this branch |
| [#16](https://github.com/ochlzo/quakestrikeph/issues/16) | Execute one prediction job end to end | #15 |
| [#17](https://github.com/ochlzo/quakestrikeph/issues/17) | Run the real SEIS 1.0.1 model bundle | #16 |
| [#18](https://github.com/ochlzo/quakestrikeph/issues/18) | Create automatic alert work atomically with forecast completion | #16 |
| [#19](https://github.com/ochlzo/quakestrikeph/issues/19) | Retry and recover prediction work durably | #16 |
| [#20](https://github.com/ochlzo/quakestrikeph/issues/20) | Operate multiple Prediction Worker replicas | #17, #19 |
| [#21](https://github.com/ochlzo/quakestrikeph/issues/21) | Prove throughput and release readiness | #17, #18, #19, #20 |

All issues are children of #14 and have the `ready-for-agent` label. GitHub stores the blocking relationships natively.

The local draft spec and local ticket files were intentionally removed after publication. Do not look for a second copy under `docs/specs/` or `.scratch/`. Use the GitHub issues above.

## First step in a new session

From the repository root, read:

```powershell
gh issue view 14 --repo ochlzo/quakestrikeph
gh issue view 15 --repo ochlzo/quakestrikeph
```

If `gh` is not on PATH, the installation used in the previous session was:

```text
C:\Program Files\GitHub CLI\gh.exe
```

Review and close issue #15 after this branch lands, then continue with issue #16.
Do not implement tickets whose blockers are still open. Use
`gh issue view <number> --repo ochlzo/quakestrikeph` to read the full body and
comments before coding.

## Settled product and architecture decisions

- The worker boundary includes prediction-job claiming, model inference, output validation, forecast persistence, automatic alert-job creation, dispatch creation, and the required system audit.
- SMS delivery, recipient resolution, provider calls, Backend APIs, public presentation, and alert delivery remain out of scope.
- PHIVOLCS Monitoring, forecast review, publication approval, operator alerts, and saved-pin matching were removed from the product scope. A valid forecast is available to the Bulletin without review.
- Every current, unexpired live M1+ forecast creates exactly one automatic alert job. The Alert Worker later compares the observed anchor magnitude with each user's alert trigger magnitude; backfill, historical, and expired work create no alert job.
- The worker consumes the existing versioned identifier-only prediction command from the separate prediction queue. PostgreSQL is the source of truth; Redis and Celery result storage are not business state.
- The real read-only `SEIS 1.0.1` bundle must work. Test doubles are for deterministic CI tests only.
- Existing pending prediction jobs are processed, including historical jobs whose forecast window has ended. Historical, backfill, expired, or otherwise ineligible jobs never create automatic alerts.
- Prediction retries are bounded to approximately 30 seconds, 2 minutes, and 10 minutes. Retry transient database and inference-runtime failures. Fail invalid snapshots, unsupported schemas, missing or hash-invalid artifacts, and invalid outputs without wasting retries.
- Each task has a configurable five-minute soft limit and six-minute hard limit inside a renewable 15-minute processing lease.
- Multiple identical worker containers are supported. Each runs Celery concurrency one. One replica is the local default. Scale-out is intended to improve throughput, not to introduce a custom coordinator.
- The first phase keeps historical and live jobs on one FIFO prediction queue. Do not add priority queues until measured backlog delay proves they are needed.
- Workers must be healthy before claiming jobs only after PostgreSQL, Redis, migration state, release registration, artifact hashes, and output-contract compatibility pass.

## Corrected forecast output contract

The model bundle supplies:

- `m1_probability`;
- `m4_given_m1`;
- `m5_given_m4`;
- expected M1+ count;
- median activity radius;
- maximum-magnitude q05, q50, and q95.

The forecast persistence contract must use matching names. Correct the existing planned q10/q50/q90 and p90-radius names in place. Do not add a second parallel set of columns and do not silently relabel model outputs.

Compose probabilities as:

```text
P(M1+) = m1_probability
P(M4+) = P(M1+) * m4_given_m1
P(M5+) = P(M4+) * m5_given_m4
```

Reject non-finite values, values outside `[0, 1]`, or results that violate `P(M5+) <= P(M4+) <= P(M1+)`. Apply the manifest's q05/q50/q95 ordering and floor-at-M1 post-processing. Forecast windows start at the linked revision event time and span exactly 24 elapsed hours.

## Important repository facts

Already implemented:

- Prediction command contract and parser: `packages/contracts/queue/prediction-command.v1.schema.json` and the Python queue contract binding.
- Prediction queue routing and shared durable Dispatcher.
- Immutable feature snapshots, prediction jobs, model-release registration, manifest validation, and artifact hash verification.
- Prediction attempts, forecasts, automatic alert jobs, their dispatch FK, and audit persistence from issue #15.
- Immutable manifests: legacy `workers/model-release-manifests/seis-1.0/manifest.json` and selected `workers/model-release-manifests/seis-1.0.1/manifest.json`.
- Ignored selected artifacts: `model-artifacts/seis-1.0.1/`, mounted read-only for the real smoke test.

Not implemented yet:

- Prediction consumer/task registration and prediction application use case.
- Prediction repositories, claim handling, and lease renewal.
- Automatic alert-job completion transaction and system-audit write orchestration.
- Prediction-specific retry/recovery logic in the Dispatcher.
- Prediction-worker image, Compose service, health check, runtime dependencies, and replica operation.
- Prediction worker tests, real-bundle smoke test, and throughput benchmark.

## Binding design references

Read these before changing behavior or schema:

- `CONTEXT.md`
- `docs/system-design/ARCHITECTURE/ARCHITECTURE.md`
- `docs/system-design/ERD/DATABASE-DESIGN.md`
- `docs/adr/0009-immutable-model-releases-and-ingestion-feature-snapshots.md`
- `docs/adr/0011-python-runtime-and-durable-worker-operations.md`
- `docs/adr/0012-queue-topology-and-operational-safeguards.md`
- `docs/adr/0016-atomic-event-processing-and-release-registration.md`
- `docs/adr/0019-explicit-startup-and-runtime-configuration.md`
- `docs/adr/0021-live-feature-contract.md`
- `docs/adr/0022-idempotent-revisions-and-bootstrap-gates.md`
- `docs/adr/0024-fenced-durable-ingestion-dispatch.md`
- `docs/adr/0025-explicit-local-runtime-enablement.md`

The written ERD and ADRs control over diagrams. Updating ERD/DFD image files is deferred.

## Verification commands

For Python worker changes, use the repository's normal checks:

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests
uv run --project workers ruff check workers
uv run --project workers ruff format --check workers
```

For PostgreSQL, Redis, bootstrap, or dispatch changes, run the isolated integration suite documented in `CONTRIBUTING.md` using the `quakestrike-data-ingestion-test` Compose project. Do not point the test environment at the development database.

The final ticket must include the real-artifact smoke test and a two-worker benchmark reporting throughput, p95 completion time, and memory observations. No fixed production latency SLA has been promised before that measurement.

## Repository state and branch note

The working tree was clean at handoff on `main`. The temporary remote branch `codex/issue-13-local-proof` was deleted after its commit had already landed in `main`. No implementation branch exists yet. Create or use the repository's normal `codex/` branch convention when starting implementation work.
