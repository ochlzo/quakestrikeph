# QuakeStrike PH implementation plan

Status: planning only

This document is the agreed execution plan for the first implementation slice.
No application code, migration, container configuration, model artifact, data
snapshot, or diagram is being created as part of this planning step. Work will
proceed in small checkpoints so the implementation can be reviewed before the
next phase starts.

## 1. Goal and first-slice boundary

The immediate goal is to initialize QuakeStrike PH and implement the ingestion
path defined by the architecture specification:

```text
PHIVOLCS website
        |
        v
Scheduler Beat -> durable ingestion run + dispatch -> Redis
                                                   |
                                                   v
                                         Data Ingestor worker
                                                   |
                              PostgreSQL event/revision state
                                                   |
                                                   v
                              immutable feature snapshot +
                              durable prediction job/dispatch
```

The first slice includes:

- a five-minute Celery Beat schedule;
- a durable scheduler dispatcher that publishes pending work to Redis;
- a Python data ingestor worker with one active ingestion execution at a time;
- PHIVOLCS current-catalog retrieval and mandatory bulletin-detail enrichment;
- validation, source-identifier reconciliation, event persistence, and event
  revisions;
- feature engineering for the approved live input contract;
- creation of immutable prediction input snapshots;
- durable prediction jobs and prediction-queue messages, even though the
  prediction worker is deferred;
- PostgreSQL and Redis health checks, structured operational logs, migrations,
  bootstrap tooling, and local verification.

The first slice does not include:

- prediction-worker inference or model scoring;
- alert-worker delivery or automatic public alerts;
- Backend HTTP APIs or client applications;
- automatic alerting for historical bootstrap rows;
- a CSV-backed runtime event store;
- scientific retraining, model selection, or changing the selected targets;
- production edge routing, off-VPS backups, restore drills, host disk alerts,
  or external uptime monitoring.

The selected models are the final targets for this project, and `SEIS 1.0` is
the production runtime release used by the first slice. The implementation may
publish prediction jobs for it after explicit registration and manifest/hash
verification. Prediction execution and alert delivery remain outside this
slice.

## 2. Repository and reference locations

The implementation repository is:

`C:\Projects\quakestrikeph\redo\quakestrikeph`

`C:\Projects` is a Windows junction to `D:\Projects`. We use the C: path in
commands and documentation, but files written through it are physically stored
on the D: drive.

The original design provenance is in:

`C:\Projects\SAM_Capstone\capstone`

Implementation authorities:

- `docs\system-design\ARCHITECTURE\ARCHITECTURE.md` — intended monorepo,
  module ownership, runtime, networking, security, and operations;
- `docs\system-design\ERD\DATABASE-DESIGN.md` — authoritative PostgreSQL
  tables, types, constraints, transactions, and ownership;
- `CONTEXT.md` — ingestion terms and invariants;
- `docs\adr\` — binding decisions and amendments.

Supporting references:

- `docs\system-design\ARCHITECTURE\system-architecture-layers.png` — current
  system and layered view;
- `docs\system-design\CFD-DFD\` — current context-flow and data-flow views;
- `C:\Projects\quakestrikeph\redo\quakestrikeph-scraper` — latest PHIVOLCS
  scraper and enrichment behavior;
- `C:\Projects\quakestrikeph\redo\quakestrikeph-training\baselines\attempt-2\stratified-baseline-02\chosen-models\balanced-selection-anchor-exploratory-01`
  — exact selected model package.

The source documents under `C:\Projects\SAM_Capstone\capstone` remain design
provenance. The repository architecture, database design, and accepted ADRs
control implementation when a source document differs.

## 3. Explicit decision record

These are the decisions already made during the grill. They are written here so
implementation choices remain traceable.

### Runtime and architecture

- Use Python and Celery because the existing implementation and model workflow
  are Python-based.
- Keep Celery Beat separate from the long-lived dispatcher and separate from
  the data ingestor process/container.
- Run three first-slice services: scheduler Beat, scheduler dispatcher, and
  data ingestor. They may share one Python image but use distinct commands.
- Use one active five-minute schedule. Do not create offset or consecutive
  schedulers, and do not allow overlapping logical ingestion runs.
- Beat creates durable pending work. The dispatcher claims and submits that
  work to Redis. The data ingestor claims the corresponding run from the
  database.
- Use a long-lived dispatcher polling loop, scanning approximately every five
  seconds, with a batch size of ten and a 60-second submission lease.
- Use PostgreSQL state and locking for active-run coordination; Redis is the
  broker, not the source of truth for run state.
- Use at-least-once delivery, late acknowledgement, durable database claims,
  and rejection of work after worker loss or lease expiry.
- Use separate ingestion and prediction queues. Do not create one queue per
  event.
- Queue commands contain stable database identifiers only. Both schemas carry
  `message_version`, `dispatch_id`, and `correlation_id`; ingestion commands
  also carry `run_id`, while prediction commands carry `job_id`. They do not
  contain full HTML, CSV rows, or large payloads.
- Use bounded retries for transient work, approximately three retry intervals
  of 30 seconds, two minutes, and ten minutes before marking the work failed.
- Use a 15-minute ingestor database lease with heartbeats and one ingestion
  concurrency slot.

### Database and identity

- Treat `docs\system-design\ERD\DATABASE-DESIGN.md` as the database contract.
- The initial migration covers the six tables needed by this slice:
  `ingestion_runs`, `earthquake_events`,
  `earthquake_event_revisions`, `model_releases`, `prediction_jobs`, and
  `job_dispatches`.
- Keep nullable `job_dispatches.alert_job_id`, omit its FK while `alert_jobs`
  is absent, and enforce a temporary `CHECK (alert_job_id IS NULL)`. The later
  alert-schema migration adds the FK and removes the temporary check.
- Use the named PostgreSQL lifecycle-status enums from the database contract.
  Create each enum before the first table that uses it.
- Remove `earthquake_events.source_event_key`. The stable identity is the
  internal `event_id`.
- Store `source_bulletin_id`, `source_event_group_id`, and `source_url` on
  event revisions, because source values can change between bulletins.
- `source_bulletin_id` is nullable but unique when present. The group ID is
  nullable and non-unique. Each revision must have at least one source
  identifier, and a valid source URL is required for accepted source rows.
- Canonicalize source identifiers to uppercase and preserve the canonical
  repaired source URL. Never fabricate an identifier or URL.
- Reconcile using this order:
  1. exact canonical bulletin ID;
  2. unambiguous group fallback using the old app's coordinate and magnitude
     thresholds;
  3. otherwise reject the row and count the rejection.
- The old fallback thresholds are latitude difference at most `0.25` degrees,
  longitude difference at most `0.25` degrees, and magnitude difference at
  most `1.0`. A group fallback must produce exactly one candidate.
- Do not use timestamps, timestamps plus group, or an identical observation
  tuple as a new identity.
- A row with a missing bulletin ID but a unique valid group match may append a
  revision with a nullable bulletin ID. A row with both identifiers missing is
  validated and counted but rejected.
- Duplicate identical bulletins are coalesced. A conflicting duplicate with
  the same bulletin ID fails the run. An ambiguous fallback rejects only that
  row while other valid rows continue.
- Store all valid new or revised events, regardless of magnitude. Create
  prediction work only for new or revised events with magnitude `>= 1.0` and
  sufficient history.
- Never clamp invalid numeric values. Parse into `Decimal`, validate physical
  bounds, quantize to the database scale, and reject invalid values.
- Normalize source time from Asia/Manila to `timestamptz` and preserve whether
  the source precision is minute or second.
- A later change to source detail metadata appends a new revision. Previous
  revisions are immutable. An unchanged normalized observation does not create
  a duplicate revision.

### Source retrieval and enrichment

- Port behavior from the latest scraper in
  `redo\quakestrikeph-scraper`, not the older combined application workflow.
- Fetch the complete current PHIVOLCS catalog page for each poll.
- Check every unique bulletin detail URL. Use the detail page to obtain
  `Origin` and seconds when available.
- Use the detail timestamp only when its date, hour, and minute agree with the
  catalog timestamp. If any of those differ, retain the catalog minute
  timestamp and record a diagnostic.
- If a detail page fails, is not HTML, or cannot be parsed, retain the catalog
  minute timestamp, leave origin null, record a diagnostic, and allow a future
  retry. Missing origin is not a prediction gate.
- Normalize recognized origin values to `TECTONIC`, `VOLCANIC`, or
  `TECTONIC-VOLCANIC`; unknown or blank values become null with a diagnostic.
- Reuse the current scraper's URL-repair rules, TLS verification, bundled
  certificate handling, retry classification, user agent, and response
  safeguards. Reject unrecognizable links rather than inventing URLs.
- Use one reused HTTP session and sequential detail requests with an initial
  configurable delay of `0.1` seconds.
- Retry only transient timeouts, connection resets, HTTP 429, and HTTP 5xx.
  Fail fast for HTTP 4xx, TLS failures, oversized responses, catalog-level
  structural/parser failures, and fatal identity conflicts. Row-level invalid,
  incomplete, ambiguous, or unmatched records are rejected and counted while
  other valid rows continue. Individual detail-page failures retain the valid
  catalog row with minute precision, nullable origin, and a diagnostic.
- Treat a structurally valid but empty PHIVOLCS page as suspicious and fail the
  transport/structural portion of the run rather than interpreting it as a
  complete empty catalog.

### Feature engineering and prediction dispatch

- Build features from PostgreSQL inside the event-level transaction.
- Use the ten approved feature names:

  - `anchor_magnitude`
  - `anchor_depth_km`
  - `anchor_latitude`
  - `anchor_longitude`
  - `anchor_time_is_minute_precision`
  - `catalog_m1_plus_count_past_1h`
  - `catalog_m1_plus_count_past_24h`
  - `catalog_m1_plus_count_past_7d`
  - `local_m1_plus_count_past_24h_within_50km`
  - `local_m1_plus_count_past_24h_within_100km`

- Use lower-inclusive and anchor-exclusive history windows. Do not count the
  anchor event itself, future rows, or uncertain same-minute ordering.
- Use the Haversine formula with Earth radius `6371.0088` km and inclusive
  50-km and 100-km boundaries.
- Require at least seven days of usable history before creating prediction
  work. Store the earthquake even when the prerequisite is missing, and record
  the reason for skipping prediction work.
- Do not use the old `M4.5` experiment cutoff as a live router boundary.
- Serialize a canonical, sorted JSON snapshot and compute its SHA-256 hash.
- Use one snapshot for all manifest-selected routes in the release.
- Make prediction idempotency explicit with a unique key over
  `(event_revision_id, model_release_id, input_snapshot_hash)`.
- Create the prediction job and its prediction dispatch atomically with the
  event revision and snapshot. Counter checkpoints are separate run progress
  updates.
- Use an explicit `MODEL_RELEASE_ID` configuration value. Startup verifies the
  immutable release manifest and artifact hashes but does not mutate or
  register releases implicitly.
- Publish prediction messages now, even though the prediction worker is
  deferred. Historical bootstrap rows do not generate automatic alerts.

### Bootstrap and release handling

- Use PostgreSQL as live truth. Defer CSV as a runtime cache or event store.
- Run a one-time resumable history bootstrap through the same normalize,
  enrich, reconcile, revision, and feature logic as live ingestion.
- Preserve raw/enriched source data for the bootstrap, not only the cleaned
  eleven-column CSV. The cleaned historical CSV is insufficient because it
  lacks exact source IDs and URLs.
- Prepare/enrich at least August 25–31, 2026, followed by the September
  demonstration/live window through the latest available source snapshot.
- Require snapshot integrity, hashes, row counts, source IDs/URLs, date
  coverage, and the seven-day history prerequisite before bootstrap completion.
- Keep bootstrap evidence and raw source snapshots local and ignored by Git.
- Write an ignored local bootstrap-readiness manifest containing the source
  snapshot path and hash, row counts, coverage window, and database run ID.
- Keep those snapshots available through project handoff, then archive them
  rather than deleting the evidence immediately after import.
- Refuse to enable Beat until bootstrap readiness has passed.
- Register the selected package through an explicit command and a normalized
  runtime manifest. Copy model weights into the application repository's
  ignored `model-artifacts` area, exclude them from Docker build contexts, mount
  them read-only, and do not commit them.
- Display the human-facing release label `SEIS 1.0`. Keep the exact selected
  training package path and hashes in the runtime manifest provenance.

### Configuration, testing, and operations

- Use Python 3.12 with `pyproject.toml` and a `uv` lock file.
- Use typed settings through `pydantic-settings`, with an `.env.example` and
  required database and Redis configuration.
- Use SQLAlchemy 2 and Alembic synchronously for this worker slice.
- Pin PostgreSQL 16 and Redis 7 Docker images to exact patch tags after checking
  current official documentation during implementation.
- Use a local Docker Compose stack for PostgreSQL and Redis, while allowing the
  Python services to run locally during development.
- Use structured JSON logs to stdout/stderr. Include service, run, dispatch,
  correlation, worker, event, revision, and message identifiers where
  available. Do not put raw HTML, secrets, or large source payloads in the
  database.
- Configure Docker's `local` logging driver with approximately 20 MiB per file
  and five retained files per container, for roughly 100 MiB per container.
- Add health checks for database connectivity, migration state, and Redis.
- Keep live network access out of CI. Use sanitized PHIVOLCS HTML fixtures and
  expected normalized rows for tests, plus local PostgreSQL/Redis integration
  tests.
- Require `pytest` and Ruff formatting/lint checks for the first slice. Defer
  strict static typing until the interfaces stabilize.

## 4. Planned implementation phases

Each phase ends with a review checkpoint. The next phase starts only after the
checkpoint result is shared and any required correction is agreed.

### Phase 1 — repository scaffold and developer tooling

- Create the Python package layout, keeping domain code independent from
  Celery, SQLAlchemy, Redis, HTTP clients, and provider SDKs.
- Add `workers/pyproject.toml`, `workers/uv.lock`, Ruff configuration, pytest
  configuration, `.env.example`, and a safe `.gitignore`.
- Add typed settings and validate required configuration names, formats, and
  ranges without performing migrations or mutating external state.
- Add a shared structured logging adapter.
- Add the initial service entry points for Beat, dispatcher, and data ingestor.
- Add versioned ingestion and prediction command schemas under
  `packages/contracts/queue/`, plus generated or validated Python bindings and
  compatibility tests.
- Add `infrastructure/compose.yml` for PostgreSQL 16 and Redis 7 with the
  agreed logging and health-check configuration, durable volumes, restart
  policies, private data networking, and no public database or Redis ports.
- Add the shared worker image at `workers/Dockerfile`; Beat, dispatcher, and
  ingestor use distinct commands from that image.
- Use non-root container execution where compatible with the selected runtime.
- Define read-only startup-gate interfaces for migration state, model-release
  verification, and bootstrap readiness. Phase 1 entry points must report a
  clear not-ready result and refuse work while concrete checks are unavailable;
  later phases supply the adapters that can make those gates pass. Phase 1 does
  not implement migrations, release registration, or bootstrap.
- Use structured stdout/stderr logs plus configuration and connectivity health
  results as the Phase 1 observability layer. Durable run/job state and counters
  begin with later persistence phases. Defer Prometheus/Grafana-style metrics
  and operator notifications until their contracts are defined.
- Validate the local Compose setup first; the one-VPS deployment follows after
  this slice is proven. Public edge routing remains out of scope here.

Checkpoint: install/synchronize dependencies with `uv`, run the formatter and
test command, and verify that no secrets, weights, or datasets are tracked. If
the workspace still has no Git repository, verify `.gitignore` coverage and
filesystem absence, then report that a Git tracking query is unavailable.

### Phase 2 — schema and migration foundation

- Implement the six-table first migration from the authoritative schema.
- Create the required named PostgreSQL status enums before their tables. Add
  indexes, unique constraints, applicable foreign keys, numeric scales,
  timestamp handling, and revision constraints.
- Retain nullable `job_dispatches.alert_job_id`, omit only its unavailable
  `alert_jobs` FK, and add the temporary null-only check required by ADR 0008.
- Add the active-run coordination mechanism and lease fields required by the
  selected schema.
- Add transaction helpers for run/dispatch creation and event-level atomic
  processing.
- Add migration tests against local PostgreSQL.

Checkpoint: apply the migration from an empty database, inspect the resulting
schema, and verify the identity and idempotency constraints explicitly.

### Phase 3 — model release packaging and registration

- Inspect and verify the exact selected package:
  `redo\quakestrikeph-training\baselines\attempt-2\stratified-baseline-02\chosen-models\balanced-selection-anchor-exploratory-01`.
- Create a normalized application runtime manifest containing the `SEIS 1.0`
  label, exact package provenance, route metadata, relative artifact paths,
  and SHA-256 hashes.
- Copy the required model weights into the ignored application
  `model-artifacts` directory. Do not copy them into Git history.
- Add an explicit model-release registration command.
- Add startup verification that the configured release exists and all manifest
  and artifact hashes match.
- Treat `SEIS 1.0` as the production runtime target for this project. Do not
  silently change the selected model targets.

Checkpoint: register the release locally and demonstrate that a changed or
missing artifact fails verification before any prediction job can be created.

### Phase 4 — PHIVOLCS adapter and detail enrichment

- Port the latest scraper's session, TLS, certificate, retry, timeout, URL
  repair, response-size, and parsing behavior into the infrastructure adapter.
- Add sanitized fixtures for current catalog pages and bulletin detail pages,
  including malformed legacy markup, repaired URLs, missing origin, and
  conflicting detail/catalog timestamps.
- Implement the normalized source-row value object with Decimal validation,
  timestamp precision, canonical identifiers, canonical URL, origin, and
  diagnostics.
- Fetch every unique detail URL sequentially through one reused session.
- Preserve the catalog minute timestamp when detail date/hour/minute differs,
  while retaining a diagnostic for later retry.

Checkpoint: fixture tests prove that valid rows are enriched, invalid links are
rejected, detail failures do not fabricate values, and no live URL is needed in
CI.

### Phase 5 — reconciliation, revisions, and run lifecycle

- Implement current-page retrieval and structural validation.
- Implement exact bulletin-ID matching, then the old app's unambiguous group
  fallback thresholds.
- Implement duplicate coalescing and conflicting duplicate failure behavior.
- Implement row-level rejection for ambiguous, source-less, malformed, or
  invalid rows while allowing unrelated valid rows to continue.
- Append immutable revisions only when normalized source data changes.
- Update visible event `last_seen` fields only for rows present in the current
  source page. Do not delete or supersede events merely because they are absent
  from a current-page response.
- Maintain durable ingestion-run state, retry state, leases, heartbeats,
  counters, and structured diagnostics.

Checkpoint: unit tests cover old-app identity behavior, source-less fallback,
revisions, duplicates, ambiguity, and run-level versus row-level failures.

### Phase 6 — feature snapshots and prediction dispatch

- Implement the ten-feature live contract and history queries.
- Enforce seven-day history readiness and the M1+ prediction rule.
- Apply the time-window, same-minute ordering, Haversine, and boundary rules.
- Canonicalize snapshot JSON and calculate the snapshot hash.
- Create the revision, snapshot, prediction job, and prediction dispatch in one
  PostgreSQL transaction.
- Make retries and duplicate commands safe through the database uniqueness
  constraint and logical job claim behavior.
- Publish IDs-only prediction commands to the separate prediction queue.

Checkpoint: integration tests prove that repeated delivery does not create
duplicate revisions, jobs, snapshots, or dispatches, and that insufficient
history stores the event while recording why prediction work was skipped.

### Phase 7 — scheduler, dispatcher, and worker orchestration

- Implement Beat's single five-minute schedule.
- Implement durable creation of one logical scheduled ingestion run and its
  dispatch row, with overlap prevention.
- Implement dispatcher lease acquisition, Redis publication, late-ack
  behavior, retry backoff, and database status transitions.
- Implement the data-ingestor task claim, heartbeat, source retrieval,
  reconciliation, event processing, and final run state.
- Add graceful shutdown and worker-loss recovery behavior.

Checkpoint: a local end-to-end test demonstrates scheduled work moving from
Beat to PostgreSQL, through Redis, into the ingestor, and finally to durable
prediction work and a prediction-queue message.

### Phase 8 — enriched historical bootstrap (Issue #10 implementation)

The explicit snapshot loader, resumable backfill run, sidecar evidence, and
bootstrap-readiness gate described below are implemented in the worker package.
The later Phase 9 service enablement and operational handoff remain separate.

- Use the latest scraper to collect and enrich August 25–31, 2026, plus the
  September source window needed for the project demonstration.
- Preserve raw/enriched snapshots, collection metadata, hashes, row counts,
  and coverage evidence outside Git.
- Run the resumable bootstrap CLI through the same ingestion path as live work.
- Use one explicit backfill ingestion run and the same reconciliation rules.
- Do not fabricate missing source IDs or URLs. Reject and count rows that do
  not meet the accepted source contract.
- Rebuild or verify the seven-day history requirement before enabling prediction
  work for the September window.
- Suppress automatic alerts for bootstrap/backfill data.
- Preserve the bootstrap source evidence through project handoff, then archive
  it outside Git.

Checkpoint: the readiness check reports source integrity, coverage, identifiers,
database counts, and seven-day history status; it refuses completion when any
required gate fails.

### Phase 9 — local enablement and handoff

- Run migrations explicitly.
- Register and verify `SEIS 1.0` explicitly.
- Run bootstrap and readiness checks explicitly.
- Start the dispatcher and data ingestor.
- Enable the single five-minute Beat schedule only after readiness succeeds.
- After readiness, allow Beat to wait for its next five-minute tick. Use a
  separate explicit command when an immediate poll is intentionally required.
- Run the local smoke suite and inspect structured logs and Docker log rotation
  settings.
- Document the exact commands, environment variables, and known limitations.
  Record prediction, alert, public edge, off-VPS backup, restore-test, host
  monitoring, and external uptime work as deferred production scope.

Checkpoint: provide a short execution report with commands run, test results,
bootstrap coverage, model-manifest verification, and any rejected-row counts.

## 5. Planned initial package layout

The exact private filenames may be refined during Phase 1, but these ownership
seams and top-level paths must remain recognizable:

```text
quakestrikeph/
├── .env.example
├── .gitignore
├── AGENTS.md
├── CONTEXT.md
├── docs/
│   ├── implementation-plan.md
│   ├── adr/
│   └── system-design/
├── workers/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── Dockerfile
│   ├── prediction-worker/
│   │   └── Dockerfile               # deferred prediction runtime
│   ├── src/quakestrike/
│   │   ├── domain/
│   │   ├── application/
│   │   ├── infrastructure/
│   │   │   ├── database/
│   │   │   ├── phivolcs/
│   │   │   ├── queues/
│   │   │   └── logging/
│   │   ├── scheduler/
│   │   ├── data_ingestor/
│   │   ├── prediction_worker/       # deferred in this slice
│   │   ├── alert_worker/            # deferred in this slice
│   │   └── cli.py
│   └── tests/
│       ├── unit/
│       ├── fixtures/
│       ├── contract/
│       └── integration/
├── packages/
│   ├── contracts/
│   │   ├── queue/
│   │   │   ├── ingestion-command.v1.schema.json
│   │   │   └── prediction-command.v1.schema.json
│   │   └── openapi.yaml             # deferred with Backend HTTP work
│   └── generated-clients/
│       ├── python/
│       └── typescript/              # deferred with TypeScript apps
├── database/
│   ├── migrations/
│   ├── initialization/
│   └── maintenance/                 # deferred production operations
├── infrastructure/
│   ├── compose.yml
│   ├── compose.production.yml       # deferred production deployment
│   ├── traefik/                     # deferred public edge
│   ├── cloudflared/                 # deferred public edge
│   ├── backup/                      # deferred production operations
│   └── scripts/
├── model-artifacts/                 # local, ignored
└── apps/                            # all deferred in this slice
    ├── quakestrikeph-bulletin/
    ├── phivolcs-monitoring/
    ├── operations-console/
    └── backend-api/
```

The scheduler and data ingestor are deployable modules. Queue handlers are
their Interface layer. Application and domain code do not depend on Celery,
SQLAlchemy, Redis, HTTP clients, or provider adapters. Infrastructure adapters
implement interfaces declared inward. The package layout is a code boundary,
not a claim that every folder is a separate physical service.

## 6. Review protocol

At each checkpoint I will report:

1. the files changed;
2. the decision or contract implemented;
3. commands and tests run;
4. evidence that the result matches the repository architecture, database
   contract, context, and ADRs;
5. any newly discovered conflict or rejected source row;
6. the next proposed step.

The implementation will pause at a checkpoint when the repository authorities
conflict, the schema is ambiguous, a model artifact is missing, bootstrap
coverage is incomplete, or a source-identity assumption is unsafe. No diagram,
dataset, model weight, or production setting will be silently changed to hide
such a conflict.
