# Keep PHIVOLCS identifiers on revisions

**Status**: accepted

`earthquake_events.event_id` is the stable QuakeStrike PH identity for one
earthquake event. The proposed `earthquake_events.source_event_key` column is
removed because it would duplicate that identity without adding a reliable
PHIVOLCS key. A PHIVOLCS bulletin identifier changes when a source bulletin is
revised, and a PHIVOLCS event group can contain more than one legitimate event.

`earthquake_event_revisions` stores the source identifiers for each validated
publication: the complete `source_bulletin_id` filename stem and the
non-unique `source_event_group_id` prefix before `_B`. Each identifier may be
null for an exceptional source response, but they may not both be null. The
bulletin identifier is unique for the PHIVOLCS source when present; the group
identifier is indexed but not unique. A persisted revision still requires its
source URL and normalized event fields.

Reconciliation searches saved revisions by exact `source_bulletin_id` first.
When a new bulletin ID may revise an existing event, the ingestor considers
the group only when the candidate is unambiguous and the declared revision
checks pass. If the bulletin ID is absent but the group ID is present, the
same guarded fallback may attach the row to exactly one existing event. If
both identifiers are absent, the row is processed for validation but is
rejected and counted rather than persisted. Timestamp alone, group alone, or
matching an identical set of observed values is not an identity key. An
accepted correction keeps the same `event_id` and appends a revision; an
ambiguous match is rejected for review.

The existing `superseded_by_event_id` relationship remains reserved for a
confirmed duplicate identity, not an ordinary PHIVOLCS correction. If support
for multiple source providers is needed later, introduce an explicit
provider-identifier mapping table rather than reintroducing a second opaque
identity column on `earthquake_events`.
