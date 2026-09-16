# Reproduce the training feature contract at ingestion time

**Status**: accepted

The Data Ingestor stores every valid PHIVOLCS event, but only a newly inserted
or changed event revision with magnitude at least `1.0` is a prediction
anchor. The old backend's `4.5` mainshock gate is not used. A complete
seven-day prior history is required before an anchor can create prediction
work.

The v1 feature builder uses the ten declared training feature names and rules.
Only recorded M1+ observations contribute to catalog and local counts. Time
windows include their lower boundary and exclude the anchor timestamp. Events
with uncertain same-minute ordering are excluded. Local counts use inclusive
Haversine distances with Earth radius `6371.0088 km` and the declared `50 km`
and `100 km` limits.

If history coverage is insufficient, the event is retained and the reason is
recorded, but no prediction job is created. The builder never shortens a
window, fills missing history with zeros, uses future outcomes, or uses
retrospective family metadata.

Each prediction job stores one immutable canonical JSON feature snapshot in
`input_snapshot_json` and its SHA-256 in `input_snapshot_hash`. Canonical
serialization includes the input-schema identity and uses stable key ordering
and normalized values. The snapshot is created before the prediction job and
dispatch row are committed together.
