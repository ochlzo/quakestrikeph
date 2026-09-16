# Use Python and Celery for ingestion

**Status**: accepted

QuakeStrike PH will implement the Data Ingestor and Ingestion Scheduler in
Python using Celery and Celery Beat. Beat will run as one dedicated scheduler
process or container, separate from the Data Ingestor worker containers. This
preserves the existing Python scraper and reconciliation work, aligns with the
Python prediction runtime, and avoids adding Node.js solely for scheduling. The
v2 architecture diagram already shows the Scheduler and Data Ingestor as
separate modules, so separating their processes does not require a diagram
change. The accepted dispatch decision in ADR 0004 adds a Scheduler or
dispatch-module database flow that must be shown when the source diagram and
handoff text are brought into alignment.
