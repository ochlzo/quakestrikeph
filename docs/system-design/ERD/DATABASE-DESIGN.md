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

`job_dispatches` is placed with D2 for the DFD, but it targets ingestion, prediction, or alert work. PostgreSQL is live truth; Redis carries commands and does not replace these records. CSV and bootstrap snapshots are finite import inputs, not live stores. See the [Level 1 DFD](../CFD-DFD/DFD-Level1.png) and [domain glossary](../../../CONTEXT.md).

## Accounts and access

### `users`

One Bulletin account maps uniquely to a stable Clerk user ID from email/password or Google sign-in. This table owns the profile, the Backend mirror of the current Clerk-verified email, the current verified alert phone, channel opt-ins, shared alert rules, onboarding completion, and account status. Clerk owns passwords, email identity, verification, and sessions. Operators authenticate through Cloudflare Access and do not have `users` rows by virtue of Console access.

```text
user_id uuid PK
clerk_user_id text UQ
first_name text?
middle_name text?
last_name text?
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

`account_status` is `active`, `suspended`, or `closed`. `display_name` is required when the Backend creates the profile; other name parts may be absent. The Backend creates a row only after Clerk completes email verification or Google authentication. A missing row means the profile step is unfinished; a null `onboarding_completed_at` means the alert-preferences step is unfinished. The final preference save sets that timestamp, even when both channels are off. Both receive switches default to false and become true only by explicit audited opt-in. Enforce `CHECK (onboarding_completed_at IS NOT NULL OR (NOT email_enabled AND NOT sms_enabled))` and `CHECK (account_status <> 'closed' OR (NOT email_enabled AND NOT sms_enabled AND mobile_number IS NULL AND mobile_verified_at IS NULL))`. An active account still needs completed onboarding and a current verified destination before delivery.

`email` mirrors the current Clerk email; it is not the local identity key and has no independent uniqueness claim. `email_verified_at` is set only after trusted Clerk evidence for that exact current address. A requested email change sets it null to pause email delivery while Clerk holds the pending replacement; after verification, the Backend updates `email` and `email_verified_at` together and the existing `email_enabled` choice can resume. Restrict direct Clerk email changes outside this controlled flow or synchronize them with verified, idempotent Clerk events before any email send. If the mirror is missing or inconsistent, fail closed. A closed account cannot have an enabled channel.

Mobile numbers are normalized E.164. `UNIQUE (mobile_number)` permits multiple nulls but prevents one current number from belonging to two accounts. Enforce `CHECK ((mobile_number IS NULL) = (mobile_verified_at IS NULL))`. A short-lived Redis verification attempt, tied to the signed-in Clerk user and proposed phone, does not change this row until IPROG confirms the entered code. Expired or lost attempts cannot verify a phone. An unsupported or unknown ordinary shared-sender network stops before OTP and cannot enable SMS. A second account cannot claim a bound phone, and phone possession does not merge accounts. Phone replacement requires recent interactive Clerk reverification. Starting it sets `sms_enabled = false` with an audit while retaining the old binding; verified replacement atomically updates the number and timestamp and still requires a new opt-in. Closing an account clears the current phone and verification time and disables both channels, releasing the phone uniqueness claim while preserving historical evidence. SMS delivery requires a verified current number and current sender support. `alert_trigger_magnitude` is finite and at least `1.0`. `nearby_alerts_only` defaults to false. The alert location is one user-selected fixed point, not continuous device tracking. Latitude and longitude are either both null or both present, finite, and within `[-90, 90]` and `[-180, 180]`; distance is finite and greater than zero kilometres when present. Enabling nearby-only alerts requires both coordinates and a distance. Disabling it may retain those values for later use, but they do not affect eligibility while it is off. There is no local password or operator-role table. The Backend writes accounts; workers read only what delivery needs. See [ADRs 0037](../../adr/0037-clerk-free-bulletin-authentication.md) and [0038](../../adr/0038-email-and-sms-alert-preferences.md).

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

One automatic two-channel batch with immutable SMS/email content and a recipient-policy snapshot. The Prediction Worker creates it with a successful current live forecast. The current migration already has `message_snapshot` for SMS; email fields below are a planned forward schema change.

```text
alert_job_id uuid PK
forecast_id uuid UQ
requested_at timestamptz = now()
message_snapshot text  -- SMS body
email_subject_snapshot text?
email_body_snapshot text?
recipient_policy_snapshot jsonb
status alert_job_status = 'pending'
recipient_resolution_completed_at timestamptz?
lease_expires_at timestamptz?
worker_execution_id uuid?
expires_at timestamptz
completed_at timestamptz?
correlation_id uuid
```

`UNIQUE (forecast_id)` enforces one alert batch per forecast, whether zero, one, or both channels have recipients. Every newly committed current forecast for a live M1+ anchor creates that job while its 24-hour window remains open. Backfill, historical, and expired work create no alert. `message_snapshot` remains the immutable SMS body. The email subject/body are both null only for legacy SMS-only jobs created before the email feature; enforce a paired-null check, trim and nonblank checks when present, and require both on every new job after the email-capable worker is enabled. The channel-content and recipient-policy snapshots are fixed in the prediction-completion transaction. Recipient eligibility is evaluated later against each user's shared alert trigger magnitude and optional nearby-only rule. Email content is separate from Clerk's authentication mail. A reviewed forward migration must add the email fields and extend the existing immutability trigger; the Prediction Worker, Alert Worker, and migrations need a compatible rollout before email delivery is enabled.

States are `pending`, `resolving`, `delivering`, `completed`, `failed`, and `expired`. Active resolving/delivering ownership needs lease/token. Terminal states need `completed_at` and stop dispatch; `completed` means recipients settled, not all delivered. Accepted/unknown recipients stay under reconciliation until expiry. `expires_at` equals forecast `window_end` and must be later than creation; verify equality transactionally. No new send begins at or after expiry. Late outcomes may still update evidence. Cancellation is deferred and has no reserved state or columns.

### `alert_recipients`

One resolved destination per user, channel, and batch, with selection evidence and current delivery summary. Alert Worker writes and rechecks it.

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

`channel` has the named check `IN ('email', 'sms')`. `UNIQUE (alert_job_id, channel, destination_snapshot)` applies after email normalization or E.164 phone normalization, plus a partial `UNIQUE (alert_job_id, user_id, channel) WHERE user_id IS NOT NULL` to prevent two destinations on one channel for the same user. One public-user resolution requires a user; the FK may later be set null for controlled account removal, but a detached row cannot start a send. States are `pending`, `sending`, `retry_wait`, `accepted`, `delivered`, `failed`, `unknown`, `skipped`, and `expired`. Sending needs lease/token; other states clear them. Retry wait alone needs `next_attempt_at`. Delivered alone needs `delivered_at`. Accepted awaits provider outcome; unknown is held for reconciliation, never blind resend. Eligibility requires an active account with completed onboarding, observed anchor magnitude greater than or equal to its `alert_trigger_magnitude`, and the channel's enabled setting and verified current destination. Email requires `email_enabled = true` and `email_verified_at` for the current mirrored Clerk email. SMS requires `sms_enabled = true`, `mobile_verified_at` for the current number, and current IPROG shared-sender support. When `nearby_alerts_only` is true, the observed earthquake epicenter must also be within the inclusive `alert_trigger_distance_km` radius of the saved alert location. Use Haversine distance in kilometres with Earth radius `6371.0088 km`; the forecast activity radius does not define this filter. The snapshot records the evaluated shared settings, channel, destination-verification state, observed magnitude, calculated distance when applicable, and policy version. Before each provider call, recheck account, current destination, channel setting, magnitude, nearby-only setting, current alert location and distance, sender support for SMS, and expiry. Lost eligibility becomes skipped. Resolution uses idempotent inserts and marks completion only after the full candidate scan. Cancellation is deferred and has no reserved recipient state.

### `alert_delivery_attempts`

One persisted SMS or email provider-call attempt per recipient. Its state cannot claim a crashed call definitely failed or delivered; the recipient supplies the channel.

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

`UNIQUE (recipient_id, attempt_number)`, number at least 1; partial `UNIQUE (recipient_id) WHERE status = 'sending'`. States are `sending`, `accepted`, `delivered`, `failed`, `unknown`. Persist `sending` before the external call. It has no finish time; later states have one. Crash recovery closes it as unknown at recovery time, with an interrupted-call code. `finished_at` is local closure, not handset receipt or email inbox arrival. Set `provider = 'brevo'` for email and store the Brevo transactional API's returned message ID in `provider_message_id`; this records acceptance, not delivery. Index provider plus reference, but do not assume provider reference is unique across retry rows. Authenticated, idempotent Brevo transactional webhooks update the attempt and recipient atomically; verified IPROG callback or polling does likewise. Neither can regress delivered to accepted. Bounce, blocked, error, or provider rejection maps to failed, not delivered.

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

- [ERD](ERD.png), [architecture](../ARCHITECTURE/ARCHITECTURE.md), [DFD](../CFD-DFD/DFD-Level1.png), [context](../../../CONTEXT.md), and [ADRs](../../adr/).
- Source schema: `C:\Projects\SAM_Capstone\capstone\docs\07-erd-schema-specification.md`.
- Source table guide: `C:\Projects\SAM_Capstone\capstone\docs\08-database-table-guide.md`. Both sources remain unchanged.
