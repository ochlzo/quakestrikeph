# Bound successful scheduled ingestion checkpoints

**Status**: accepted

`ingestion_run_inputs` is retry progress for one logical run. Completed
scheduled runs no longer need those per-input checkpoints for retry. Keep their
durable `ingestion_runs` counters, catalog evidence, event revisions, and audit
records. A host maintenance job deletes only checkpoints whose parent run is
`scheduled`, `succeeded`, and finished more than 24 hours ago. It never deletes
checkpoints from pending, running, retrying, failed, cancelled, manual, or
backfill runs. The bootstrap readiness and operator recovery paths therefore
keep their evidence.

The job runs hourly outside Celery Beat. Each transaction deletes at most 5,000
input rows; one invocation performs at most 20 batches. It shares the host
maintenance lock with PostgreSQL backup and restore-test jobs and records its
result in `maintenance_runs`. The socket-only `quakestrike_maintenance` role
receives `SELECT` on `ingestion_runs` and `SELECT, DELETE` on
`ingestion_run_inputs`, with no write grant on other business tables.

The run summary remains the historical outcome after its detailed checkpoints
expire. This changes the database design's implied long-term availability of
per-input checkpoints for successful scheduled runs. It does not authorize
deleting business audit logs, source coverage evidence, revisions, forecasts,
or other run types. PostgreSQL autovacuum reuses deleted-row space; physical
table files need not shrink immediately. Monitor retained row count, relation
size, cleanup failures, and disk usage.

At approximately 1,575 inputs every five minutes, the 24-hour window keeps
about 454,000 successful scheduled checkpoints, plus any protected run types.
This policy bounds retained checkpoints; it does not reduce their insertion
rate. [ADR 0033](0033-reuse-stored-live-bulletin-details.md) separately reduces
the dominant repeated detail-page requests.
