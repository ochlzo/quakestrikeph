# Enrich every visible bulletin through its detail page

**Status**: accepted

Each unique bulletin URL visible in a catalog response is checked through a
reused HTTP session. Live enrichment uses at most four concurrent detail
requests, with a separate reused session per worker and a global minimum
`0.1`-second gap between request starts. The concurrency limit is configurable
from one through four. Catalog fetching and event reconciliation still belong
to one durable ingestion run. The parser reuses the latest scraper's
encoding, URL-repair, TLS, retry, and detail-page extraction behavior.

The detail page supplies `Origin` and may supply seconds. The ingestor trusts
the seconds-bearing timestamp only when its date, hour, and minute agree with
the catalog row. If any of those components differ, the catalog timestamp is
retained at minute precision and the discrepancy is recorded. Seconds are
never guessed.

If a detail page cannot be downloaded or parsed, the catalog event is retained
with its minute timestamp and a nullable origin, with a structured enrichment
diagnostic. A later poll may retry the detail request. Known origin values are
normalized to `TECTONIC`, `VOLCANIC`, or `TECTONIC-VOLCANIC`; unknown or blank
values become null with a diagnostic. Missing origin does not block prediction
work because origin is not a model input feature.

Known malformed PHIVOLCS URL patterns are repaired before the detail request.
Links that remain unrecognizable are rejected without fabricating a URL.

## Amendment: controlling enrichment rule

This ADR is the controlling rule for individual detail-page enrichment and
supersedes any broader earlier wording that would reject a valid catalog row
solely because its detail page could not be downloaded or parsed.
