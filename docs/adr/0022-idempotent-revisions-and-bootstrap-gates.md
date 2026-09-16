# Preserve enrichment history and gate runtime readiness

**Status**: accepted

When a later detail-page request changes a persisted source field, including
origin, timestamp precision, or canonical source URL, the ingestor appends a
new event revision rather than mutating the previous revision. If the resulting
feature snapshot is identical, a new revision can still create eligible prediction
work because `event_revision_id` is part of the uniqueness key. Duplicate
deliveries for the same revision, model release, and snapshot reuse the existing
job. This constraint does not deduplicate work across distinct event revisions.

Feature construction runs inside the event-level PostgreSQL transaction that
locks the event and creates the prediction job. Prediction-job uniqueness is
enforced across `event_revision_id`, `model_release_id`, and
`input_snapshot_hash`; a duplicate delivery is therefore a safe no-op or
existing-job observation.

Services require an explicit `MODEL_RELEASE_ID` and verify the immutable
`SEIS 1.0` manifest and artifact hashes before processing. A run that reaches
its retry limit is recovered by requeueing its existing logical run and
dispatch records through an operator CLI, not by creating replacement
identities.

The bootstrap command is complete only after validating source snapshot
integrity, row counts, identifiers, and the seven-day history prerequisite.
Beat remains disabled until those checks pass.
