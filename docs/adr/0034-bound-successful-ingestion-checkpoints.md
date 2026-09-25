# Bound ingestion checkpoints

**Status**: accepted

`ingestion_run_inputs` is PostgreSQL retry progress for rows that require
processing, including changed and rejected rows. It is committed with the event
outcome when applicable. Scheduled runs count every distinct normalized input,
including rows proved unchanged without a checkpoint. On scheduled success,
the summary and deletion of that run's checkpoints commit together. A failure
leaves the checkpoints for retry. Skipped visible events receive one fenced
batch update to `last_seen_run_id`. Manual and backfill successes retain their
checkpoints initially.

The bounded host job drains successful scheduled checkpoints left by the prior
policy, regardless of age. It also removes checkpoints from any terminal run
(`succeeded`, `failed`, or `cancelled`) after 30 days from `finished_at`. It
never age-deletes pending, running, or retry-wait checkpoints. Requeueing a
failed backfill inside 30 days retains its original run and progress; after
that, recovery creates a new logical run from the preserved snapshot. The
requeue and cleanup paths take the same PostgreSQL advisory lock so they cannot
race.

The job runs hourly outside Celery Beat. Each transaction deletes at most 5,000
input rows; one invocation performs at most 20 batches. It shares the host
maintenance lock with PostgreSQL backup and restore-test jobs and records its
result in `maintenance_runs`. The socket-only `quakestrike_maintenance` role
receives `SELECT` on `ingestion_runs` and `SELECT, DELETE` on
`ingestion_run_inputs`, with no write grant on other business tables.

The run summary remains the historical outcome after its detailed checkpoints
expire. This does not authorize deleting event, revision, forecast, run summary,
catalog evidence, or audit rows. PostgreSQL autovacuum reuses deleted-row
space; physical table files need not shrink immediately. Monitor retained row
count, relation size, cleanup failures, and disk usage.

At approximately 1,575 inputs every five minutes, selective reconciliation
avoids most scheduled checkpoint inserts. [ADR 0033](0033-reuse-stored-live-bulletin-details.md)
also reduces repeated detail-page requests.
