# Issue #13 local enablement execution report

Date: 2026-09-19 Asia/Manila. Tested implementation commit: `6bdb4ff` on
`codex/issue-13-local-proof`. Parent issue: #6. Prerequisite issue #12 was
pushed and closed before this work.

## Deterministic proof

`workers/tests/integration/test_local_enablement.py` runs against the disposable
`quakestrike-data-ingestion-test` PostgreSQL and Redis project. It imports the
sanitized preserved snapshot, runs the real bootstrap readiness gate, invokes
one real Beat schedule entry, and observes one new scheduled run and ingestion
dispatch. The shared Dispatcher puts the identifier-only command on the real
Redis ingestion queue. The test reads that command and passes it to the
production Data Ingestor command handler. The source adapter parses sanitized
catalog and detail HTML without an external HTTP request.

The fixture contains one new M4.2 event, one correction to an existing event,
one repeated bulletin, and one rejected numeric row. The scheduled run finishes
with 3 checkpointed inputs, 1 inserted event, 1 new revision on the original
event ID, and 1 rejected row. One new immutable prediction snapshot, job, and
dispatch are committed. The Dispatcher publishes a version 1 prediction
command containing only `message_version`, `dispatch_id`, `job_id`, and
`correlation_id` to the prediction queue. Replaying the ingestion command
leaves run counters and durable identity counts unchanged. The test checks the
snapshot hash against canonical feature serialization and uses a controlled
clock for dispatch timing.

The main test consumes the real Redis message and calls the production handler
directly. Existing integration tests exercise a Celery worker's Redis
redelivery, processing retries, lease recovery, and stale token fencing. These
remain separate so a failure identifies the broken contract. The main test
does not start a Prediction Worker; inference is deferred.

| Contract | Test evidence |
| --- | --- |
| Beat tick, one run and dispatch, Redis routing, source parsing, revision, snapshot, prediction command, replay | `test_local_enablement.py` |
| Retry delays, exhausted dispatch, expired claims, stale submission tokens | `test_ingestion_dispatch.py`, `test_scheduled_dispatch.py` |
| Processing lease recovery, stale worker fencing, duplicate command, Celery redelivery | `test_transactions.py`, `test_data_ingestor_consumer.py` |
| Bootstrap integrity, resumability, rejected rows, usable history | `test_bootstrap.py` in unit and integration suites |
| Migration, release registration, readiness failures, read-only startup, operator actions | `test_initial_migration.py`, `test_model_release_registry.py`, `test_operator_startup.py`, `test_startup_gates.py`, `test_operator_sequence.py` |
| Queue contracts and bounded structured logs | `test_queue_contracts.py`, `test_logging.py`, scheduler and dispatcher unit tests |

## Commands and results

Run from the repository root. The exact isolated service project prevents the
test fixtures from migrating or truncating the retained local database.

```powershell
uv run --project workers pytest --config-file workers/pyproject.toml workers/tests -q
uv run --project workers ruff check workers
uv run --project workers ruff format --check workers
git diff --check
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration -q
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Host pytest: **252 passed, 124 skipped**. The skipped integration tests lack
`TEST_DATABASE_URL` and `TEST_REDIS_URL` on the host; two more skips are for
unavailable Windows symlink creation. The isolated Compose summary was **122
passed**, with no integration skips. Ruff lint and format checks passed after
formatting one preexisting line in `test_operator_sequence.py`; `git diff
--check` passed. The focused end-to-end test passed after setting its controlled
clock to 2099, so real calendar progression cannot make due dispatches appear
early to the test.

## Retained local readiness inspection

The #12 operator sequence had already migrated, registered SEIS 1.0, and
bootstrapped this retained database. Issue #13 did not rerun those mutating
actions. This inspection restarted only PostgreSQL and Redis, ran read-only
verification, queried durable records, and stopped the two containers without
removing their volumes:

```powershell
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait postgres redis
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike verify-model-release
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml run --rm release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
Get-FileHash -Algorithm SHA256 bootstrap-snapshots/source-snapshots/5131d8e1c61d54deca6c585164fa7df54e277f6e7e2dc0ebba48687f2086746c.source.json
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml exec -T postgres psql -U quakestrike -d quakestrike -At -F ',' -c "SELECT (SELECT count(*) FROM earthquake_events), (SELECT count(*) FROM earthquake_event_revisions), (SELECT count(*) FROM prediction_jobs), (SELECT count(*) FROM job_dispatches WHERE prediction_job_id IS NOT NULL), (SELECT count(*) FROM job_dispatches WHERE ingestion_run_id IS NOT NULL), (SELECT count(*) FROM ingestion_runs), (SELECT count(*) FROM ingestion_run_inputs); SELECT r.run_id, r.trigger_type, r.status, r.attempt_count, r.events_found, r.events_inserted, r.events_revised, r.events_unchanged, r.events_rejected, d.dispatch_id, d.status, d.attempt_count FROM ingestion_runs r LEFT JOIN job_dispatches d ON d.ingestion_run_id=r.run_id WHERE r.trigger_type <> 'backfill' ORDER BY r.requested_at DESC LIMIT 5; SELECT status,count(*) FROM job_dispatches WHERE prediction_job_id IS NOT NULL GROUP BY status ORDER BY status;"
docker inspect --format '{{json .HostConfig.LogConfig}} {{json .State.Health.Status}}' infrastructure-postgres-1 infrastructure-redis-1
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml down
```

| Evidence | Observed result |
| --- | --- |
| Migration | Alembic `20260918_06`, required revision matched |
| Release | SEIS 1.0 ID `2f532893-7a25-4f18-814c-91d66f38dac4`, manifest `seis-1.0/manifest.json`, SHA-256 `39e1808fac8c511d02b84c3f7f1c2787e7237a152c29daf0c1c23e156481dc0f`; all 8 listed artifact hashes verified |
| Source snapshot | SHA-256 `5131d8e1c61d54deca6c585164fa7df54e277f6e7e2dc0ebba48687f2086746c`, independently checked against the preserved file bytes |
| Source coverage | 2026-08-01 00:00 through 2026-09-19 00:00 Manila; retrieved 2026-09-18 20:31:33; available through 2026-09-18 19:42; first prediction anchor 2026-09-01 00:00 |
| Backfill run | `e58cf433-5eaf-445b-b13e-103414a00bb2`, succeeded; 3,243 accepted and checkpointed inputs, 3,243 inserted events, 0 rejected rows |
| Database counts | 3,243 events; 3,243 revisions; 3,243 input checkpoints; 2,612 prediction jobs and prediction dispatches; 1 ingestion dispatch and 2 total ingestion runs including backfill |
| History readiness | All 5 startup gates ready; 377 history observations and 377 usable observations for the required seven-day anchor window |
| Prediction dispatch state | 2,330 enqueued and 282 pending |
| Rejection and enrichment diagnostics | Backfill rejected rows: 0. Manifest records 24 `DETAIL_FETCH_FAILED` and 2 `DETAIL_ORIGIN_UNKNOWN` diagnostics without rejecting those catalog rows. |

The manual poll from the #12 handoff remains run
`0060aea1-953b-4e23-9c1f-825c0b955b48` with dispatch
`44511e3a-449e-4c26-ae3d-92e7d0ff1730`. Both were still `pending` with zero
attempts and zero run counters at this read-only inspection. No live PHIVOLCS
reconciliation or live prediction dispatch is claimed for that run. The
fixture-based proof is the completion gate for #13.

## Operations and limits

The README gives the explicit initialization and startup order, readiness
failure behavior, separate immediate poll, inspection queries, and bounded
`docker compose logs` command. A poll result establishes durable work, not
completed ingestion. Operators must retain the ignored hash-addressed source
snapshot, readiness manifest, and model package through handoff and archive
them outside Git. They contain the reproduction evidence; rotating Docker logs
do not. The local PostgreSQL and Redis containers inspected here were healthy
and used Docker's `local` driver with `max-size=20m` and `max-file=5`. Compose
worker health checks and the same bounded logging settings remain unchanged.

Prediction inference and forecasts, automatic alerts and SMS, public APIs and
web apps, public edge routing, and production monitoring remain outside #13.
The retained manual poll still needs an operational follow-up when consumers
are deliberately started again; this ticket's automated proof does not depend
on the live website or that backlog.
