# Recover bootstrap readiness evidence after checkpoint retention

**Status**: accepted

Amends [ADR 0022](0022-idempotent-revisions-and-bootstrap-gates.md) alongside the
retention policy in [ADR 0034](0034-bound-successful-ingestion-checkpoints.md).
A succeeded history bootstrap retains its run summary, source binding, and event
revisions after temporary checkpoints expire. Startup accepts either all
expected checkpoints or zero checkpoints when the run finished more than 30
days ago. Partial checkpoints and younger missing checkpoints fail readiness.
Age establishes retention eligibility; it does not prove what deleted the rows.
Snapshot validation, the bound source and enrichment hashes, run counts, event
revisions, persisted usable history, migrations, model verification, PostgreSQL,
and Redis remain required.

When the run sidecar is unavailable, an explicit operator command previews the
evidence and can reconstruct a labelled sidecar without changing the run,
events, or checkpoints. It selects exactly one matching succeeded run or
requires an explicit run ID. It never replaces existing evidence. Before
publication it records the verified recovery decision in `audit_logs`, bound
to the run, snapshot, destination, and reconstructed file hash. An interrupted
publication can be retried only when its evidence still matches the audit.
The audit records successful evidence verification, not proof that the sidecar
was published. Startup verifies the audit binding for reconstructed sidecars.
Operators verify the resulting file and run all startup checks
before enabling processing or public traffic.
