# Map each bulletin ID to one stable event

**Status**: accepted

A PHIVOLCS bulletin can be enriched later without a new bulletin identifier.
The same canonical `source_bulletin_id` may therefore occur in more than one
immutable `earthquake_event_revisions` row. Every occurrence must belong to
the same `earthquake_events.event_id`.

`earthquake_bulletin_event_identities` stores one canonical bulletin ID and
its stable event ID. Its primary key makes exact matching unambiguous and
enforces the invariant across concurrent transactions. The global partial
unique index on revision `source_bulletin_id` is replaced with a non-unique
lookup index. A transaction inserts or verifies the bulletin map before it
accepts a revision. An attempt to use a mapped bulletin for a different event
fails and rolls back.

This does not weaken the current-page rule. Conflicting duplicate rows with
the same bulletin ID in one catalog response still fail that logical run.
