# QuakeStrike PH domain context

This glossary defines the domain terms used by QuakeStrike PH.

## Ingestion workflow

**Bulletin**:
A PHIVOLCS source publication that reports an earthquake observation and its
published details.

**Event**:
A QuakeStrike PH earthquake record created from one or more related PHIVOLCS
bulletins.

**Ingestion run**:
One attempt to retrieve and reconcile the PHIVOLCS source data. A run has a
status and a summary of what it found and changed.

**Revision**:
A later PHIVOLCS bulletin that changes the published details for an existing
event while preserving that event's identity and history.

**Stable event identity**:
The QuakeStrike `earthquake_events.event_id` UUID that remains unchanged across
accepted source corrections. It is an internal identity, not a PHIVOLCS
bulletin or group identifier.

**Source bulletin ID**:
The complete PHIVOLCS bulletin filename stem, such as
`2026_0831_1609_B2`. It identifies one source publication and is stored on an
event revision.

**Source event group ID**:
The PHIVOLCS filename portion before `_B`, such as `2026_0831_1609`. It can
identify a possible revision family but is not unique and is never sufficient
by itself to merge events.

**Source-less candidate**:
An incoming row missing one or both PHIVOLCS identifiers. It may be considered
for an unambiguous existing-event fallback when a group ID is available. A row
with neither identifier is rejected and counted; it cannot create a new event
identity.

**Ingestion scheduler**:
The single Celery Beat process that creates scheduled ingestion work every five
minutes. It does not perform PHIVOLCS retrieval or reconciliation itself.

**Dispatch**:
The durable step that claims a pending ingestion or prediction dispatch,
publishes its identifier-only command to the matching Redis queue, and records
the submission state for recovery and retry.

**Queue command**:
A versioned message containing stable database identifiers for one logical job.
It identifies the dispatch, one durable target (`run_id` for ingestion or
`job_id` for prediction), and the correlation context; it does not carry
scraped HTML, a full event payload, or a CSV path.

**Processing lease**:
A time-limited PostgreSQL claim held by a worker while it processes a run. The
Data Ingestor renews its lease by heartbeat, and an expired lease may be
reclaimed safely because processing is idempotent.

**Ingestion queue**:
The Redis/Celery queue consumed by the Data Ingestor. Prediction commands use a
separate prediction queue. The shared Dispatcher publishes prediction commands
after the Data Ingestor commits their durable dispatch rows.

**At-least-once delivery**:
A queue may deliver the same logical command more than once. Consumers and
durable work creation must therefore make source matching, persistence, and
prediction-work publication safe to repeat.

**Feature engineering**:
The deterministic application step that turns validated earthquake history and
one event revision into the versioned model input features. It must use only
data available before the anchor event and must not include labels, future
outcomes, or retrospective family metadata.

**Prediction input snapshot**:
The canonical JSON representation of the features sent to a model release. The
snapshot is stored with its SHA-256 hash so the Prediction Worker can reproduce
exactly what the ingestor requested.

**Historical prediction recovery**:
An explicit operator action that creates audited prediction work for a current
live revision previously skipped for missing source-coverage evidence. It keeps
the original revision and skip decision and never creates an automatic alert.

**Prediction provenance gate**:
The minimum evidence required before an ingested revision can create
prediction work: a valid source URL, at least one PHIVOLCS source identifier,
validated event data, and a complete versioned feature snapshot.

**Event transaction**:
The PostgreSQL transaction that preserves an event identity, appends its
revision when needed, and creates its prediction job and dispatch row
atomically. Redis publication occurs after commit.

**Project runtime release**:
The explicitly configured, immutable `SEIS 1.0.1` release used for project
implementation and demonstration. Startup verifies its normalized manifest and
artifact hashes before processing prediction work. Model files remain outside
Git and mount read-only.

**History bootstrap**:
A finite import or backfill that seeds PostgreSQL with enough prior validated
earthquake history for live feature engineering. It is not a second runtime
event store and does not require CSV to remain in the workflow afterward.

**Bootstrap source snapshot**:
A preserved raw or enriched PHIVOLCS artifact used as input to the one-time
history bootstrap. It must retain source identifiers, source URLs, retrieval
metadata, row counts, and validation results; the cleaned catalog alone is not
authoritative bootstrap input.

**Detail-page enrichment**:
A bounded concurrent request to a new or changed visible PHIVOLCS bulletin URL
to obtain origin and optional seconds precision. Unchanged catalog rows reuse
accepted details from their stored revisions. Detail seconds are used only when
the date, hour, and minute agree with the catalog row; otherwise the catalog
minute timestamp is retained.

**Log retention cycle**:
Docker-managed rotation of structured service output. The initial policy keeps
five approximately 20 MiB files per container using the `local` logging driver;
the application does not manage log files.

**Enrichment revision**:
A new event revision created when a later detail-page check changes persisted
source data such as origin, timestamp precision, or canonical URL. The prior
revision is not edited in place.

**Bootstrap readiness**:
The state reached only after migrations, model-release verification, source
snapshot checks, identifier checks, and seven-day history coverage succeed.
The recurring Beat schedule remains disabled before this state.

## Forecasts and alerts

**Automatic alert**:
A system-created email/SMS batch linked to one current live forecast. It does
not require human review or approval. Each enabled channel has separate
recipient and delivery evidence.
_Avoid_: Operator alert, reviewed alert

**Alert trigger magnitude**:
The minimum observed anchor magnitude at which one user is eligible for an
automatic alert.
_Avoid_: Global alert threshold

**SMS enrollment**:
The state in which a user has a verified current mobile number and has explicitly
enabled SMS alerts. Current ordinary sender support is an additional delivery
eligibility check.
_Avoid_: PHIVOLCS consent, review approval

**Bulletin account**:
A Clerk account signed in through email/password or Google for personal alert
settings. Public earthquake information remains available without an account.
The account's stable Clerk user ID, not its email or phone, identifies its
QuakeStrike profile.

**Alert receive options**:
Independent email and SMS choices saved by the user. A verified destination
alone never enables a channel; both may be off.

**Verified alert email**:
The current Clerk-verified email mirrored by the Backend as an eligible email
alert destination. A pending email change pauses email alerts until verified.

**Verified alert phone**:
The one current mobile number linked to a Bulletin account after an SMS
provider confirms a code entered for that account's pending verification.
Verification alone does not enable alerts; changing the number pauses SMS until
the user opts in again.

**Nearby-only alert**:
An optional per-user alert filter that compares an observed earthquake epicenter
with one saved alert location and the user's maximum distance in kilometres.
It applies to both enabled channels. It does not use the forecast activity
radius or track the user's device.

**Alert location edit**:
An unfinished choice of one alert location and nearby distance. It remains
separate from saved alert settings until the user submits it.

## Operations

**Test operator**:
A person admitted through the private Tailscale network to control an alert
test. This person is separate from a Console operator or Bulletin account.

**Tester**:
An existing Bulletin account explicitly selected to receive alerts in a test.
The account's ordinary alert settings continue to govern eligibility.

**Test session**:
One shared, temporary period for alert testing with a fixed four-hour deadline.
Ending or expiry closes access before cleanup finishes.

**Test scenario**:
One frozen synthetic earthquake, forecast, and set of replay observations
belonging to a test session.

**Operator workspace**:
One independent working context for a test operator within the shared test
session. Changes in one workspace do not replace another workspace's draft.

**Workspace draft**:
Unfinished earthquake, forecast, replay inputs, and tester selection in one
operator workspace. A draft remains editable and creates no alert.

**Console operator**:
A person admitted by the Operations Console's Cloudflare Access policy through
a named Google identity and MFA. This identity is separate from a Bulletin
account and is not a role on the `users` table.

**Console access event**:
An append-only record of a verified operator opening a Console page or detail,
or revealing a sensitive user field with a stated reason. It does not contain
the revealed value or a raw search term.
