# Accept verified latest catalog coverage during month rollover

**Status**: accepted

Amends the month restrictions in [ADR 0031](0031-live-catalog-coverage-evidence.md).
On October 1, 2026, the PHIVOLCS latest page still declared September while its
complete event table contained September and October observations. Requiring
the heading and every event to match the retrieval month prevented new live
prediction work despite successful ingestion.

A complete latest-page response may declare the retrieval month or its
immediately preceding calendar month, including December-to-January rollover.
Every six-cell event row must normalize, the first day of the declared month
must be represented, and no accepted event may precede that day or follow the
retrieval time. Missing or ambiguous headings, older headings, malformed event
rows, truncated responses, and future events still provide no coverage claim.
The validated interval starts at midnight on the first day of the declared
month and ends at retrieval. This permits one continuous interval across the
month boundary without inventing coverage across an unverified gap.

Reconciliation reads overlapping coverage from prior succeeded runs for the
visible anchors' seven-day history windows even if the current response cannot
claim coverage. Failed and incomplete runs remain ineligible. Previously
verified evidence may support an older corrected anchor, but cannot be extended
to a new anchor without source evidence. Only touching or overlapping intervals
merge; a real gap remains a prediction skip.

The existing bounded HTTPS retrieval, exact source hash and run binding,
chronological processing, immutable feature snapshots, seven-day history gate,
and atomic event/job/dispatch transaction remain in force. No schema, role,
queue, model release, or runtime configuration change is required.

Previously skipped immutable revisions are not retried by normal polling.
Audited recovery remains a separate operator action; the existing September 24
recovery command is not broadened by this decision.
