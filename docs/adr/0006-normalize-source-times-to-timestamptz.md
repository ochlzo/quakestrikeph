# Normalize PHIVOLCS source times to timestamptz

**Status**: accepted

PHIVOLCS bulletin times will be interpreted as local time in the
`Asia/Manila` timezone and stored as PostgreSQL `timestamptz` values. The
ingestor will also preserve whether the source reported minute or second
precision. This keeps comparisons and downstream processing unambiguous while
retaining the precision supplied by the source.
