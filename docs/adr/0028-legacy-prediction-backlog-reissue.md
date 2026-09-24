# Reissue legacy prediction work under the corrected release

**Status**: accepted

The Prediction Worker may infer a job only with the exact model release named
by that job. Matching input and output schema versions alone do not establish
release identity. A job for another release must fail before inference; its
forecast must never be attributed to the worker's configured bundle.

The original `SEIS 1.0` output contract cannot be stored in the corrected v2
forecast schema. The old release, the job's release and input snapshot, and
its attempt history stay immutable. An explicit operator command, `quakestrike
reissue-legacy-predictions`, creates a new `SEIS 1.0.1` job and prediction
dispatch for each eligible old job. The new job uses the old job's preserved
canonical input snapshot, with fresh job and dispatch IDs. It keeps the same
event revision and correlation context. The command validates the v2 release
and snapshot before writing.

Eligible old jobs are `pending` or `retry_wait`, plus `failed` jobs whose
recorded error is `unsupported_schema` or `release_mismatch`. A `running` job
or an active attempt blocks reissue. Successful, cancelled, and unrelated
failed jobs are not reissued. In a PostgreSQL transaction, the command
creates or validates the replacement job and dispatch, cancels the old job
with reason code `reissued_for_release`, stops its dispatch, and writes a
required `prediction_backlog_reissued` system audit with actor service
`operator-cli`. The audit links both job and dispatch identities. Reissue
does not create an alert. Forecast completion later applies the normal alert
rules to the new job's result.

Rerunning the command is safe. It may reuse an existing v2 job only after it
checks the event revision, canonical snapshot and hash, correlation context,
and associated dispatch. A conflicting row fails closed. The original job and
attempt records remain available as evidence; the reissue reason records why
the old job will not process under the corrected release. This controlled
release transition is the exception to ordinary retry recovery, which keeps
the same job and dispatch IDs.

Operators stop Beat, Data Ingestor, Dispatcher, and Prediction Worker, allow
in-flight work to settle, then run the command in `release-init` after
migrations and `SEIS 1.0.1` registration and verification. They inspect its
result before starting Dispatcher or Prediction Worker. Startup does not run
this migration implicitly. See the [operator steps](../operations/local-runtime.md#5-initialize-the-database-and-model-release).
