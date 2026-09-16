# Commit event processing atomically

**Status**: accepted

For each accepted event, one PostgreSQL transaction locks or creates the
stable event identity, appends a changed revision when needed, and creates any
eligible prediction job with its `job_dispatches` row. The prediction input
snapshot must already be complete and hashed. Redis publication happens only
after the transaction commits. Run counters are checkpointed separately and
retries do not double-count the same logical input.

Rows rejected for identity or validation problems increment
`ingestion_runs.events_rejected` while other valid rows continue. A valid
source page with no event rows is treated as a failed, suspicious poll. A
conflicting duplicate bulletin ID also fails the logical run. These failures
must not mark unseen events as absent or delete historical data.

Prediction work requires a valid source URL, at least one PHIVOLCS source
identifier, a validated event revision, and a complete feature snapshot. The
release registry is populated from a normalized runtime manifest copied into
the application workspace. The manifest and local model files are hash
verified before the `model_releases` row is registered; training-repository
paths are not runtime dependencies.
