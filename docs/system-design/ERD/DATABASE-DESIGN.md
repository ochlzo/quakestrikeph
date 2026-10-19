# QuakeStrike PH database design

Status: authoritative intended PostgreSQL contract, not evidence that migrations have run. This specification consolidates the schema rules, table purposes, accepted decisions, and relationships into one implementation contract. It contains 19 tables. The [ERD](ERD.png) shows the former review-oriented design and is temporarily stale, including its former operator-role and SMS-only relationships; this file controls fields, constraints, transactions, and ownership until the diagram follow-up lands. [ADR 0003](../../adr/0003-schema-specification-controls-database-contracts.md) establishes that precedence. The [architecture specification](../ARCHITECTURE/ARCHITECTURE.md) and [ADRs 0035](../../adr/0035-cloudflare-access-operations-console.md), [0036](../../adr/0036-google-accounts-and-independent-phone-verification.md), [0037](../../adr/0037-clerk-free-bulletin-authentication.md), and [0038](../../adr/0038-email-and-sms-alert-preferences.md) describe the applications that use them, subject to the later ADR amendments.

## Conventions and data stores

In column lists, `?` means nullable, `PK` primary key, and `UQ` unique. All other columns are `NOT NULL`; nullable columns default to null unless another default appears. Application code generates UUID primary keys before insert. Other UUIDs have no implicit default. `created_at` and `updated_at` begin at `now()` where shown; application transactions refresh `updated_at`. Counts default to zero only where shown. Text identifiers and codes are nonblank; JSONB values are objects. Application validation caps diagnostic messages and error summaries at 2,000 characters, diagnostic context and audit metadata at 16 KiB, and public statements and internal notes at 10,000 characters. SMS segmentation follows the selected provider.

Use finite numeric values. Coordinates are decimal degrees; depth and distance are kilometres; probabilities are fractions in `[0,1]`. Model outputs use `double precision` and reject NaN and infinity. All event and forecast times use `timestamptz`; interpret PHIVOLCS source times in `Asia/Manila` and retain source minute/second precision. Lifecycle status columns use the named PostgreSQL enum types below. Other bounded text values use named database checks. Cross-table comparisons, access rules, and external effects require transactions or application logic, not a `CHECK` that reads another table.

| PostgreSQL enum type | Values |
| --- | --- |
| `account_status` | `active`, `suspended`, `closed` |
| `ingestion_run_status` | `pending`, `running`, `retry_wait`, `succeeded`, `failed`, `cancelled` |
| `prediction_job_status` | `pending`, `running`, `retry_wait`, `succeeded`, `failed`, `cancelled` |
| `prediction_attempt_status` | `running`, `succeeded`, `failed`, `abandoned` |
| `alert_job_status` | `pending`, `resolving`, `delivering`, `completed`, `failed`, `expired` |
| `alert_recipient_status` | `pending`, `sending`, `retry_wait`, `accepted`, `delivered`, `failed`, `unknown`, `skipped`, `expired` |
| `alert_delivery_status` | `sending`, `accepted`, `delivered`, `failed`, `unknown` |
| `maintenance_run_status` | `running`, `succeeded`, `failed`, `abandoned` |
| `dispatch_status` | `pending`, `dispatching`, `enqueued`, `retry_wait`, `stopped` |

Create enum types before their tables in the migration that first uses them. Add a value only through a reviewed forward migration. Renaming or removing a value requires a compatibility plan for running application versions and stored rows.

| DFD store | Tables | Purpose |
| --- | --- | --- |
| D1 Earthquake data | `ingestion_runs`, `source_catalog_evidence`, `ingestion_run_inputs`, `earthquake_events`, `earthquake_bulletin_event_identities`, `earthquake_event_revisions` | Source runs, validated catalog coverage, durable input outcomes, stable events, bulletin identity mappings, and immutable observed revisions. |
| D2 Forecast and model records | `model_releases`, `prediction_jobs`, `prediction_attempts`, `forecasts`, `job_dispatches` | Model provenance, work, results, and durable queue submission. |
| D3 Accounts and access | `users` | Clerk account mapping, verified alert destinations, and channel settings. |
| D4 Alerts | `alert_jobs`, `alert_recipients`, `alert_delivery_attempts` | Automatic email/SMS authorization and delivery evidence. |
| D5 Operational records | `audit_logs`, `operator_access_events`, `technical_logs`, `maintenance_runs` | Business evidence, Console access evidence, selected diagnostics, and maintenance history. |

`job_dispatches` is placed with D2 for the DFD, but it targets ingestion, prediction, or alert work. PostgreSQL is live truth; Redis carries commands and does not replace these records. CSV and bootstrap snapshots are finite import inputs, not live stores. See the [Level 1 DFD](../CFD-DFD/DFD-Level1.png) and [domain glossary](../../../GLOSSARY.md).

## Accounts and access

### `users`

One Bulletin account maps uniquely to a stable Clerk user ID from email/password or Google sign-in. This table owns the profile, the Backend mirror of the current Clerk-verified email, the current verified alert phone, channel opt-ins, shared alert rules, onboarding completion, and account status. Clerk owns passwords, email identity, verification, and sessions. Operators authenticate through Cloudflare Access and do not have `users` rows by virtue of Console access.

```text
user_id uuid PK
clerk_user_id text UQ
display_name text
email text
email_verified_at timestamptz?
email_enabled boolean = false
mobile_number text? UQ
mobile_verified_at timestamptz?
sms_enabled boolean = false
alert_trigger_magnitude numeric(3,1) = 4.5
nearby_alerts_only boolean = false
alert_location_latitude numeric(9,6)?
alert_location_longitude numeric(10,6)?
alert_trigger_distance_km numeric(10,3)?
account_status account_status = 'active'
onboarding_completed_at timestamptz?
created_at timestamptz = now()
updated_at timestamptz = now()
```

`display_name` is the only stored profile name. The Backend trims surrounding whitespace and accepts 1–100 characters. It does not split the name into first, middle, or last names. Migration `20261004_12` removes the unused name columns; its downgrade restores nullable columns but cannot recover dropped values.

`account_status` is `active`, `suspended`, or `closed`. `display_name` is required when the Backend creates the profile. The Backend creates a row only after Clerk completes email verification or Google authentication. A missing row means the profile step is unfinished; a null `onboarding_completed_at` means the alert-preferences step is unfinished. The final preference save sets that timestamp, even when both channels are off. Both receive switches default to false and become true only by explicit audited opt-in. Enforce `CHECK (onboarding_completed_at IS NOT NULL OR (NOT email_enabled AND NOT sms_enabled))` and `CHECK (account_status <> 'closed' OR (NOT email_enabled AND NOT sms_enabled AND mobile_number IS NULL AND mobile_verified_at IS NULL))`. An active account still needs completed onboarding and a current verified destination before delivery.

`email` mirrors the current Clerk email; it is not the local identity key and has no independent uniqueness claim. `email_verified_at` is set only after trusted Clerk evidence for that exact current address. A requested email change sets it null to pause email delivery while Clerk holds the pending replacement; after verification, the Backend updates `email` and `email_verified_at` together and the existing `email_enabled` choice can resume. Restrict direct Clerk email changes outside this controlled flow or synchronize them with verified, idempotent Clerk events before any email send. If the mirror is missing or inconsistent, fail closed. A closed account cannot have an enabled channel.

Mobile numbers are normalized E.164. `UNIQUE (mobile_number)` permits multiple nulls but prevents one current number from belonging to two accounts. Enforce `CHECK ((mobile_number IS NULL) = (mobile_verified_at IS NULL))`. A short-lived Redis verification attempt, tied to the signed-in Clerk user and proposed phone, does not change this row until IPROG confirms the entered code. Expired or lost attempts cannot verify a phone. An unsupported or unknown ordinary shared-sender network stops before OTP and cannot enable SMS. A second account cannot claim a bound phone, and phone possession does not merge accounts. Phone replacement requires recent interactive Clerk reverification. Starting it sets `sms_enabled = false` with an audit while retaining the old binding; verified replacement atomically updates the number and timestamp and still requires a new opt-in. Closing an account clears the current phone and verification time and disables both channels, releasing the phone uniqueness claim while preserving historical evidence. SMS delivery requires a verified current number and current sender support. `alert_trigger_magnitude` is finite between `1.0` and `10.0`; the API accepts steps of `0.1`. `nearby_alerts_only` defaults to false. The alert location is one user-selected fixed point, not continuous device tracking. Latitude and longitude are either both null or both present, finite, and within `[-90, 90]` and `[-180, 180]`; distance is finite from `1` to `1000` kilometres when present; the API accepts whole kilometres. Enabling nearby-only alerts requires both coordinates and a distance. Disabling it may retain those values for later use, but they do not affect eligibility while it is off. There is no local password or operator-role table. The Backend writes accounts; workers read only what delivery needs. See [ADRs 0037](../../adr/0037-clerk-free-bulletin-authentication.md) and [0038](../../adr/0038-email-and-sms-alert-preferences.md).

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

`trigger_type` is `scheduled`, `manual`, or `backfill`; `status` is `pending`, `running`, `retry_wait`, `succeeded`, `failed`, or `cancelled`. Counts are nonnegative and summarize distinct normalized inputs, not deliveries. Running needs start time, lease, and execution token. Terminal states need `finished_at`, no earlier than start; `retry_wait` remains unfinished. One Beat process ticks every five minutes and uses PostgreSQL locking plus active-run state to avoid overlapping logical runs. Run and dispatch are created together. A catalog-level structural failure, empty but structurally valid current page, or conflicting duplicate bulletin ID fails the run. Invalid or ambiguous individual rows increment `events_rejected` while valid rows continue. Durable checkpoints and the full normalized input set make successful-run counters safe across redelivery. See [scheduler](../../adr/0007-five-minute-single-scheduler-polling.md) and [failure scope](../../adr/0017-input-normalization-and-source-freshness.md).

`next_attempt_at` is set only while a run is `retry_wait`. The first processing attempt and up to three retry attempts retain the same `run_id`; retry delays are 30 seconds, 2 minutes, and 10 minutes. `ingestion_run_inputs` records retry progress for each row requiring processing. Scheduled polls omit checkpoints for rows proved unchanged against complete revisions from before the logical run. Their successful counters use the distinct normalized input set plus checkpoint outcomes; other runs derive counters from checkpoints. Redelivery cannot increment a counter twice.

New `backfill` runs bind `bootstrap_snapshot_sha256` to the exact SHA-256 of the preserved source snapshot. When a raw snapshot is enriched before import, `bootstrap_enriched_snapshot_sha256` also binds the run to the exact derived cache. Operator recovery requeues the same failed run within 30 days of `finished_at`. Once retry checkpoints may have expired, recovery creates a new logical run bound to the same preserved snapshot and retains the prior run's audit record.

### `source_catalog_evidence`

One immutable coverage claim for a live ingestion run, bound to the exact
PHIVOLCS catalog response before row reconciliation. Only a `succeeded` run's
claim may extend coverage for later runs; the current run may use its own claim
while processing rows in event-time order. See [ADR 0031](../../adr/0031-live-catalog-coverage-evidence.md).

```text
run_id uuid PK FK -> ingestion_runs.run_id
source_url text
catalog_sha256 text
retrieved_at timestamptz
coverage_start timestamptz
coverage_end timestamptz
accepted_rows integer
```

The SHA-256 is lowercase 64-character hex, `accepted_rows > 0`, and
`coverage_start < coverage_end <= retrieved_at`. The worker may read and insert
claims but cannot update or delete them. A retry with different catalog bytes
fails its logical run rather than replacing the original claim.

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

Temporary PostgreSQL retry progress for each distinct normalized row requiring processing, including parser-rejected rows. A complete unchanged row in a scheduled run has no checkpoint.

```text
run_id uuid PK
input_key text PK
outcome text
event_id uuid?
created_at timestamptz = now()
```

`outcome` is `inserted`, `revised`, `unchanged`, or `rejected`. Rejected inputs have no event; all other outcomes reference the event that was visible in the page. The checkpoint stores a SHA-256-derived catalog-field key or a bounded parser-row key, never raw source HTML, exception text, or an untrusted URL. Detail-page seconds and origin do not change the catalog-field key during a retry.

`prediction_skip_reason` is nullable immutable evidence for a valid revision that did not create prediction work. Allowed values are `magnitude_below_m1`, `history_coverage_unavailable`, `incomplete_feature_history`, `history_starts_after_required_window`, `history_ends_before_anchor`, and `model_release_unavailable`.

Successful scheduled runs remove their input checkpoints in the same transaction
that saves summary counters. Skipped visible events receive one fenced batch
update to `last_seen_run_id` during reconciliation.
The bounded host job drains older successful scheduled checkpoints and removes
other terminal-run checkpoints after 30 days from `finished_at`. Pending,
running, and retry-wait runs retain their checkpoints. The `ingestion_runs`
outcome counters remain.
See [ADR 0034](../../adr/0034-bound-successful-ingestion-checkpoints.md).

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

Manifest hash is lowercase 64-character SHA-256 hex. Deployment selects `MODEL_RELEASE_ID` explicitly. `SEIS 1.0.1` is the corrected production runtime label; the original `SEIS 1.0` row and manifest remain immutable. Registration verifies the normalized manifest and local artifact hashes. Artifacts remain out of Git and Docker build contexts and mount read-only. A release row does not itself switch deployment configuration. See [release ADR](../../adr/0009-immutable-model-releases-and-ingestion-feature-snapshots.md).

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

The scoped [historical recovery](../../adr/0032-audited-historical-live-prediction-recovery.md) is an exception to ordinary ingestion-time work creation. The operator command creates the same immutable job and dispatch with a required audit after verified coverage becomes available. The revision's original skip reason stays immutable; prediction completion uses it to suppress automatic alerts for recovered historical work.

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
created_at timestamptz = now()
```

The window starts at the linked revision's event time and spans exactly 24 elapsed hours; the Prediction Worker verifies the cross-table equality in its transaction. Count and radius are nonnegative. Enforce `P(M5+) <= P(M4+) <= P(M1+)`, each in `[0,1]`; reject inconsistent outputs instead of reordering them. Magnitude quantiles are all null or all present and ordered `q05 <= q50 <= q95`. Null is not zero. Supersession targets another forecast for the same event and cannot cycle. A check rejects direct self-reference, and the database supersession trigger enforces same-event ancestry and rejects longer cycles. The current forecast is the newest successful result for the latest event revision and configured release, ordered by job request time then job ID. If the latest revision has no success, no current forecast exists; older results may be labelled stale. A newer failed job does not hide an older successful result for the same revision/release.

## Alerts

### `alert_jobs`

One automatic two-channel batch created atomically with a successful current live M1+ forecast, its dispatch, and the required system audit. Historical recovery, historical/backfill work, and expired forecasts create no alert. Migration `20261011_13` implements the content amendment approved on 11 October 2026; [ADR 0047](../../adr/0047-forecast-alert-content-and-delivery-evidence.md) records approval and ownership.

```text
alert_job_id uuid PK
forecast_id uuid UQ
requested_at timestamptz = now()
message_snapshot text  -- general SMS
email_subject_snapshot text?
email_body_snapshot text?
nearby_message_snapshot text?
nearby_email_subject_snapshot text?
nearby_email_body_snapshot text?
content_provenance_snapshot jsonb?
recipient_policy_snapshot jsonb
status alert_job_status = 'pending'
recipient_resolution_completed_at timestamptz?
lease_expires_at timestamptz?
worker_execution_id uuid?
expires_at timestamptz
completed_at timestamptz?
correlation_id uuid
```

UUIDs are caller-generated. All columns are NOT NULL unless marked `?`; unspecified defaults are absent. The six content/provenance additions are either all null for legacy SMS-only jobs or all present for forecast-content jobs. The email-capable Prediction Worker requires all six for new work. Never backfill or rewrite legacy content. `message_snapshot` retains the general SMS body. Frozen nearby wording refers to a saved alert location, never device tracking. Email bodies are plain text and contain fuller model outputs and their limitations.

`content_provenance_snapshot` freezes `rendering_policy_version`, `geographic_lookup_policy_version`, `geographic_dataset_version`, `geographic_dataset_sha256`, `geographic_lookup_limit_km`, `location_label`, `location_source`, `reference_geoname_id`, `reference_distance_km`, `province_code`, and `province_name`. The application validates the versioned shape; SQL requires an object. Resolve the nearest suitable local GeoNames city/municipality representative point within inclusive 100 km. Explicit reviewed province metadata determines `near` labels, not containment or parsed prose. Source fallback preserves the unchanged PHIVOLCS description and nulls the reference/province fields. Dataset provenance remains present on fallback. Districts, independent cities, and ambiguous mappings never invent a province. Package attribution, source hashes, reviewed mapping/exclusions, and a deterministic generator.

`recipient_policy_snapshot` freezes the batch policy. Eligibility remains per-user and per-channel. The renderer uses raw-probability Bulletin likelihood thresholds, matching percentage rounding, and a full configured `/forecasts/{eventId}` URL labelled `View current forecast`. The page may show newer information than the frozen message. Optional outputs remain unavailable; activity radius is not shaking distance or a safety boundary.

[ADR 0048](../../adr/0048-forecast-alert-copy-amendment.md) amends rendering for newly created snapshots with `rendering_policy_version = forecast-alert-v2`. General and nearby SMS/email omit the entire `Original 24-hour forecast window:` line. The original window still governs expiry. SMS bodies omit the `QuakeStrike PH` header because the provider template adds branding; email subjects and bodies retain branding.

Email labels are exactly `Possible further activity radius:` and `Possible maximum magnitude:`. The radius displays `activity_radius_median_km_24h`; maximum magnitude displays only `maximum_magnitude_q50_24h`. The stored q05/q50/q95 outputs remain unchanged. These fields remain email-only. Frozen older snapshots remain immutable; no schema migration, backfill, or grant change is required.

| Constraint | Required rule |
|---|---|
| Existing forecast uniqueness/FK | One batch per forecast; forecast FK uses RESTRICT update/delete. |
| `ck_alert_jobs_message` | Trimmed nonblank general SMS. |
| `ck_alert_jobs_recipient_policy_object` | Recipient policy is a JSON object. |
| `ck_alert_jobs_expiry` | Expiry is later than request time. |
| `ck_alert_jobs_lease` | Resolving/delivering require lease/token; other states clear both. |
| `ck_alert_jobs_completion` | Terminal states require completion time; active states have none. |
| `ck_alert_jobs_email_pair` | General email subject/body have paired nullability. |
| `ck_alert_jobs_forecast_content_group` | All six new additions are null or present together. |
| `ck_alert_jobs_new_content_nonblank` | Every present content field is trimmed and nonblank. |
| `ck_alert_jobs_content_provenance_object` | Present content provenance is an object. |

Indexes remain `ix_alert_jobs_status_expiry(status, expires_at)`, `ix_alert_jobs_requested_at(requested_at)`, and partial `ix_alert_jobs_active_lease(lease_expires_at)` for resolving/delivering. `trg_alert_jobs_assignment_and_snapshots_immutable` invokes `enforce_alert_assignment_and_snapshots_immutable()` and protects forecast assignment, recipient policy, and every SMS/email/provenance snapshot. States remain pending, resolving, delivering, completed, failed, expired. Terminal transitions stop dispatch atomically. Completed means recipients settled, not necessarily delivered. Expiry equals forecast window end transactionally. New sends stop at expiry; late evidence may still change.

Recipient resolution claims pending jobs or recovers expired resolving leases with a fresh execution token. Each recipient write and checkpoint requires the same unexpired token and an unexpired forecast. Production ownership checks read PostgreSQL `clock_timestamp()` after lock acquisition and before page/checkpoint commit; lock waits and host-clock skew never extend ownership. Isolated tests can inject a deterministic clock.

The worker reads the fourteen approved account columns in bounded UUID order without account locks or writes. Each execution captures a maximum user UUID; accounts created beyond that bound do not extend its scan. Restart scans begin again with a fresh bound; unique constraints retain the original destination and resolution evidence. Email uses the Backend's stored canonical destination, including its preserved local-part case. SMS uses the stored Philippine E.164 destination.

Resolution requires active accounts, completed onboarding, channel opt-in, verified destinations, and the inclusive observed-magnitude threshold. Nearby-only selection calculates Haversine distance between the observed epicenter and saved coordinates using Earth radius `6371.0088` km. Selection includes calculated distance equal to the user's `alert_trigger_distance_km`. Geographic display labels do not affect selection.

A proven unsupported SMS network excludes only SMS. An unavailable SMS support lookup preserves eligible email rows and leaves status resolving with a null completion checkpoint. The same live root claim permits subsequent email processing; provider outages do not authorize fallback email or declare the roster complete.

Only a complete candidate scan sets `recipient_resolution_completed_at`. A nonempty roster advances to delivering and retains the root lease/token. An empty roster sets completed, records completion time, clears the root lease/token, and stops the dispatch atomically. Successful alert publication resets its per-publication attempt count; recovery does not consume a lifetime resolution budget. Alert publication defaults to disabled through `ALERT_RESOLUTION_ENABLED`. Submission additionally requires `ALERT_DELIVERY_ENABLED`.

The handler uses explicit provider boundaries for SMS and email submission. It resolves the bounded scan, then drains committed recipients under the same live claim. Eligible email may drain while SMS support leaves resolution incomplete; the checkpoint remains null. Delivery recovers completed rosters without rescanning accounts. The explicit runtime constructs both providers only after configuration and restricted-capability checks. Provider authentication and delivery proof require separate target-environment verification. Both enablement gates default to false. Total handler execution has a 240-second budget with 30 seconds reserved for bounded provider calls and settlement. Resolution commits a partial page and leaves its checkpoint null when that budget ends. Repeated scans skip already persisted channel evidence, so slow successful support lookups still advance the roster without rewriting immutable rows.

The opt-in runtime uses separate process-owned UUID cursors for known-reference SMS polling and job maintenance. Maintenance runs even without SMS candidates and settles callback-completed email batches without queue redelivery. Expired sending leases remain recovery candidates even when the root job is terminal. Polling and maintenance have separate finite budgets; failures do not authorize resubmission or provider timestamp changes. IPROG detection/submission/polling and Brevo submission use a 12-second elapsed deadline across headers and body, plus a 16 KiB decoded response-body limit. The Linux main/prefork runtime cancels the synchronous call, closes streams, and restores its signal handler; no background submission continues after return. Default real transport fails closed outside that supported execution context or when another owner already holds the alarm timer. Interrupted submissions remain unknown; known references and immutable delivery evidence retain their existing reconciliation rules.

Explicit legacy retirement selects only active jobs with all six content additions null, no live root/dispatch claim, no attempt, and only pending/retry-wait recipients. One transaction expires overdue jobs or fails other applicable jobs, settles unsent recipients, stops dispatch, and inserts a `retire_legacy_alert` system audit. The bounded reason is `legacy_content_retired`; audit metadata contains identifiers, statuses, recipient count, and content hash. The operation never changes immutable content. Preview is read-only, and repeated terminal retirement adds no duplicate audit.

The finite verification runner accepts only a selected new complete-content job and an isolated synthetic account in the disposable database. Private destination authorization and one-call channel budgets prevent ordinary backlog delivery. Selected known-reference reconciliation retains the same evidence rules and does not reopen submission. Runtime operations add no tables, columns, enums, triggers, indexes, ownership, or grants. See [alert operations](../../operations/alert-runtime.md).

### `alert_recipients`

One destination per user/channel/batch, with immutable resolution evidence and mutable delivery summary.

```text
recipient_id uuid PK
alert_job_id uuid
user_id uuid?
channel text
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

`alert_recipient_status` contains pending, sending, retry_wait, accepted, delivered, failed, unknown, skipped, expired. `fk_alert_recipients_job` references alert_jobs with RESTRICT update/delete. `fk_alert_recipients_user` references users with RESTRICT update and SET NULL delete. Resolution requires an account. Controlled account removal first settles a sending recipient; a detached recipient cannot start sending. Suspension/closure uses account state without deleting evidence.

| Constraint | Required rule |
|---|---|
| `uq_alert_recipients_job_channel_destination` | Unique `(alert_job_id, channel, destination_snapshot)`. |
| `ck_alert_recipients_channel` | Channel is email or SMS. |
| `ck_alert_recipients_destination` | Trimmed nonblank destination; SMS matches Philippine E.164 `^\+639[0-9]{9}$`. Email normalization uses the Backend canonicalization. |
| `ck_alert_recipients_key` | Trimmed nonblank logical delivery key. |
| `ck_alert_recipients_eligibility_object` | Resolution evidence is an object. |
| `ck_alert_recipients_sending_claim` | Sending requires lease/token; other states clear both. |
| `ck_alert_recipients_retry` | Retry wait alone has next attempt time. |
| `ck_alert_recipients_delivered` | Delivered alone has delivery time. |
| `ck_alert_recipients_error` | Present last error code is trimmed and 1–100 characters. |

| Index | Columns and predicate |
|---|---|
| `uq_alert_recipients_job_user_channel` | UNIQUE `(alert_job_id, user_id, channel)` where user_id is present. |
| `ix_alert_recipients_user` | `(user_id)` where user_id is present. |
| `ix_alert_recipients_job_status` | `(alert_job_id, status)`. |
| `ix_alert_recipients_retry` | `(next_attempt_at)` where status is retry_wait. |
| `ix_alert_recipients_sending_lease` | `(processing_lease_expires_at)` where status is sending. |

The unique logical key has its ordinary unique-constraint index. `trg_alert_recipients_evidence` invokes `enforce_alert_recipient_evidence()`. It freezes identity, channel, destination, selection evidence, resolution time, and logical key. A user may detach to null but cannot be reassigned. Delivered summaries cannot regress.

Eligibility requires an active account, completed onboarding, explicit channel opt-in, verified current destination, and observed anchor magnitude at or above the user's threshold. SMS additionally requires current approved ordinary sender support. Nearby-only compares the observed epicenter with the saved point using Haversine distance and Earth radius 6371.0088 km. Equality qualifies. Forecast activity radius and the display lookup limit never determine eligibility. Before every provider call, recheck all settings, destination, verification, account, magnitude, distance, sender support, and expiry. Lost eligibility becomes skipped. Resolve idempotently and checkpoint only after the full scan.

Resolution JSON records policy version, channel, account/onboarding state, enabled setting, verification state, observed magnitude, threshold, nearby-only state, and saved location/radius/calculated distance when used. Coordinates and snapshots remain private and excluded from public responses and technical logs.

A confirmed unsupported SMS destination also records immutable resolution evidence with `ordinary_sms_supported: false`, status `skipped`, and `last_error_code` `sms_sender_unsupported`. Retries skip that channel for the same alert batch, so negative support checks advance the scan as successful checks do. Support lookup failures remain unresolved; they never prove an unsupported destination or block independent email resolution. Each new alert batch checks support again. A completed scan with only settled recipients completes the batch without creating delivery attempts.

### `alert_delivery_attempts`

One durable provider-call attempt per recipient; persist sending before the external call, outside that call's SQL transaction.

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
content_variant text
eligibility_snapshot jsonb
provider_evidence_snapshot jsonb?
```

`alert_delivery_status` contains sending, accepted, delivered, failed, unknown. `fk_alert_delivery_attempts_recipient` references alert_recipients with RESTRICT update/delete. Acceptance means provider submission, not inbox/handset delivery. Crash recovery closes interrupted calls as unknown; unknown never authorizes automatic resend. `finished_at` is local closure, not receipt. `provider_status_at` is verified provider event time. Retain accepted/unknown/delivered evidence through expiry and reconcile late outcomes.

| Constraint | Required rule |
|---|---|
| `uq_alert_delivery_attempts_recipient_number` | Unique `(recipient_id, attempt_number)`. |
| `ck_alert_delivery_attempts_number` | Attempt number is at least 1. |
| `ck_alert_delivery_attempts_provider` | Provider is iprog or brevo. |
| `ck_alert_delivery_attempts_reference` | Present provider ID is trimmed and 1–512 characters. |
| `ck_alert_delivery_attempts_closure` | Sending alone has no finish time. |
| `ck_alert_delivery_attempts_finish_order` | Finish is not before start. |
| `ck_alert_delivery_attempts_variant` | Selected content is general or nearby, stored as checked text. |
| `ck_alert_delivery_attempts_eligibility_object` | Send-time evidence is an object. |
| `ck_alert_delivery_attempts_provider_evidence_object` | Present provider evidence is an object. |
| `ck_alert_delivery_attempts_errors` | Present errors are trimmed; code is 1–100 and message is 1–500 characters. |

| Index | Columns and predicate |
|---|---|
| `uq_alert_delivery_attempts_one_sending` | UNIQUE `(recipient_id)` where status is sending. |
| `ix_alert_delivery_attempts_provider_reference` | Non-unique `(provider, provider_message_id)` where reference is present. |
| `ix_alert_delivery_attempts_reconcile` | `(provider, status, provider_status_at, started_at)` where accepted/unknown. |

The recipient-number unique index covers the recipient FK; do not add a duplicate index. `trg_alert_delivery_attempts_evidence` invokes `enforce_alert_attempt_evidence()`. It enforces email/Brevo and SMS/IPROG pairing; freezes identity, number, provider, start, correlation, variant, and send-time evidence. A null provider reference may become known; a known reference cannot change. Delivered cannot regress. Attempt eligibility additionally records check time, expiry, and SMS sender-support evidence. Retries preserve prior attempts and insert new evidence.

Provider evidence may change during reconciliation. Application validation allows only normalized operation, safe provider code, HTTP status, error category, retry delay, encoding, estimated segments, and provider-supplied charging units. Never persist raw provider payloads, credentials, OTPs, message content, destinations, or credential-bearing URLs in diagnostic evidence. SQL validates the outer object; application validates the allowlist.

Submission lifecycle uses four actual provider calls at most: the initial call and three confirmed-transient retries after 30, 120, and 600 seconds. Trustworthy provider timing cannot be shortened. Support preflight retries consume no submission budget. Permanent credential/credit failures and uncertain calls never retry. Each new call rechecks eligibility and records new immutable evidence before calling outside SQL. Expiry prevents new calls but preserves accepted/unknown/sending evidence for later reconciliation. Outcome writers lock recipient before attempt; job settlement occurs separately in dispatch-then-job order. Worker submission completion cannot overwrite a callback-completed outcome or immutable provider reference. Final account, exact attempt, recipient/root token, lease, and expiry checks run after attempt commit and immediately before the call. Changed settings or lost ownership close a provably unsubmitted attempt conservatively; an interrupted request remains unknown. Safe late acceptance/uncertainty retains references and normalized metadata without restoring send ownership. Completed resolution settles only after no pending, retry_wait, sending, accepted, or unknown recipients remain. Expiry settles pending/retry_wait rows and the job/dispatch atomically, preserving active and reconciliation evidence. A completed invocation releases its root lease and schedules the existing dispatch for due unsent work or a fixed bounded 60-second maintenance cadence. Publication and support checks do not spend message-submission retries.

Verified status polls may lack a provider event timestamp. In that case, `provider_status_at` remains null; local database time supplies only `finished_at` or `delivered_at`. Such outcomes advance by strength and cannot regress delivered or reopen failed acceptance. Timestamped outcomes retain the approved older/equal timestamp rules. Reconciliation updates exact attempts and newest recipient summaries independently of root ownership and forecast expiry; verified delivery proof can advance an earlier attempt's recipient summary. Separate maintenance settles job/dispatch after outcome locks are released and preserves terminal expired jobs.

### Narrow Backend callback capability and ownership

`quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text) RETURNS text` takes attempt ID, provider reference, normalized outcome, provider time, and optional sanitized error code. It returns only applied, ignored, uncorrelated, conflict. Valid outcomes are accepted, delivered, failed. Backend authenticates callbacks before executing this function and gets no direct delivery-table mutation grant. Early correlation uses documented Brevo X-Mailin-custom with the pre-created attempt UUID. Without a tag, an already-known reference must identify exactly one attempt; never match by destination. Conflicting references fail closed.

The SECURITY DEFINER function has fixed `pg_catalog, public` search path and migration ownership. PUBLIC execution is revoked. All lifecycle writers lock recipient before attempt. Updates to both records commit atomically. Older timestamps are ignored; equal timestamps allow delivery over failure over acceptance. Delivered cannot regress; acceptance cannot reopen failure. Only the newest attempt updates a non-delivered recipient summary, while delivery proof can advance the summary. Late evidence can close another attempt without regressing a delivered summary. Worker outcome persistence must retain callback-completed evidence and fence claims with leases/tokens.

Backend acknowledges only committed updates or verified no-ops. Authenticated transient database failure and unresolved correlation return HTTP 429, because [Brevo's documented retries](https://developers.brevo.com/docs/retry-mechanism) discard 5xx. Actual callback behavior still requires controlled verification.

Brevo submission sends one frozen recipient, subject, and plain-text body, with an escaped HTML representation of the same body. The worker places only `quakestrike-attempt:<uuid>` in `X-Mailin-custom`; execution tokens never enter the request. Both submission and callback normalization remove one surrounding angle-bracket pair from a bounded, control-free provider reference. HTTP 201 plus a usable message ID means accepted, not delivered. Transport interruption, generic server failure, or unusable response preserves unknown evidence without automatic resend. Only an explicit HTTP 429 rejection permits retry, with valid Retry-After preserved and no adapter-internal retries.

`POST /api/v1/callbacks/brevo` authenticates a separate `BREVO_CALLBACK_TOKEN` through constant-time digest comparison before parsing JSON. Missing configuration denies ingress. The callback accepts at most 32 KiB of uncompressed JSON and requires an allowed event, bounded reference, and safe-integer `ts_event` in UTC seconds. Event time may be old after expiry, but cannot exceed receipt time by five minutes; `ts_epoch` and prose dates supply no fallback. A supplied custom attempt tag must match the exact UUID format; an absent tag permits only the function's unique-reference fallback.

Request and deferred evidence map to accepted; delivered maps to delivered; hard/soft bounce, blocked, error, and invalid-email evidence map to failed. These callback failures never authorize resubmission; later verified delivery can strengthen failed evidence. The same restricted Backend Pool executes BEGIN, transaction-local read-only off, the narrow function, and COMMIT. Rollback and connection release preserve role defaults and ordinary read-only transactions. Committed applied/ignored returns 204, unresolved correlation returns 429, reference conflict returns 409, and processing failures return 429 with a bounded Retry-After. Logs contain request identity and bounded outcomes/categories, excluding raw payloads, addresses, message content, secrets, and exception prose.

| Role | Approved access |
|---|---|
| quakestrike_migration | Own new tables, enums, and all four alert functions; apply schema explicitly. |
| quakestrike_worker | SELECT/INSERT on recipients/attempts; UPDATE only named lifecycle/diagnostic columns below; USAGE on both new enums. |
| quakestrike_backend | EXECUTE only on the reconciliation function; existing account/public permissions unchanged. |
| PUBLIC | No execution on the four alert functions; no USAGE on the two new enums. |

Worker alert-job UPDATE columns are status, recipient_resolution_completed_at, lease_expires_at, worker_execution_id, completed_at. Recipient UPDATE columns are status, next_attempt_at, delivered_at, last_error_code, processing_lease_expires_at, worker_execution_id. Attempt UPDATE columns are provider_message_id, status, finished_at, provider_status_at, error_code, error_message, provider_evidence_snapshot. Worker reads only these account fields: user_id, email, email_verified_at, email_enabled, mobile_number, mobile_verified_at, sms_enabled, alert_trigger_magnitude, nearby_alerts_only, alert_location_latitude, alert_location_longitude, alert_trigger_distance_km, account_status, onboarding_completed_at. No account writes are granted. Existing dispatch writes and append-only audits remain sufficient. Optional observer default SELECT continues covering new tables; no new Console role or grant is introduced.

Migration ownership follows execution as quakestrike_migration. Explicit provisioning repairs ownership and reapplies restricted grants. No extra login, callback inbox, dispatch table, account column, or technical-log table is authorized. Additive migration preserves legacy rows. Destructive downgrade refuses retained recipients, attempts, or new content; prefer stopping delivery while retaining schema. Shared development/production application and ordinary-user sends need separate authorization.

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

Actor type is `user`, `system`, or `anonymous`; the matching user/service field is required only for its type. A `user` is a Clerk-backed Bulletin account, not a Cloudflare Access operator. Outcome is `succeeded`, `denied`, or `failed`. Target type/id are paired when a target exists; do not fabricate a target for an early denial. Target fields are historical descriptions, not polymorphic FKs. Account mutation and success audit commit together. Rollback failures and denials use a bounded separate path and never report committed success. Normal application roles cannot update or delete audit rows. Metadata contains no secrets. Console page visits and sensitive-field reveals belong in `operator_access_events`.

Until the accounts migration creates `users`, this phase rejects `actor_type = 'user'` so `actor_user_id` cannot become an orphan. That migration removes the temporary check and adds the required `users` foreign key. System audits needed by prediction completion remain available now.

### `operator_access_events`

Append-only evidence of which verified Cloudflare Access operator opened a
Console page or detail and which sensitive user fields they revealed. This
table is separate from Clerk-backed business `audit_logs`; it has no FK to
`users`.

```text
access_event_id uuid PK
occurred_at timestamptz = now()
operator_sub text
operator_email text
event_type text
route_template text
target_type text?
target_id text?
field_category text?
reason text?
request_id uuid?
```

`event_type` is `page_open`, `detail_open`, or `sensitive_reveal`. A reveal's
`field_category` is `name`, `email`, `mobile`, or `alert_location`, and its
reason is bounded to 500 characters. The target
type and ID are both absent for a general page open and both present for a
detail open or reveal. Only a reveal has a field category and nonblank
operator-entered reason; other events leave those fields null. The actor
values come only from a verified Access application JWT. Store route
templates, not raw paths, query strings, search terms, or revealed values.
Record page opens and detail opens before their protected data response;
record each reveal after reading only the requested fields but before returning
them. Deny that response
if the insert fails. Background refreshes and filter changes do not create
events. `SELECT, INSERT` on this table are the Console role's only grants
beyond its approved business-table `SELECT` grants. It has no `UPDATE` or
`DELETE`; a dedicated host cleanup role removes rows older than 180 days in
bounded batches. Cloudflare Access keeps separate login-attempt evidence.
See [ADR 0035](../../adr/0035-cloudflare-access-operations-console.md).

### `technical_logs`

Selected, sanitized warnings, errors, slow requests, and maintenance messages for protected Console queries. Container stdout/stderr carries ordinary and outage diagnostics.

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

Operations are `backup`, `restore_test`, `retention_cleanup`; states are `running`, `succeeded`, `failed`, `abandoned`. Terminal finish is no earlier than start; running has no finish. Affected count is nonnegative. Successful backup needs artifact reference and SHA-256 checksum. Restore test needs a related backup and, on success, verification summary. Application logic checks that the referenced row is a backup; no self-reference. A failed backup may have no artifact. The next maintenance reconciliation marks interrupted runs abandoned. Restricted scripts write results; the Console server reads them directly with its restricted database role.

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
| `earthquake_events.first_seen_run_id`, `.last_seen_run_id` | `ingestion_runs` | RESTRICT |
| `earthquake_events.superseded_by_event_id` | `earthquake_events` | RESTRICT |
| `earthquake_event_revisions.event_id`, `.ingestion_run_id` | `earthquake_events`, `ingestion_runs` | RESTRICT |
| `earthquake_event_revisions.(source_bulletin_id, event_id)` | `earthquake_bulletin_event_identities.(source_bulletin_id, event_id)` | RESTRICT |
| `earthquake_bulletin_event_identities.event_id` | `earthquake_events` | RESTRICT |
| `ingestion_run_inputs.run_id`, `.event_id` | `ingestion_runs`, `earthquake_events` | RESTRICT |
| `prediction_jobs.event_revision_id`, `.model_release_id` | `earthquake_event_revisions`, `model_releases` | RESTRICT |
| `prediction_attempts.job_id`; `forecasts.job_id` | `prediction_jobs` | RESTRICT |
| `forecasts.supersedes_forecast_id` | `forecasts` | RESTRICT |
| `alert_jobs.forecast_id` | `forecasts` | RESTRICT |
| `alert_recipients.alert_job_id`; `alert_delivery_attempts.recipient_id` | `alert_jobs`; `alert_recipients` | RESTRICT |
| `alert_recipients.user_id` | `users` | SET NULL |
| `audit_logs.actor_user_id` | `users` | RESTRICT after the accounts migration; user actors are rejected before it |
| `maintenance_runs.related_backup_run_id` | `maintenance_runs` | RESTRICT |

An alert job requires one forecast and `UNIQUE (forecast_id)` allows no second job for the same forecast. A job can have zero or one dispatch by FK/UQ, but creation transactions require one for new background work. `technical_logs` and `operator_access_events` have no business FK. Closing an account clears its current phone binding; anonymize retained users rather than deleting their audit evidence. Physical deletion succeeds only when RESTRICT references are absent. Business retention requires a separately reviewed procedure; technical-log and Console-event cleanup cannot cascade through history.

[ADR 0054](../../adr/0054-manual-vps-test-account-cleanup.md) permits a narrow manual exception for owner-selected disposable test accounts on the VPS.
That procedure deletes their dependent evidence explicitly with the migration login; it adds no schema change or ordinary application permission.

## Index plan

PK and UQ constraints create indexes; do not duplicate an index already covered by a useful left prefix. Index every remaining FK lookup column. Add indexes for these query paths:

- Unique normalized current mobile number; revision group ID and non-unique bulletin-ID lookup. `UNIQUE (event_id, revision_number)` supports latest revision by reverse scan.
- `prediction_jobs(event_revision_id, model_release_id, requested_at DESC)`.
- Dispatch `next_dispatch_at, dispatch_id` for pending/retry-wait and `lease_expires_at` for dispatching; target UQs support job lookup.
- Prediction running-attempt lease and partial running-job uniqueness; active ingestion/alert processing leases.
- Alert status/expiry and request time; recipient job/channel/status, retry time, sending lease, and user ID.
- Delivery provider/reference when present; recipient/attempt sequence uniqueness.
- Audit occurrence time, actor/time, target/time, and correlation; Console access-event occurrence, operator/time, and target/time; technical-log occurrence, module/severity/time, category/status/time, request, and correlation; maintenance operation/start time.

Queue searches must be indexed. Console historical views are paginated and date-bounded; the user list is paginated. Console pages query only `ingestion_runs`, `ingestion_run_inputs`, `source_catalog_evidence`, `job_dispatches`, `prediction_jobs`, `prediction_attempts`, `forecasts`, `model_releases`, `alert_jobs`, `alert_recipients`, `alert_delivery_attempts`, `audit_logs`, `operator_access_events`, `technical_logs`, `maintenance_runs`, and `users`, with linked `earthquake_events` and `earthquake_event_revisions` for context. This is a named operational read surface, not an all-table SQL browser. The Console supports targeted user ID or partial phone lookup. The phone may be used in a server-side search predicate, but names, email, phone, and saved alert-location coordinates are not selected for list responses and are returned only after an audited field reveal. Add a search index only when its query plan requires one; the lookup implementation is a Console application decision. Do not add JSON-wide indexes, partitions, or host-metric tables without measured need. Technical-log and Console-event deletion use manageable batches.

## Transactions and cross-table rules

1. Account changes check Clerk ownership. Email/password signup verifies the Clerk email before profile creation. The Backend mirrors the current verified Clerk email and pauses email alerts during a pending email change; a confirmed replacement updates the mirror and restores the existing email preference. A provider-confirmed phone claim or replacement checks the pending user/number pair, current number uniqueness, sender support, and account state. Starting phone replacement first disables SMS; the confirmed replacement atomically updates the current verified phone but does not opt in. The user enables either channel through a separate explicit action. Final preference save sets onboarding completion and required success audit in one transaction. Other account and alert-setting changes also commit with required success audits. A verified email does not prove phone possession.
2. Beat commits the pending ingestion run with its dispatch. Dispatcher claims and publishes after commit. Worker processing preserves run/job identity across retries and uses a separate processing lease. Redis is at-least-once; database claims and uniqueness make repetition safe.
3. For each accepted event, Ingestor locks or creates stable identity, appends a changed revision, builds the ten-feature snapshot from prior PostgreSQL history, hashes canonical JSON, and creates any eligible prediction job plus dispatch in one transaction. Run counters checkpoint separately. Redis publication occurs after commit. No future data, uncertain same-minute ordering, retrospective family metadata, missing URL, missing both IDs, or incomplete snapshot can pass the prediction gate. See [atomic processing](../../adr/0016-atomic-event-processing-and-release-registration.md) and [revision idempotency](../../adr/0022-idempotent-revisions-and-bootstrap-gates.md).
4. Prediction completion validates the current execution token. Forecast, job/attempt success, its automatic alert job and dispatch, and system audit commit together. Every current, unexpired live M1+ forecast creates exactly one alert job with both channel-content snapshots; backfill, historical, and expired work do not. The Alert Worker later applies each user's shared trigger magnitude and optional nearby-only radius to the observed anchor, not predicted outputs.
5. Alert resolution inserts unique eligible email and/or SMS recipients and checkpoints completion only after candidate processing. Before a provider call, the worker claims and rechecks one recipient, then persists an attempt. An external email or SMS call cannot join a SQL transaction. Unknown results require provider reconciliation. An expiry sweep stops new sends and marks unsent recipients expired, without rewriting accepted/unknown/delivered evidence. Late callbacks may close earlier attempts.
6. Console page loads and detail opens insert `operator_access_events` before returning protected data. A sensitive-field reveal reads only the requested values, then inserts its target, category, and reason before returning them. If the insert fails, the response fails closed. These inserts do not authorize business-table mutations.

## Initialization, retention, and policy choices

Apply hand-reviewed Alembic migrations, verify and explicitly register the selected `SEIS 1.0.1` manifest and artifact hashes, run the resumable bootstrap, check source snapshot integrity, identifiers, URLs, row counts, and seven-day history, then start Dispatcher/Ingestor and enable Beat. Bootstrap records a `backfill` run and uses the same normalization and reconciliation as live ingestion. Service startup never runs migrations, imports data, or silently changes releases. Historical snapshots remain source evidence outside Git; PostgreSQL is the only live event store. See [startup](../../adr/0019-explicit-startup-and-runtime-configuration.md) and [readiness](../../adr/0022-idempotent-revisions-and-bootstrap-gates.md).

Choose and version the recipient policy before enabling delivery; `recipient_policy_snapshot` records the batch policy and `eligibility_snapshot` records channel, the user's enabled setting, trigger magnitude, observed anchor magnitude, nearby-only setting, saved alert location and radius when used, calculated distance, account state, and current destination-verification state. Treat saved coordinates and snapshots as private account data; do not expose them in public responses or technical logs. Successful scheduled ingestion checkpoints are removed when summaries commit; other terminal-run checkpoints expire after 30 days under [ADR 0034](../../adr/0034-bound-successful-ingestion-checkpoints.md). Console access events expire after 180 days. The technical-log period and business-audit, run-summary, and delivery-evidence retention periods remain separate decisions before production; do not apply Console or technical-log cleanup to them. IPROG SMS is selected with the existing shared sender, subject to tested OTP, network coverage, callback or polling reconciliation, sender/fallback behavior, and cost before production. Unknown or unsupported ordinary sender coverage blocks SMS opt-in and sending. Brevo Transactional Email API is selected for alert email; authenticate the sending domain and test webhook reconciliation, bounces, and cost before production delivery. Short-lived pending OTP state is not a durable business table; codes and complete provider responses must not enter audit or technical logs. Host maintenance scripts, not a database scheduling extension, own cleanup, backup, and restore-test schedules. The [architecture specification](../ARCHITECTURE/ARCHITECTURE.md#logging-diagnostics-and-maintenance) defines diagnostic fallback and off-VPS backup requirements.

## References

- [ERD](ERD.png), [architecture](../ARCHITECTURE/ARCHITECTURE.md), [DFD](../CFD-DFD/DFD-Level1.png), [context](../../../GLOSSARY.md), and [ADRs](../../adr/).
- Source schema: `C:\Projects\SAM_Capstone\capstone\docs\07-erd-schema-specification.md`.
- Source table guide: `C:\Projects\SAM_Capstone\capstone\docs\08-database-table-guide.md`. Both sources remain unchanged.
