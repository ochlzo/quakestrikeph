# Reuse stored details for unchanged live catalog rows

**Status**: accepted

The Data Ingestor fetches and parses the complete current PHIVOLCS catalog on
every five-minute scheduled run. For each visible bulletin, it compares the
normalized catalog fields with the latest durable event revision bearing that
bulletin ID. When they match, it reuses the revision's accepted detail timestamp
and origin. A new bulletin, changed catalog field, missing prior revision, or
ambiguous shared detail URL causes a fresh detail request. No separate detail
cache is stored in Redis or PostgreSQL.

When the stored revision lacks either seconds precision or origin, the ingestor
fetches the detail page again. This keeps failed or incomplete detail results
eligible for retry, even if the catalog row is unchanged. For scheduled runs,
a complete unchanged row is counted without a per-event transaction or input
checkpoint. Its event's `last_seen_run_id` is updated in one fenced batch.
Manual and backfill rows continue through normal reconciliation.

This changes [ADR 0020](0020-detail-page-enrichment.md)'s rule to check every
visible detail URL on every run. Its rules for accepting detail seconds,
normalizing origin, reporting failures, and preserving source revisions still
apply. A correction made only on an old detail page while its catalog row stays
unchanged is not discovered. This is an accepted freshness tradeoff.

Run identity, full-catalog validation, catalog coverage evidence, event matching,
revision creation, and prediction gating remain. Rows with missing bulletin IDs,
incomplete details, or ambiguous shared URLs use normal processing. A retry
compares against revisions from before its logical run, and existing checkpoints
still govern rows already processed by that run. [ADR 0034](0034-bound-successful-ingestion-checkpoints.md)
defines checkpoint retention.

The production timing sample before this change showed approximately 1,556
detail URLs and 157–159 seconds of detail enrichment per scheduled run, while
catalog fetch and parsing took roughly 2–5 seconds. If the database comparison
cannot establish a match, the ingestor fetches the detail page.
