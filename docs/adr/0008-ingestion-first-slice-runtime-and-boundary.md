# Define the ingestion first-slice runtime boundary

**Status**: accepted

The first deployment uses separate `scheduler-beat`,
`scheduler-dispatcher`, and `data-ingestor` containers. Exactly one Beat
replica owns the five-minute schedule. A scheduled tick does not create a
second logical run while an existing run is pending, running, or waiting for
retry. Queue dispatch and ingestion processing may recover expired claims, but
they preserve the existing run and dispatch identities.

The dispatcher and ingestor use bounded retries with exponential backoff.
Polling reconciles the complete current PHIVOLCS page, while archive traversal
and explicit backfill remain separate capabilities. A valid newly inserted or
revised event may create one prediction job for the configured model release;
unchanged or rejected events do not create new prediction work. The initial
migration includes `ingestion_runs`, `earthquake_events`,
`earthquake_event_revisions`, `model_releases`, `prediction_jobs`, and
`job_dispatches`, with the authoritative constraints and indexes required by
their contracts.

Prediction work requires a versioned input contract and an immutable,
validated snapshot. Placeholder snapshots are not allowed. A model release
must be explicitly approved before production prediction commands can be
enabled; current development artifacts are not treated as approved releases.

## Amendment: project production target

For this project, the selected `SEIS 1.0` runtime release is treated as the
production target for implementation and demonstration. The earlier approval
gate in this ADR does not block production prediction-command creation for the
first slice. The immutable manifest, artifact-hash verification, explicit
release configuration, and fixed model targets remain mandatory. Prediction
execution and alert delivery remain outside this ingestion slice.

## Amendment: stage the alert dispatch foreign key

The first migration still creates the six first-slice tables named above.
`job_dispatches` retains its nullable `alert_job_id` column so its final shape
remains visible, but the migration omits the FK to `alert_jobs` because that
parent table is outside the first slice. A temporary
`CHECK (alert_job_id IS NULL)` prevents dangling alert targets. The existing
exactly-one-target check continues to permit only ingestion-run or
prediction-job dispatches in this stage.

The migration that later creates `alert_jobs` must add the
`job_dispatches.alert_job_id` FK with `ON UPDATE RESTRICT` and
`ON DELETE RESTRICT`, then remove the temporary null-only check in the same
migration. The final schema must match
`docs/system-design/ERD/DATABASE-DESIGN.md`.
