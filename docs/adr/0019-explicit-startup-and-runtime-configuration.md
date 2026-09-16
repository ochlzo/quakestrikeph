# Make initialization explicit and configuration typed

**Status**: accepted

Services use typed environment-backed settings and a committed `.env.example`.
`DATABASE_URL` and `REDIS_URL` are required at startup; deployment secrets and
`.env` files remain outside Git. PHIVOLCS URL, polling interval, model release
ID, artifact directory, retry limits, and logging settings are configurable
without changing application code.

Local Compose provides pinned PostgreSQL 16 and Redis 7 images. The exact
patch tags are selected from current official documentation before the first
installation; floating `latest` tags are not used. Python services run locally
through `uv` during development.

Initialization is an explicit operator workflow: apply Alembic migrations,
verify and register the normalized model release, run the resumable bootstrap,
verify coverage, then start the dispatcher and ingestor before enabling the
five-minute Beat schedule. Service startup does not silently run migrations,
bootstrap data, or mutate the model registry.

The registered application release uses the human-facing version label
`SEIS 1.0`. Its normalized runtime manifest must still record the exact
training package `balanced-selection-anchor-exploratory-01`, artifact paths,
target mappings, feature lists, provenance, and hashes. The label does not
change the package's provisional development status.

The three initial worker services share one application image and use distinct
commands. Each service also has a read-only health check for database
connectivity, migration state, and Redis connectivity.

Parser tests use copied, sanitized PHIVOLCS HTML fixtures and expected
normalized values. CI never depends on the live PHIVOLCS website. Live raw HTML
is not stored in PostgreSQL or the application runtime store; preserved
raw/enriched source snapshots are used only for bootstrap and investigation.

## Amendment: project production posture

For this project, `SEIS 1.0` is the production runtime release used by the
initial ingestion slice. The earlier provisional-development wording is not a
startup or prediction-command gate. Explicit registration, immutable manifest
verification, artifact-hash verification, and the exact selected targets are
still required before services start processing prediction work.
