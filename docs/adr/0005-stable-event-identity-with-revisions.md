# Preserve event identity across bulletin revisions

**Status**: accepted

The ingestor will match an incoming PHIVOLCS bulletin by the exact bulletin
identifier saved on `earthquake_event_revisions` first. It may use the source
group identifier only when the candidate match is unambiguous and passes the
declared revision checks. A confirmed match keeps the existing
`earthquake_events.event_id` and appends an event revision; it does not create
a new event for every revised bulletin. Timestamp alone, group alone, or an
identical observation tuple is not an event identity key. The proposed
`earthquake_events.source_event_key` is removed as redundant.
