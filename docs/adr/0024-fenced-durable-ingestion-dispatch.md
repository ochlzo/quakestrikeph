# Fence durable ingestion dispatch by processing state

**Status**: accepted

The scheduler Beat owns one local five-minute tick. The tick creates or reuses
one active ingestion run and its dispatch in the same PostgreSQL transaction.
The scheduled entry is a local Beat callback label, not a broker task; Beat
never publishes an ingestion command.

The dispatcher may claim an ingestion dispatch only when its submission state
is due and its target run is also eligible for processing:

- `pending` runs with no processing retry schedule or lease;
- `retry_wait` runs whose processing retry time has arrived and have no lease;
- `running` runs only when their processing lease has expired.

Terminal runs and runs with a future processing retry time or a live processing
lease are fenced out; due submission rows targeting terminal runs are stopped
without publication. Claiming locks both the dispatch and run rows with
`FOR UPDATE SKIP LOCKED`, records a new submission token and lease, and
commits before publication. Redis acceptance is recorded only by a later
token-fenced update. A stale token cannot acknowledge or retry a newer claim.

Submission failures use the timestamp observed when each publication fails,
not the beginning of the scan. The default retry sequence is 30 seconds, two
minutes, and ten minutes. The existing dispatch and run identities are
preserved; exhaustion stops the dispatch and fails the run only when the run
is not actively held by an unexpired processing lease. An expired submission
claim may be recovered only when the target run is eligible under the same
rules.

Scheduler and dispatcher diagnostics use the worker's structured JSON logging
adapter. Logs contain stable event codes and available durable identifiers,
plus a sanitized exception type when needed; exception messages and traces do
not cross the logging boundary.

The contract is proven with unit tests for timing, waiting, and logging; a
PostgreSQL integration suite for row locks, leases, run-state fencing, retry
transitions, and stale tokens; and an integration test that drives the real
Beat callback through PostgreSQL and publishes the resulting versioned
identifier-only command to the real Redis ingestion queue.
