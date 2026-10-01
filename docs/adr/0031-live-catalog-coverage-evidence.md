# Bind live prediction coverage to a complete PHIVOLCS catalog response

**Status**: accepted

The heading and event-month restrictions, and the use of prior successful
coverage when the current page cannot claim coverage, are amended by
[ADR 0039](0039-latest-catalog-month-rollover.md).

The PHIVOLCS current page presents a named current-month earthquake table. A
live response may claim coverage from the first day of that month through its
retrieval time only when the entire bounded HTTPS response was read, the page
declares the retrieval month, every six-cell event row normalizes, all accepted
event times belong to that month and precede retrieval, and at least one event
on the first day is present. A failed check yields no coverage claim; ingestion
still retains valid rows and their diagnostics. This is source-page evidence,
not an inference from the oldest row already stored in PostgreSQL.

The Data Ingestor binds the exact catalog SHA-256, source URL, retrieval time,
row count, and claimed interval to its leased run before reconciling events.
Redis still carries IDs only. A retry may use the same catalog bytes and its
original bound interval; a different response ends that logical run so a later
scheduled run can use a new source snapshot. A failed or incomplete run's
interval cannot extend coverage for another run.

Rows are reconciled in increasing event time so the database contains prior
observations before an anchor's features are built. For one run, the validated
current response can combine with the verified bootstrap interval and intervals
from earlier successful live runs. Only touching or overlapping intervals are
merged. A gap, missing month heading, malformed event row, source truncation,
or unavailable prior-month archive leaves affected anchors without prediction
work as required by [ADR 0021](0021-live-feature-contract.md). Forecasts never
receive zero-filled history.

Existing revisions whose immutable skip decision was recorded before coverage
became available require separate audited recovery. The ingestor does not edit
their revision rows or fabricate a source correction to create prediction work.
