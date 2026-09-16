# Normalize input values and protect source freshness

**Status**: accepted

The parser converts numeric source fields with `Decimal`, validates their
allowed ranges, and quantizes them to the database scales. Invalid or
out-of-range values are rejected; values are never silently clamped. Source
bulletin and group identifiers are stored in a canonical uppercase form for
matching. The source URL is preserved as a canonical URL and is not invented
when absent.

Only transient HTTP failures are retried: timeouts, connection resets, HTTP
`429`, and `5xx` responses. Client errors, TLS verification failures,
oversized responses, and parser or identity failures stop the logical run.
Counters describe distinct normalized inputs. Identical duplicate rows count
once, and redelivery does not increment counters again.

PostgreSQL owns overlap protection through the active-run state and database
lock. A poll updates `last_seen_run_id` only for rows visible in that response;
absence from the current page does not delete or supersede an event. Archive
traversal and explicit backfill are separate operations.

Services emit structured logs to stdout/stderr with run, dispatch, worker, and
correlation identifiers. They do not write application log files or store raw
HTML and secrets in PostgreSQL. Docker is responsible for the configured log
rotation and retention cycle. The initial Compose deployment uses Docker's
`local` logging driver with approximately `20 MiB` per file and five retained
files per container, for an approximate `100 MiB` ceiling per container.

## Amendment: failure scope clarification

The statement that parser or identity failures stop the logical run applies to
catalog-level structural/parser failures and fatal identity conflicts, such as
a conflicting duplicate bulletin identifier. It does not override the earlier
row-level rules in ADRs 0014–0016: an invalid, incomplete, ambiguous, or
unmatched individual row is rejected and counted while other valid rows
continue. Individual detail-page enrichment failures follow ADR 0020 and do
not by themselves fail the run.
