# Reuse recent successful live bulletin details

**Status**: accepted

The Data Ingestor still fetches and parses the complete current PHIVOLCS catalog
on every five-minute scheduled run. It may reuse a successfully parsed detail
result for an unchanged catalog row from a short-lived Redis cache. A cache key
binds the normalized catalog fields of every row using the detail URL. A new or
changed catalog row therefore causes an immediate detail request and invalidates
the earlier cached result, even if the new request fails.

Successful detail results expire after 23 hours, so a continuously visible,
unchanged bulletin receives a fresh detail check within roughly 24 hours at
the normal polling cadence. Failed, malformed, incomplete, or catalog-time-
mismatched detail results are never cached and are retried on the next poll.
A missing, invalid, or unavailable cache entry causes an ordinary detail fetch.
The cache contains
only parsed timestamp and origin values, not source HTML, and is never
authoritative event history.

This changes [ADR 0020](0020-detail-page-enrichment.md)'s rule to check every
visible detail URL on every run. Its rules for accepting detail seconds,
normalizing origin, reporting failures, and preserving source revisions still
apply. A correction made only on an old detail page can be observed up to one
day later when scheduled polls succeed.

Run identity, catalog coverage evidence, per-input checkpoints, event matching,
revision creation, and prediction gating are unchanged. This reduces repeated
external requests and run time. [ADR 0034](0034-bound-successful-ingestion-checkpoints.md)
separately bounds accumulated successful-run checkpoints.

The production timing sample before this change showed approximately 1,556
detail URLs and 157–159 seconds of detail enrichment per scheduled run, while
catalog fetch and parsing took roughly 2–5 seconds. The cache is a best-effort
optimization; cache errors fall back to the existing full-detail path.
