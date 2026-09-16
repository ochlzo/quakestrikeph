# Handle incomplete source identity conservatively

**Status**: accepted

Rows missing one PHIVOLCS identifier are not discarded before reconciliation.
If a bulletin ID is present, it is used for exact revision lookup. If the
bulletin ID is absent but a group ID is present, the ingestor may use the
approved group-and-field fallback only when exactly one existing event passes
the checks. The row keeps that existing `event_id`; it never creates a new
event solely because its source identity is incomplete.

Rows missing both the bulletin ID and group ID are still validated and counted
in the ingestion run, but are rejected from PostgreSQL because there is no
safe identity path. Ambiguous and unmatched fallback candidates are handled
the same way. A fallback revision may create prediction work only when it has
a valid source URL and at least one source identifier. Missing source URLs are
rejected; the ingestor never fabricates them.
