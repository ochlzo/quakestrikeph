# Use typed queues and stable database-ID commands

**Status**: accepted

The first runtime uses separate Redis/Celery queues for ingestion and
prediction work. It does not create a queue per event. The Scheduler module
contains one Beat process and a long-lived dispatcher. Beat creates durable
`ingestion_runs` and `job_dispatches` rows; the dispatcher scans for pending
dispatches approximately every five seconds, claims up to ten at a time, and
uses a sixty-second queue-submission lease.

Queue commands contain stable database identifiers only: the message version,
`dispatch_id`, `run_id`, and `correlation_id`. They do not contain scraped HTML,
full event rows, or paths to CSV files. The dispatcher commits its claim before
publishing to Redis and records the accepted submission afterward. Duplicate
commands are expected and must be safe to claim and process again.

The initial Data Ingestor runs with one worker concurrency and a fifteen-minute
database processing lease that is renewed by heartbeat. Celery uses late
acknowledgement and rejects work when a worker is lost. PostgreSQL remains the
source of job state; Redis is the broker, not the system of record.

Automatic retries are bounded. A retryable failure receives three retries with
approximately thirty-second, two-minute, and ten-minute backoff, then the
logical run becomes `failed` and its dispatch becomes `stopped`, following the
schema's separate processing and submission states. Non-retryable validation and source
identity failures do not consume retries. PHIVOLCS requests use connection and
read timeouts, TLS certificate verification, a response-size limit, an
identifying user agent, and bounded backoff. A missing or structurally invalid
events table is a failed poll, not an empty successful result.

## Amendment: typed command identifiers

Each versioned command carries `message_version`, `dispatch_id`, and
`correlation_id`. An ingestion command also carries `run_id`. A prediction
command carries `job_id` instead of `run_id`. Future alert commands carry their
own durable alert-job identifier. Commands do not copy payload data that the
consumer can load from PostgreSQL. The schemas live under
`packages/contracts/queue/` and compatibility tests protect messages that may
still be held by Redis during deployment.

## Amendment: shared dispatch ownership

The long-lived Dispatcher owns queue publication for both ingestion and
prediction `job_dispatches` rows. The Data Ingestor creates an eligible
prediction job and its dispatch row inside the event transaction, but it does
not publish a prediction command. After the transaction commits, the shared
Dispatcher claims the existing prediction dispatch with the same token,
submission lease, retry policy, and durable identity used for ingestion, then
routes it only to the prediction queue. This keeps one dispatch state machine
without replacing or duplicating prediction identities.
