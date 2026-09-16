# Enrich the bootstrap lookback before import

**Status**: accepted

Before the history bootstrap, the scraper/enrichment workflow will produce a
raw or enriched PHIVOLCS snapshot covering at least August 25 through August
31 and the available September demonstration window. The existing September
raw/enriched snapshot can be reused after validation. The cleaned historical
CSV is not sufficient as the authoritative bootstrap input because it lacks
source bulletin identifiers and source URLs.

The snapshot is preserved with its retrieval metadata, row counts, source
identifiers, source URLs, and validation results. The bootstrap CLI consumes
the snapshot once and writes PostgreSQL; it does not establish a live CSV
dual-write path. Rows whose source enrichment fails remain in the preserved
source artifact but are rejected or counted by the bootstrap. The ingestor
must not fabricate identifiers or URLs.

## Amendment: detail-page failure handling

The later, more specific rule in ADR 0020 controls individual bulletin
detail-page failures. When the catalog row itself is valid, a failed or
unparseable detail request is preserved with the catalog minute timestamp,
nullable origin, and a structured diagnostic; it is not rejected solely for
that detail-page failure and may remain eligible for prediction work. The
bootstrap still rejects or counts rows that fail the accepted source contract,
such as an unrecognizable source URL, missing required source identity, or
invalid catalog fields. Preserved source snapshots retain the failed
enrichment evidence for later retry.
