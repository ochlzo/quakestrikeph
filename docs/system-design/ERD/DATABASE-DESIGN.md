# QuakeStrike PH database design

Status: authoritative intended PostgreSQL contract, not evidence that migrations have run. This specification consolidates the schema rules, table purposes, accepted decisions, and relationships into one implementation contract. It contains 21 tables. The [ERD](ERD.png) shows their shape; this file controls fields, constraints, transactions, and ownership. [ADR 0003](../../adr/0003-schema-specification-controls-database-contracts.md) establishes that precedence. The [architecture specification](../ARCHITECTURE/ARCHITECTURE.md) describes the modules that use them.

## Conventions and data stores

In column lists, `?` means nullable, `PK` primary key, and `UQ` unique. All other columns are `NOT NULL`; nullable columns default to null unless another default appears. Application code generates UUID primary keys before insert. Other UUIDs have no implicit default. `created_at` and `updated_at` begin at `now()` where shown; application transactions refresh `updated_at`. Counts default to zero only where shown. Text identifiers and codes are nonblank; JSONB values are objects. Application validation caps diagnostic messages and error summaries at 2,000 characters, diagnostic context and audit metadata at 16 KiB, and public statements and internal notes at 10,000 characters. SMS segmentation follows the selected provider.

Use finite numeric values. Coordinates are decimal degrees; depth and distance are kilometres; probabilities are fractions in `[0,1]`. Model outputs use `double precision` and reject NaN and infinity. All event and forecast times use `timestamptz`; interpret PHIVOLCS source times in `Asia/Manila` and retain source minute/second precision. Lifecycle status columns use the named PostgreSQL enum types below. Other bounded text values use named database checks. Cross-table comparisons, access rules, and external effects require transactions or application logic, not a `CHECK` that reads another table.

| PostgreSQL enum type | Values |
| --- | --- |
| `account_status` | `active`, `suspended`, `closed` |
| `ingestion_run_status` | `pending`, `running`, `retry_wait`, `succeeded`, `failed`, `cancelled` |
| `prediction_job_status` | `pending`, `running`, `retry_wait`, `succeeded`, `failed`, `cancelled` |
| `prediction_attempt_status` | `running`, `succeeded`, `failed`, `abandoned` |
| `forecast_visibility_status` | `draft`, `published`, `withdrawn` |
| `alert_job_status` | `pending`, `resolving`, `delivering`, `completed`, `failed`, `cancelled`, `expired` |
| `alert_recipient_status` | `pending`, `sending`, `retry_wait`, `accepted`, `delivered`, `failed`, `unknown`, `skipped`, `cancelled`, `expired` |
| `alert_delivery_status` | `sending`, `accepted`, `delivered`, `failed`, `unknown` |
| `maintenance_run_status` | `running`, `succeeded`, `failed`, `abandoned` |
| `dispatch_status` | `pending`, `dispatching`, `enqueued`, `retry_wait`, `stopped` |

Create enum types before their tables in the migration that first uses them. Add a value only through a reviewed forward migration. Renaming or removing a value requires a compatibility plan for running application versions and stored rows.

| DFD store | Tables | Purpose |
| --- | --- | --- |
| D1 Earthquake data | `ingestion_runs`, `ingestion_run_inputs`, `earthquake_events`, `earthquake_bulletin_event_identities`, `earthquake_event_revisions` | Source runs, durable input outcomes, stable events, bulletin identity mappings, and immutable observed revisions. |
| D2 Forecast and model records | `model_releases`, `prediction_jobs`, `prediction_attempts`, `forecasts`, `job_dispatches` | Model provenance, work, results, and durable queue submission. |
| D3 Accounts and access | `users`, `user_role_assignments`, `user_alert_preferences`, `saved_pins` | Identity mapping, roles, consent, and locations. |
| D4 Reviews and alerts | `forecast_reviews`, `alert_jobs`, `alert_recipients`, `alert_delivery_attempts` | Publication and SMS authorization/delivery evidence. |
| D5 Operational records | `audit_logs`, `technical_logs`, `maintenance_runs` | Business evidence, selected diagnostics, and maintenance history. |

`job_dispatches` is placed with D2 for the DFD, but it targets ingestion, prediction, or alert work. PostgreSQL is live truth; Redis carries commands and does not replace these records. CSV and bootstrap snapshots are finite import inputs, not live stores. See the [Level 1 DFD](../CFD-DFD/DFD-Level1.png) and [domain glossary](../../../CONTEXT.md).

## Accounts and access

### `users`

One application account maps uniquely to a stable Clerk user ID. Clerk owns sign-in; this table owns profile, current mobile verification, and account status. Email is not a login key.

```text
user_id uuid PK
clerk_user_id text UQ
first_name text?
middle_name text?
last_name text?
display_name text
email text?
mobile_number text?
mobile_verified_at timestamptz?
account_status account_status = 'active'
created_at timestamptz = now()
updated_at timestamptz = now()
```

`account_status` is `active`, `suspended`, or `closed`. Mobile numbers are normalized E.164; verification needs a current number and changing the number clears verification in the same transaction. Closing an account stops SMS and protected actions. Names may be absent. There is no local password or privileged-role default. The Backend writes accounts; workers read only what delivery needs.

### `user_role_assignments`

Historical privileged grants and revocations. A user can hold multiple independent roles; revocation retains evidence and a later re-grant creates a new row.

```text
assignment_id uuid PK
user_id uuid
role_code text
granted_by_user_id uuid?
grant_source text
granted_at timestamptz = now()
revoked_by_user_id uuid?
revoked_at timestamptz?
reason text?
```

`role_code` is `phivolcs_operator`, `operations_viewer`, or `access_administrator`; `grant_source` is `administrator` or `bootstrap`. Administrator grants need a grantor; bootstrap grants need a system audit. Revocation actor and time are both null or both set, and revocation cannot predate grant. Partial `UNIQUE (user_id, role_code) WHERE revoked_at IS NULL`. No role inherits another. Backend role administration writes grants and required audits atomically; protected requests read active assignments afresh.

### `user_alert_preferences`

One optional preferences row per user. No row means no SMS.

```text
user_id uuid PK
sms_enabled boolean = false
phivolcs_only boolean = true
near_pins_only boolean = true
consent_recorded_at timestamptz?
created_at timestamptz = now()
updated_at timestamptz = now()
```

`sms_enabled` requires consent. The defaults are technical proposals for review. `phivolcs_only` excludes automatic-model jobs; `near_pins_only` needs a matching saved pin, and no pins means no match. Backend owns edits. Alert Worker snapshots the selected rule and rechecks live preferences and consent before each new send.

### `saved_pins`

User-named coordinates for near-pin recipient matching, not an authoritative geography table.

```text
pin_id uuid PK
user_id uuid
label text
latitude numeric(9,6)
longitude numeric(10,6)
created_at timestamptz = now()
updated_at timestamptz = now()
```

Latitude is `-90..90`; longitude is `-180..180`. Duplicate labels and coordinates are allowed. The Alert Worker saves matched pin IDs, coordinates, and distances in recipient evidence, but deduplicates SMS destinations rather than pins. Backend owns pin edits.

## Ingestion and earthquake history

### `ingestion_runs`

One logical retrieval/reconciliation attempt, preserved across queue redelivery and retry. Beat creates scheduled runs; Data Ingestor owns processing state and counters.

```text
run_id uuid PK
trigger_type text
status ingestion_run_status = 'pending'
requested_at timestamptz = now()
started_at timestamptz?
attempt_count integer = 0
next_attempt_at timestamptz?
lease_expires_at timestamptz?
worker_execution_id uuid?
finished_at timestamptz?
events_found integer = 0
events_inserted integer = 0
events_revised integer = 0
events_unchanged integer = 0
events_rejected integer = 0
error_code text?
error_message text?
correlation_id uuid
bootstrap_snapshot_sha256 text?  -- required for backfill runs
bootstrap_enriched_snapshot_sha256 text?  -- required when raw input produced an enriched cache
```

`trigger_type` is `scheduled`, `manual`, or `backfill`; `status` is `pending`, `running`, `retry_wait`, `succeeded`, `failed`, or `cancelled`. Counts are nonnegative and summarize distinct normalized inputs, not deliveries. Running needs start time, lease, and execution token. Terminal states need `finished_at`, no earlier than start; `retry_wait` remains unfinished. One Beat process ticks every five minutes and uses PostgreSQL locking plus active-run state to avoid overlapping logical runs. Run and dispatch are created together. A catalog-level structural failure, empty but structurally valid current page, or conflicting duplicate bulletin ID fails the run. Invalid or ambiguous individual rows increment `events_rejected` while valid rows continue. Counters are checkpointed without double-counting. See [scheduler](../../adr/0007-five-minute-single-scheduler-polling.md) and [failure scope](../../adr/0017-input-normalization-and-source-freshness.md).

`next_attempt_at` is set only while a run is `retry_wait`. The first processing attempt and up to three retry attempts retain the same `run_id`; retry delays are 30 seconds, 2 minutes, and 10 minutes. `ingestion_run_inputs` records each distinct normalized input and its final row outcome once per run. The Ingestor derives aggregate counters from those checkpoints before it completes the run, so redelivery cannot increment a counter twice.

New `backfill` runs bind `bootstrap_snapshot_sha256` to the exact SHA-256 of the preserved source snapshot. When a raw snapshot is enriched before import, `bootstrap_enriched_snapshot_sha256` also binds the run to the exact derived cache. Operator recovery requeues that same run identity after a terminal failure; it cannot create a replacement run for the same evidence.

### `earthquake_events`

Stable QuakeStrike event identity. Ordinary PHIVOLCS corrections preserve `event_id` and append a revision; supersession is only for confirmed duplicate identities.

```text
event_id uuid PK
first_seen_run_id uuid
last_seen_run_id uuid
superseded_by_event_id uuid?
created_at timestamptz = now()
updated_at timestamptz = now()
```

No self-supersession or cycles. A current-page poll changes `last_seen_run_id` only for visible events; absence never deletes or supersedes history. Resolve the latest revision by greatest `revision_number` under an event-row lock. Source identifiers do not live on this table.

### `earthquake_event_revisions`

Immutable validated observation versions. Each belongs to one stable event and one run, allowing correction and enrichment history to remain traceable.

```text
event_revision_id uuid PK
event_id uuid
revision_number integer
ingestion_run_id uuid
source_bulletin_id text?
source_event_group_id text?
source_url text
source_time_precision text
event_time timestamptz
latitude numeric(9,6)
longitude numeric(10,6)
depth_km numeric(10,3)
magnitude numeric(5,2)
location_description text
origin text?
prediction_skip_reason text?
ingested_at timestamptz = now()
```

`UNIQUE (event_id, revision_number)`, with number at least 1. Both source IDs may be individually null but not together. `source_event_group_id` is indexed and never unique. URL is canonical and required but not globally unique. Precision is `minute` or `second`; known origin is `TECTONIC`, `VOLCANIC`, or `TECTONIC-VOLCANIC`. Coordinates obey pin ranges, depth is nonnegative, and magnitude need not be positive.

The same canonical `source_bulletin_id` may appear on several immutable revisions only when all occurrences belong to one `event_id`. A composite foreign key from `(source_bulletin_id, event_id)` to `earthquake_bulletin_event_identities` enforces this rule for every direct insert as well as repository writes. The revision table indexes `source_bulletin_id`; it has no global unique index because a later detail enrichment can append a revision for the same bulletin.

### `earthquake_bulletin_event_identities`

One canonical PHIVOLCS bulletin ID maps to one stable QuakeStrike event.

```text
source_bulletin_id text PK
event_id uuid
```

`source_bulletin_id` is uppercase and nonblank. `event_id` references `earthquake_events`. The primary key makes exact lookup unambiguous, while `UNIQUE (source_bulletin_id, event_id)` provides the parent key for the revision table's composite foreign key. A revision with a null bulletin ID does not use this mapping.

### `ingestion_run_inputs`

One durable input checkpoint for each distinct normalized catalog row or parser-rejected row in an ingestion run.

```text
run_id uuid PK
input_key text PK
outcome text
event_id uuid?
created_at timestamptz = now()
```

`outcome` is `inserted`, `revised`, `unchanged`, or `rejected`. Rejected inputs have no event; all other outcomes reference the event that was visible in the page. The checkpoint stores a SHA-256-derived input key or a bounded parser-row key, never raw source HTML, exception text, or an untrusted URL.

`prediction_skip_reason` is nullable immutable evidence for a valid revision that did not create prediction work. Allowed values are `magnitude_below_m1`, `history_coverage_unavailable`, `incomplete_feature_history`, `history_starts_after_required_window`, `history_ends_before_anchor`, and `model_release_unavailable`.

Match exact bulletin ID first. A group fallback may attach a revision only when exactly one existing event has the same group, latitude and longitude differences each at most `0.25` degrees, and magnitude difference at most `1.0`. Timestamp, group alone, and identical observations are not identity keys. Missing both IDs, unmatched or ambiguous fallback, or an unrecognizable URL rejects that row; a conflicting duplicate bulletin ID fails the run. When detail retrieval fails, a valid catalog row keeps its minute timestamp and nullable origin with a diagnostic. Detail seconds are accepted only if date, hour, and minute agree with the catalog. Later changes to origin, precision, or URL append a revision. Serialize insertion per event. See [identity](../../adr/0013-revision-level-source-identifiers.md), [fallback](../../adr/0015-source-less-fallback-reconciliation.md), and [enrichment](../../adr/0020-detail-page-enrichment.md).

## Prediction and forecasts

### `model_releases`

Immutable model-release registry. The normalized manifest, not mutable database flags, defines routes, targets, features, provenance, runtime metadata, and artifact hashes.

```text
model_release_id uuid PK
version_label text UQ
artifact_manifest_uri text
artifact_manifest_hash text
input_schema_version text
output_schema_version text
created_at timestamptz = now()
```

Manifest hash is lowercase 64-character SHA-256 hex. Deployment selects `MODEL_RELEASE_ID` explicitly. `SEIS 1.0` is the project's production runtime label for the selected package; registration verifies the normalized manifest and local artifact hashes. Artifacts remain out of Git and Docker build contexts and mount read-only. A release row does not itself switch deployment configuration. See [release ADR](../../adr/0009-immutable-model-releases-and-ingestion-feature-snapshots.md).

### `prediction_jobs`

One immutable input snapshot and requested model release for a specific event revision. The Ingestor creates it with the event transaction; the Prediction Worker owns later processing.

```text
job_id uuid PK
event_revision_id uuid
model_release_id uuid
input_snapshot_hash text
input_snapshot_json jsonb
idempotency_key text UQ
status prediction_job_status = 'pending'
requested_at timestamptz = now()
next_attempt_at timestamptz?
completed_at timestamptz?
last_error_code text?
last_error_message text?
correlation_id uuid
```

`UNIQUE (event_revision_id, model_release_id, input_snapshot_hash)` prevents duplicate inference for the same revision/release/snapshot while allowing work for a later revision. Hash is SHA-256 over canonical validated features plus schema identity. Snapshot never changes. States are `pending`, `running`, `retry_wait`, `succeeded`, `failed`, `cancelled`. `retry_wait` needs `next_attempt_at`; other states clear it. Terminal states need `completed_at`, whether successful or not. A failed job may retry in place by adding an attempt. The processing claim is on `prediction_attempts`.

Every valid event is saved, but only a new or changed M1+ revision with seven complete days of prior history can create prediction work. The v1 snapshot has exactly these fields: `anchor_magnitude`, `anchor_depth_km`, `anchor_latitude`, `anchor_longitude`, `anchor_time_is_minute_precision`, `catalog_m1_plus_count_past_1h`, `catalog_m1_plus_count_past_24h`, `catalog_m1_plus_count_past_7d`, `local_m1_plus_count_past_24h_within_50km`, and `local_m1_plus_count_past_24h_within_100km`. Count only recorded M1+ events using lower-inclusive, anchor-exclusive windows; exclude the anchor, future observations, and uncertain same-minute ordering. Local counts use inclusive Haversine radii of 50 and 100 km with Earth radius `6371.0088 km`. No placeholder snapshot or shortened window is permitted. Insufficient history retains the event and records why work was skipped. See [feature ADR](../../adr/0021-live-feature-contract.md).

### `prediction_attempts`

Processing history and the active lease for each prediction job.

```text
attempt_id uuid PK
job_id uuid
attempt_number integer
status prediction_attempt_status = 'running'
started_at timestamptz = now()
finished_at timestamptz?
lease_expires_at timestamptz?
worker_execution_id uuid
error_code text?
error_message text?
```

`UNIQUE (job_id, attempt_number)` with number at least 1; partial `UNIQUE (job_id) WHERE status = 'running'`. States are `running`, `succeeded`, `failed`, `abandoned`. Running requires lease and no finish time; other states require finish time and clear lease. Recovery abandons an expired attempt before opening the next. Completion matches the current execution token and lease, then commits forecast and job/attempt success together. Stale workers cannot commit a result.

### `forecasts`

Immutable result of one successful prediction job. A newer result can explicitly supersede an older forecast for the same event.

```text
forecast_id uuid PK
job_id uuid UQ
supersedes_forecast_id uuid?
window_start timestamptz
window_end timestamptz
probability_m1_plus_24h double precision
expected_m1_plus_count_24h double precision
probability_m4_plus_24h double precision
probability_m5_plus_24h double precision
activity_radius_median_km_24h double precision?
maximum_magnitude_q05_24h double precision?
maximum_magnitude_q50_24h double precision?
maximum_magnitude_q95_24h double precision?
additional_output_json jsonb?
created_at timestamptz = now()
```

The window starts at the linked revision's event time and spans exactly 24 elapsed hours; the Prediction Worker verifies the cross-table equality in its transaction. Count and radius are nonnegative. Enforce `P(M5+) <= P(M4+) <= P(M1+)`, each in `[0,1]`; reject inconsistent outputs instead of reordering them. Magnitude quantiles are all null or all present and ordered `q10 <= q50 <= q90`. Null is not zero. Supersession targets another forecast for the same event and cannot cycle. The current forecast is the newest successful result for the latest event revision and configured release, ordered by job request time then job ID. If the latest revision has no success, no current forecast exists; older results may be labelled stale. A newer failed job does not hide an older successful result for the same revision/release.

## Reviews and alerts

### `forecast_reviews`

One editable PHIVOLCS review per forecast. Public statement and internal note have separate visibility. Audits retain the action sequence; there is no publication-history table.

```text
review_id uuid PK
forecast_id uuid UQ
reviewer_user_id uuid
last_edited_by_user_id uuid
decision text?
public_statement text?
internal_note text?
visibility_status forecast_visibility_status = 'draft'
published_by_user_id uuid?
published_at timestamptz?
withdrawn_by_user_id uuid?
withdrawn_at timestamptz?
reviewed_at timestamptz?
created_at timestamptz = now()
updated_at timestamptz = now()
edit_version integer = 1
```

Decision is null before assessment, otherwise `approved`, `rejected`, or `inconclusive`. Visibility is `draft`, `published`, or `withdrawn`. Non-draft needs decision and reviewed time; published needs nonblank public statement plus publisher/time; withdrawal needs withdrawer/time. Actor/time pairs are both set or both null. Allowed visibility transitions are draft to published, published to withdrawn, and withdrawn to published. Content edits may occur in any state. Increment `edit_version` and use the version read by the editor to prevent lost updates. Republishing clears withdrawal fields and replaces latest publication actor/time. Only published reviews appear publicly; `internal_note` never does. Add `UNIQUE (review_id, forecast_id)` for the alert-job composite FK.

### `alert_jobs`

One authorized SMS batch with an immutable message and recipient-policy snapshot. Backend creates operator jobs; Prediction Worker may create automatic jobs.

```text
alert_job_id uuid PK
forecast_id uuid
review_id uuid?
alert_type text
requested_by_user_id uuid?
requested_by_service text?
requested_at timestamptz = now()
channel text = 'sms'
message_snapshot text
recipient_policy_snapshot jsonb
idempotency_key text UQ
status alert_job_status = 'pending'
recipient_resolution_completed_at timestamptz?
lease_expires_at timestamptz?
worker_execution_id uuid?
expires_at timestamptz
cancelled_at timestamptz?
cancellation_reason text?
completed_at timestamptz?
correlation_id uuid
```

Types are `operator_review` and `automatic_model`; only `sms` is in scope. An operator job needs matching `review_id` and requester user, with no service requester. Backend locks the review, checks that it is published or withdrawn, and snapshots its text, visibility, and edit version. Drafts cannot authorize SMS. An automatic job needs a service requester and no review or user requester. Direct forecast FK plus composite `(review_id, forecast_id)` FK prevent a mismatched review. Partial `UNIQUE (forecast_id, channel) WHERE alert_type = 'automatic_model'` permits at most one automatic batch per forecast/channel; operator resends use new keys. The automatic trigger uses observed anchor magnitude at least M4.5, a newly committed current forecast from the configured release, and an unexpired window. Backfills do not automatically send. Keep the threshold in version-controlled policy configuration and its version in the snapshot, not a new table or live JSON override.

States are `pending`, `resolving`, `delivering`, `completed`, `failed`, `cancelled`, `expired`. Active resolving/delivering ownership needs lease/token. Terminal states need `completed_at` and stop dispatch; `completed` means recipients settled, not all delivered. Accepted/unknown recipients stay under reconciliation until expiry or cancellation. `expires_at` equals forecast `window_end` and must be later than creation; verify equality transactionally. No new send begins at or after expiry. Late outcomes may still update evidence. Withdrawal alone does not cancel an authorized job; explicit cancellation stops remaining unsent work. Cancellation fields apply only to cancelled jobs.

### `alert_recipients`

One resolved normalized phone destination per batch, with selection evidence and current delivery summary. Alert Worker writes and rechecks it.

```text
recipient_id uuid PK
alert_job_id uuid
user_id uuid?
destination_snapshot text
eligibility_snapshot jsonb
resolved_at timestamptz = now()
delivery_idempotency_key text UQ
status alert_recipient_status = 'pending'
next_attempt_at timestamptz?
delivered_at timestamptz?
last_error_code text?
processing_lease_expires_at timestamptz?
worker_execution_id uuid?
```

`UNIQUE (alert_job_id, destination_snapshot)` after E.164 normalization. One public-user resolution requires a user; the FK may later be set null for controlled account removal, but a detached row cannot start a send. States are `pending`, `sending`, `retry_wait`, `accepted`, `delivered`, `failed`, `unknown`, `skipped`, `cancelled`, `expired`. Sending needs lease/token; other states clear them. Retry wait alone needs `next_attempt_at`. Delivered alone needs `delivered_at`. Accepted awaits provider outcome; unknown is held for reconciliation, never blind resend. Eligibility snapshot records current preference values, matching pins/coordinates/distances, rule version, and radius. Before each new provider call, recheck active account, verified current number, consent, preferences, near-pin rule, and expiry. Changed or lost eligibility becomes skipped. Resolution uses idempotent inserts and marks completion only after the full candidate scan.

### `alert_delivery_attempts`

One persisted provider-call attempt per recipient. Its state cannot claim a crashed call definitely failed or delivered.

```text
delivery_attempt_id uuid PK
recipient_id uuid
attempt_number integer
provider text
provider_message_id text?
status alert_delivery_status = 'sending'
started_at timestamptz = now()
finished_at timestamptz?
provider_status_at timestamptz?
error_code text?
error_message text?
correlation_id uuid
```

`UNIQUE (recipient_id, attempt_number)`, number at least 1; partial `UNIQUE (recipient_id) WHERE status = 'sending'`. States are `sending`, `accepted`, `delivered`, `failed`, `unknown`. Persist `sending` before the external call. It has no finish time; later states have one. Crash recovery closes it as unknown at recovery time, with an interrupted-call code. `finished_at` is local closure, not handset delivery. Index provider plus reference, but do not assume provider reference is unique across retry rows. Provider callback updates attempt and recipient atomically and cannot regress delivered to accepted.

## Audit, operations, and dispatch

### `audit_logs`

Durable evidence of security and business actions, distinct from disposable technical diagnostics.

```text
audit_id uuid PK
occurred_at timestamptz = now()
actor_type text
actor_user_id uuid?
actor_service text?
action text
target_type text?
target_id text?
target_revision text?
outcome text
reason_code text?
request_id uuid?
correlation_id uuid
metadata jsonb?
```

Actor type is `user`, `system`, or `anonymous`; the matching user/service field is required only for its type. Outcome is `succeeded`, `denied`, or `failed`. Target type/id are paired when a target exists; do not fabricate a target for an early denial. Target fields are historical descriptions, not polymorphic FKs. Privileged mutation and success audit commit together. Rollback failures and denials use a bounded separate path and never report committed success. Normal application roles cannot update or delete audit rows. Metadata contains no secrets.

### `technical_logs`

Selected, sanitized warnings, errors, slow requests, and maintenance messages for protected Operations queries. Container stdout/stderr carries ordinary and outage diagnostics.

```text
log_id bigint GENERATED ALWAYS AS IDENTITY PK
occurred_at timestamptz = now()
module text
category text
http_method text?
route_template text?
status_code smallint?
duration_ms numeric(12,3)?
client_ip inet?
severity text
event_code text
message text
correlation_id uuid?
request_id uuid?
context jsonb?
```

Categories are `http_access`, `worker`, `scheduler`, `database`, `maintenance`; severity is `info`, `warning`, or `error`. Completed HTTP records need method, route template, status `100..599`, nonnegative duration, and request ID. Other categories leave HTTP-only fields null; interrupted requests use another diagnostic category. IP is optional and comes only from trusted proxy hops. Never store secrets, headers, full URLs/queries, complete payloads, or raw SQL. No business FKs tie short-lived logs to retained records. Correlation/request IDs allow joins in queries without hard FKs. Cleanup may delete these rows independently.

### `maintenance_runs`

Evidence of host-scheduled backup, isolated restore test, and retention cleanup; the table does not perform or schedule maintenance.

```text
maintenance_run_id uuid PK
operation_type text
status maintenance_run_status = 'running'
started_at timestamptz = now()
finished_at timestamptz?
target text
affected_row_count bigint?
artifact_reference text?
artifact_checksum text?
related_backup_run_id uuid?
verification_summary text?
error_message text?
correlation_id uuid
```

Operations are `backup`, `restore_test`, `retention_cleanup`; states are `running`, `succeeded`, `failed`, `abandoned`. Terminal finish is no earlier than start; running has no finish. Affected count is nonnegative. Successful backup needs artifact reference and SHA-256 checksum. Restore test needs a related backup and, on success, verification summary. Application logic checks that the referenced row is a backup; no self-reference. A failed backup may have no artifact. The next maintenance reconciliation marks interrupted runs abandoned. Restricted scripts write results; Operations Console reads them through Backend.

### `job_dispatches`

One durable queue-submission row targets exactly one ingestion run, prediction job, or alert job. It separates Redis acceptance from worker processing.

```text
dispatch_id uuid PK
ingestion_run_id uuid? UQ
prediction_job_id uuid? UQ
alert_job_id uuid? UQ
status dispatch_status = 'pending'
next_dispatch_at timestamptz? = now()
last_dispatched_at timestamptz?
attempt_count integer = 0
lease_expires_at timestamptz?
dispatch_token uuid?
last_error text?
created_at timestamptz = now()
updated_at timestamptz = now()
```

`CHECK (num_nonnulls(ingestion_run_id, prediction_job_id, alert_job_id) = 1)` and each target is independently unique. Creation transactions insert target and dispatch together. States are `pending`, `dispatching`, `enqueued`, `retry_wait`, `stopped`; count is nonnegative. Dispatching needs lease/token and clears next time. Pending/retry wait need next time and clear lease/token. Enqueued/stopped clear scheduling and claim. Set `last_dispatched_at` only after Redis accepts the command. Claim, commit, publish, and record acceptance are separate steps. A stale dispatcher may update only with its current token. Redis acceptance does not mean work completed; if acceptance succeeds but SQL status write fails, consumers deduplicate and claim the existing logical job. Recovery checks processing state, retry schedule, and leases before resubmitting. Terminal job transitions stop the dispatch in the same transaction; explicit retry reopening resets the same dispatch. Dispatch lease is distinct from worker processing leases. The ingestion-first migration retains nullable `alert_job_id` but omits its FK while `alert_jobs` is absent and adds a temporary `CHECK (alert_job_id IS NULL)`. The later alert-schema migration creates `alert_jobs`, adds the FK, and removes that temporary check in the same migration. See [durable dispatch ADR](../../adr/0004-persist-ingestion-runs-before-dispatch.md), the [first-slice amendment](../../adr/0008-ingestion-first-slice-runtime-and-boundary.md), and the [fenced ingestion-dispatch ADR](../../adr/0024-fenced-durable-ingestion-dispatch.md).

## Foreign keys and delete behavior

Every FK uses `ON UPDATE RESTRICT`. Required child references have one parent; optional child references have zero or one. A parent can have many children unless child PK/UQ narrows that relation. Implement these `ON DELETE` actions exactly:

| Child reference | Parent | Delete |
| --- | --- | --- |
| `job_dispatches.ingestion_run_id`, `.prediction_job_id`, `.alert_job_id` | `ingestion_runs`, `prediction_jobs`, `alert_jobs` | RESTRICT |
| `user_role_assignments.user_id`, `.granted_by_user_id`, `.revoked_by_user_id` | `users` | RESTRICT |
| `user_alert_preferences.user_id`; `saved_pins.user_id` | `users` | CASCADE |
| `earthquake_events.first_seen_run_id`, `.last_seen_run_id` | `ingestion_runs` | RESTRICT |
| `earthquake_events.superseded_by_event_id` | `earthquake_events` | RESTRICT |
| `earthquake_event_revisions.event_id`, `.ingestion_run_id` | `earthquake_events`, `ingestion_runs` | RESTRICT |
| `earthquake_event_revisions.(source_bulletin_id, event_id)` | `earthquake_bulletin_event_identities.(source_bulletin_id, event_id)` | RESTRICT |
| `earthquake_bulletin_event_identities.event_id` | `earthquake_events` | RESTRICT |
| `ingestion_run_inputs.run_id`, `.event_id` | `ingestion_runs`, `earthquake_events` | RESTRICT |
| `prediction_jobs.event_revision_id`, `.model_release_id` | `earthquake_event_revisions`, `model_releases` | RESTRICT |
| `prediction_attempts.job_id`; `forecasts.job_id` | `prediction_jobs` | RESTRICT |
| `forecasts.supersedes_forecast_id` | `forecasts` | RESTRICT |
| `forecast_reviews.forecast_id` | `forecasts` | RESTRICT |
| `forecast_reviews` creator/editor/publisher/withdrawer user IDs | `users` | RESTRICT |
| `alert_jobs.forecast_id`; `alert_jobs.(review_id, forecast_id)` | `forecasts`; `forecast_reviews.(review_id, forecast_id)` | RESTRICT |
| `alert_jobs.requested_by_user_id` | `users` | RESTRICT |
| `alert_recipients.alert_job_id`; `alert_delivery_attempts.recipient_id` | `alert_jobs`; `alert_recipients` | RESTRICT |
| `alert_recipients.user_id` | `users` | SET NULL |
| `audit_logs.actor_user_id` | `users` | RESTRICT |
| `maintenance_runs.related_backup_run_id` | `maintenance_runs` | RESTRICT |

The composite review FK uses PostgreSQL `MATCH SIMPLE`: an automatic job has null `review_id`, while its direct forecast FK and alert-type check still apply. `forecast_id` remains required. A job can have zero or one dispatch by FK/UQ, but creation transactions require one for new background work. `technical_logs` has no business FK. Close or anonymize retained users rather than deleting their audit evidence. Physical deletion succeeds only when RESTRICT references are absent. Business retention requires a separately reviewed procedure; technical-log cleanup cannot cascade through history.

## Index plan

PK and UQ constraints create indexes; do not duplicate an index already covered by a useful left prefix. Index every remaining FK lookup column and the composite review FK. Add indexes for these query paths:

- Active role assignment partial uniqueness; revision group ID and non-unique bulletin-ID lookup. `UNIQUE (event_id, revision_number)` supports latest revision by reverse scan.
- `prediction_jobs(event_revision_id, model_release_id, requested_at DESC)`; `forecast_reviews(visibility_status, updated_at DESC)`.
- Dispatch `next_dispatch_at, dispatch_id` for pending/retry-wait and `lease_expires_at` for dispatching; target UQs support job lookup.
- Prediction running-attempt lease and partial running-job uniqueness; active ingestion/alert processing leases.
- Automatic alert partial uniqueness, alert status/expiry and request time; recipient job/status, retry time, sending lease, and user ID.
- Delivery provider/reference when present; recipient/attempt sequence uniqueness.
- Audit occurrence time, actor/time, target/time, and correlation; technical-log occurrence, module/severity/time, category/status/time, request, and correlation; maintenance operation/start time.

Queue and Console searches must be indexed, paginated, and date-bounded. Do not add JSON-wide indexes, partitions, or host-metric tables without measured need. Technical-log deletion uses manageable batches.

## Transactions and cross-table rules

1. Account and role changes check ownership and authorization. Grants, review publication, and operator alert creation commit with required success audits. Review edits check `edit_version`; operator alert creation locks the non-draft review and snapshots its current content and state.
2. Beat commits the pending ingestion run with its dispatch. Dispatcher claims and publishes after commit. Worker processing preserves run/job identity across retries and uses a separate processing lease. Redis is at-least-once; database claims and uniqueness make repetition safe.
3. For each accepted event, Ingestor locks or creates stable identity, appends a changed revision, builds the ten-feature snapshot from prior PostgreSQL history, hashes canonical JSON, and creates any eligible prediction job plus dispatch in one transaction. Run counters checkpoint separately. Redis publication occurs after commit. No future data, uncertain same-minute ordering, retrospective family metadata, missing URL, missing both IDs, or incomplete snapshot can pass the prediction gate. See [atomic processing](../../adr/0016-atomic-event-processing-and-release-registration.md) and [revision idempotency](../../adr/0022-idempotent-revisions-and-bootstrap-gates.md).
4. Prediction completion validates the current execution token. Forecast, job/attempt success, any eligible automatic alert job and dispatch, and system audit commit together. The automatic M4.5 trigger applies to the observed anchor, not the predicted maximum; backfills never auto-alert.
5. Alert resolution inserts unique recipients and checkpoints completion only after candidate processing. Before a provider call, the worker claims and rechecks one recipient, then persists an attempt. The external SMS call cannot join a SQL transaction. Unknown results require provider reconciliation. An expiry sweep stops new sends and marks unsent recipients expired, without rewriting accepted/unknown/delivered evidence. Late callbacks may close earlier attempts.

## Initialization, retention, and policy choices

Apply hand-reviewed Alembic migrations, verify and explicitly register the `SEIS 1.0` manifest and artifact hashes, run the resumable bootstrap, check source snapshot integrity, identifiers, URLs, row counts, and seven-day history, then start Dispatcher/Ingestor and enable Beat. Bootstrap records a `backfill` run and uses the same normalization and reconciliation as live ingestion. Service startup never runs migrations, imports data, or silently changes releases. Historical snapshots remain source evidence outside Git; PostgreSQL is the only live event store. See [startup](../../adr/0019-explicit-startup-and-runtime-configuration.md) and [readiness](../../adr/0022-idempotent-revisions-and-bootstrap-gates.md).

Choose the near-pin radius policy before selecting recipients. A fixed radius or a versioned magnitude-based rule can fit `recipient_policy_snapshot`; `eligibility_snapshot` records actual matches. Gardner-Knopoff is a research candidate, not an adopted notification or safety boundary. Do not silently substitute the forecast P90 activity radius. Also decide technical and business retention periods separately, SMS provider/callback and phone-verification policy, and any additional automatic-alert throttle. Existing snapshots and states support these choices without a new table. Host maintenance scripts, not a database scheduling extension, own cleanup, backup, and restore-test schedules. The [architecture specification](../ARCHITECTURE/ARCHITECTURE.md#logging-diagnostics-and-maintenance) defines diagnostic fallback and off-VPS backup requirements.

## References

- [ERD](ERD.png), [architecture](../ARCHITECTURE/ARCHITECTURE.md), [DFD](../CFD-DFD/DFD-Level1.png), [context](../../../CONTEXT.md), and [ADRs](../../adr/).
- Source schema: `C:\Projects\SAM_Capstone\capstone\docs\07-erd-schema-specification.md`.
- Source table guide: `C:\Projects\SAM_Capstone\capstone\docs\08-database-table-guide.md`. Both sources remain unchanged.
