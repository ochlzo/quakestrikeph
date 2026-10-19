# QuakeStrike PH glossary

This glossary defines project terms. Use the linked references for implementation rules and operating procedures.

## Earthquake data

**Bulletin**:
A PHIVOLCS source publication that reports an earthquake observation and its details.
This differs from the QuakeStrike PH Bulletin application.

**Event**:
A QuakeStrike PH earthquake record created from one or more related PHIVOLCS bulletins.

**Revision**:
A preserved version of an event's accepted details, including its initial version, source corrections, or enrichment changes.
A new revision preserves the event's identity and earlier versions.

**Stable event identity**:
The internal QuakeStrike PH identifier that remains unchanged across accepted corrections.
It differs from a PHIVOLCS bulletin or group identifier.

**Source bulletin ID**:
The complete PHIVOLCS bulletin filename stem, such as `2026_0831_1609_B2`, identifying one source publication.

**Source event group ID**:
The PHIVOLCS filename portion before `_B`, such as `2026_0831_1609`, indicating a possible revision family.
It is not unique and cannot establish event identity alone.

**Source-less candidate**:
An incoming observation missing one or both PHIVOLCS identifiers.
A group ID may support an unambiguous existing-event match; an observation with neither identifier is rejected and cannot create an event.

**Detail-page enrichment**:
Additional source details obtained from a PHIVOLCS bulletin page, such as origin information or more precise event time.

**Enrichment revision**:
A new revision that preserves changed details found through detail-page enrichment without editing the earlier revision.

## Forecasts

**Anchor event**:
The observed earthquake that provides the reference time and event details for a forecast.

**Forecast**:
A model estimate of possible further earthquake activity during the forecast window after an anchor event.
It does not predict an exact earthquake.

**Forecast window**:
The 24 elapsed hours starting at the anchor event's observed time.
Viewing, replaying, or receiving a forecast does not restart this window.

**Model release**:
An immutable, versioned set of model artifacts and input/output definitions used to generate reproducible forecasts.

**Project runtime release**:
The model release explicitly selected for project processing and demonstration.

**Feature engineering**:
The preparation of model inputs from an event revision and validated history available before the anchor event.
Future outcomes, labels, and retrospective family metadata are excluded.

**Prediction input snapshot**:
The preserved set of model inputs for one event revision and model release, allowing the requested prediction to be reproduced.

**Prediction provenance gate**:
The evidence requirement for prediction work: validated event data, a source URL, a PHIVOLCS identifier, and a complete versioned input snapshot.

**Historical prediction recovery**:
An audited operator action that creates prediction work for a current live revision previously skipped for missing source-coverage evidence.
It preserves the original revision and skip decision and never creates an automatic alert.

## Alerts and accounts

**Automatic alert**:
A system-created email/SMS batch linked to one current live forecast, without individual human review or approval.
Each enabled channel has separate recipient and delivery evidence.
_Avoid_: Operator alert, reviewed alert

**Alert trigger magnitude**:
A user's minimum observed anchor magnitude for automatic alert eligibility.
_Avoid_: Global alert threshold

**Bulletin account**:
An account for personal alert settings, identified by a stable identity rather than an email address or phone number.
Public earthquake information remains available without an account.

**Alert receive options**:
The user's independent email and SMS choices; both may be off.
A verified destination alone does not enable either channel.

**Verified alert email**:
The account's current verified email address, recognized by QuakeStrike PH as an alert destination.
Verification alone does not enable email alerts.

**Verified alert phone**:
The account's current mobile number confirmed through a verification code.
Verification alone does not enable SMS alerts; changing the number requires a new SMS opt-in.

**SMS enrollment**:
The combination of a verified current mobile number and the user's explicit SMS opt-in.
Sender coverage remains a separate condition for delivery eligibility.
_Avoid_: PHIVOLCS consent, review approval

**Nearby-only alert**:
An optional filter comparing the observed epicenter with one saved alert location and the user's maximum distance in kilometres, for both enabled channels.
The filter neither uses the forecast activity radius nor tracks the user's device.

**Alert location edit**:
An unfinished choice of alert location and nearby distance, separate from saved settings until submitted.

## Processing

**Ingestion run**:
One recorded attempt to retrieve and reconcile PHIVOLCS source data, with a status and results.

**Ingestion scheduler**:
The single scheduler that creates recurring ingestion work, separate from source retrieval and reconciliation.

**Dispatch**:
The recorded submission of an ingestion, prediction, or alert command to its matching queue, with a recoverable submission state.

**Queue command**:
A versioned message identifying one recorded ingestion run, prediction job, or alert job and its dispatch context.
It references recorded work rather than carrying the full source or event data.

**Processing lease**:
A temporary claim that gives one worker authority to process recorded work.

**Ingestion queue**:
The queue of ingestion commands consumed by the Data Ingestor, separate from prediction and alert queues.

**At-least-once delivery**:
The possibility that a queue delivers the same logical command more than once.
Repeated processing must preserve the same logical result without duplicate effects.

**Event transaction**:
One atomic change that preserves event identity and records any new revision, prediction job, and dispatch together.
Queue publication follows the committed change.

**History bootstrap**:
A finite import or backfill supplying validated earlier earthquake history for live feature engineering.

**Bootstrap source snapshot**:
Preserved raw or enriched PHIVOLCS data with source identifiers, URLs, retrieval metadata, row counts, and validation evidence.
A cleaned catalog alone does not qualify.

**Bootstrap readiness**:
The verified state in which required history, source evidence, and model setup support live processing.
Recurring ingestion remains disabled until readiness is established.

## Private testing

**Test operator**:
A person authorized through private access to control alert testing, distinct from a Console operator or selected tester.

**Tester**:
An existing Bulletin account explicitly selected for test alerts, with eligibility governed by its ordinary alert settings.

**Test session**:
One shared, temporary period for alert testing with a fixed four-hour deadline.
Ending or expiry closes access before cleanup finishes.

**Test scenario**:
A frozen synthetic earthquake, forecast, and set of replay observations belonging to a test session.

**Operator workspace**:
An independent working context within a shared test session, with a draft separate from other workspaces.

**Workspace draft**:
Editable, autosaved earthquake, forecast, replay inputs, and tester selection in one operator workspace.
A draft creates no alert.

**Prepared preview**:
A frozen, validated synthetic scenario available for public test-mode viewing before alert submission, without private tester selections.
Creating a preview creates no delivery job.

## Planned Operations Console

**Console operator**:
A planned Operations Console user admitted through a named identity with multifactor authentication, separate from a Bulletin account.

**Console access event**:
A planned audit record of Console access or a sensitive-field reveal with a stated reason.
The record excludes revealed values and raw search terms.

## References

- [Architecture](docs/system-design/ARCHITECTURE/ARCHITECTURE.md) and [database design](docs/system-design/ERD/DATABASE-DESIGN.md) define implementation contracts.
- [Accepted decisions](docs/adr/) record binding choices and amendments.
- [Operations guides](docs/operations/README.md) contain setup, scheduling, verification, and maintenance procedures.
