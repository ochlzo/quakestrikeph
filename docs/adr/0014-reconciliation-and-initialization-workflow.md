# Reuse the tested reconciliation workflow

**Status**: accepted

The normalizer coalesces repeated rows with the same bulletin identifier when
their normalized values agree. If the same bulletin identifier appears with
conflicting values, the logical ingestion run fails rather than choosing one
row.

An ambiguous source-identity candidate is rejected for that bulletin and
counted in `ingestion_runs.events_rejected`; other valid rows in the same page
continue through the run. The ingestor never creates a new event merely to
avoid an ambiguous merge.

For a new bulletin that may revise an existing event, the fallback uses the
same source group and the old app's tested coordinate and magnitude checks:
latitude and longitude differences no greater than `0.25` degrees, magnitude
difference no greater than `1.0`, and exactly one candidate. These values are
explicit policy constants and require fixture coverage. A timestamp alone or
an identical observation tuple is not an identity key.

The bootstrap is an explicit resumable CLI operation. It uses the same
normalization and reconciliation path as live ingestion, records one
`backfill` run, and is completed after migrations and before Beat is enabled.
It does not create a second CSV-backed runtime store.

The Python project uses `uv`, a `pyproject.toml`, and a committed lock file.
Local development starts PostgreSQL and Redis through Docker Compose while the
Python services run locally for straightforward debugging. The application is
one Python package with separate `scheduler`, `data_ingestor`, `domain`, and
`infrastructure` subpackages. Deployment can still place those modules in
separate containers.
