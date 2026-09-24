# Prediction Worker release check for issue #21

Measured on 2026-09-24 from base commit `fc558cc` with the issue #21
supersession test added. This is a local baseline for the ignored, read-only
`SEIS 1.0.1` bundle. It is not a VPS capacity measurement or latency target.

## Coverage

The dedicated PostgreSQL and Redis Compose suite ran 167 integration cases:
**165 passed, 2 expected skips**. The standard image omits the ignored model
bundle, so the two real-bundle cases ran separately in the prediction image and
both passed.

| Requirement                                    | Proof                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Queue to forecast and M1+ live automatic alert | `test_published_v1_command_is_consumed_by_a_running_worker` consumes a Redis command; `test_prediction_command_completes_once_and_stops_dispatch` checks forecast, successful job and attempt, stopped prediction dispatch, one alert job, alert dispatch, and audit.                                                                             |
| Duplicate delivery and fencing                 | `test_duplicate_queue_delivery_to_two_replicas_keeps_one_attempt_and_forecast` uses two live Celery workers and checks one attempt and forecast. `test_expired_attempt_is_abandoned_and_stale_completion_is_audited` rejects the old execution token.                                                                                             |
| Retry exhaustion and recovery                  | `test_runtime_failures_retry_on_schedule_then_stop_with_stable_ids`, `test_fourth_expired_attempt_is_abandoned_and_job_stops`, `test_prediction_dispatch_recovery_fences_live_lease_and_old_submission_token`, and `test_broker_loss_republishes_pending_prediction_without_replacing_dispatch` check retries, leases, and unchanged durable IDs. |
| Supersession                                   | `test_later_revision_forecast_supersedes_prior_forecast` checks that the new forecast points to the prior one while the prior row stays unchanged.                                                                                                                                                                                                |
| Alert suppression and uniqueness               | `test_backfill_and_expired_forecasts_create_no_alert` and `test_historical_revision_creates_no_alert` check suppression. `test_one_alert_job_is_allowed_per_forecast` in `test_database_constraints.py` checks the database uniqueness rule.                                                                                                      |
| Atomic rollback                                | `test_alert_dispatch_failure_rolls_back_forecast_completion` checks that a failed alert-dispatch insert leaves no forecast, alert, or audit and does not mark the job complete.                                                                                                                                                                   |
| Real bundle                                    | `test_real_seis_bundle_persists_known_forecast` checks release readiness, artifact hashes, native model loading, inference, and persisted known outputs.                                                                                                                                                                                          |

These cases live in `workers/tests/integration/test_prediction_worker.py` unless
another file is named above. The runbook for starting, checking, stopping,
and recovering existing durable work is in `README.md` under "Prediction Worker
operations."

## Benchmark

The benchmark runs ten real-bundle jobs through the prediction Redis queue for
each configuration, with one Celery child per replica. It records completion
when PostgreSQL marks each job `succeeded`. Throughput spans the first publish
to the last observed completion. p95 is the slowest of ten per-job
publish-to-completion times. RSS readings are per process and may include
shared pages.

| Replicas | Throughput (jobs/s) | p95 completion (s) | Retry attempts | Parent RSS (MiB) | Child peak RSS (MiB) |
| -------: | ------------------: | -----------------: | -------------: | ---------------- | -------------------- |
|        1 |               4.967 |              1.946 |              0 | 203.6            | 165.4                |
|        2 |               9.803 |              1.003 |              0 | 205.4, 205.4     | 164.3, 165.1         |

Environment: Windows host build 26200 with 16.5 GB physical RAM; Docker
Desktop Engine 29.5.2, Compose 5.1.3; Linux x86_64 Docker VM with 12 CPUs and
7,992,922,112 bytes assigned. The isolated services use PostgreSQL
`16.15-bookworm`, Redis `7.4.11-bookworm`, and Python 3.12.14. The model bundle
was mounted read-only at `/workspace/model-artifacts`. The benchmark runs in
the integration test container, not the release Compose service with its
512 MiB container limit. Measure memory and completion time on the VPS before
choosing a steady replica count. One ten-job run per configuration cannot show
load variance or sustained throughput.

To reproduce from the repository root with the ignored bundle present:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml --profile prediction-smoke run --build --rm prediction-smoke-runner pytest --config-file workers/pyproject.toml workers/tests/integration/test_prediction_worker.py -k 'test_real_seis_bundle_persists_known_forecast or test_real_seis_replica_benchmark' -s
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

The second command reported `2 passed, 22 deselected` and printed
`PREDICTION_REPLICA_BENCHMARK` with the values above. The full integration
suite used the `test-runner` command in `CONTRIBUTING.md` before this run.
