# Persist ingestion runs before queue dispatch

**Status**: accepted

The Scheduler or dispatch module will create a pending `ingestion_runs` row and
its one `job_dispatches` row in the same database transaction. A dispatcher
will claim pending dispatches, publish the ingestion command to Redis, and
record whether submission was accepted. The Data Ingestor will claim and
process the existing logical run, preserving its run ID across retries. This
follows the authoritative schema specification and gives Redis submission a
durable recovery record. The v2 architecture diagram and handoff text will be
updated later to show this database flow.
