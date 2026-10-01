# Scoped historical prediction recovery

After [ADR 0040](../adr/0040-scoped-rollover-recovery-and-worker-checkout.md),
select a succeeded live run and its original coverage skip reason explicitly:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile init run --rm release-init quakestrike recover-historical-predictions --source-run-id <run-uuid> --skip-reason history_ends_before_anchor
```

Inspect the dry run, then repeat with `--apply --batch-size 50`. Keep live workers
running, wait for each batch to drain, and rerun the dry run to verify reuse.
Only `history_coverage_unavailable` and `history_ends_before_anchor` are supported.
Select each affected run separately; do not recover superseded revisions or
fabricate coverage. Recovery preserves the original skip and never creates
automatic alerts. Omitting the selectors retains the September 24 defaults below.

## September 24 default recovery

Run this one-shot action only after the reviewed release containing [ADR 0032](../adr/0032-audited-historical-live-prediction-recovery.md) is deployed. It is scoped in code to ingestion run `adc80d19-d105-4ef7-b427-6bc52f133b4d`. Keep Beat and the live workers running; the command uses ordinary event locks and durable dispatches. The release has no migration.

From `/srv/quakestrikeph`, use the same Compose files and `.env` as the runtime:

```bash
compose=(docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml)
"${compose[@]}" --profile init run --rm release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
"${compose[@]}" --profile init run --rm release-init quakestrike recover-historical-predictions
"${compose[@]}" --profile init run --rm release-init quakestrike recover-historical-predictions --apply
"${compose[@]}" --profile init run --rm release-init quakestrike recover-historical-predictions
```

Inspect the dry run before applying. Expect `total=450`, `superseded=4`, and up to 446 eligible revisions. Investigate any coverage skip or conflict. Apply creates at most 50 jobs per invocation and reports the remaining `deferred` count. Wait for those jobs to finish and check that scheduled runs remain healthy before applying the next batch. Repeat until `deferred=0`, then run once more to confirm 446 `reused` and zero new jobs. An interrupted batch can be rerun safely. Forecasts are processed by the normal Prediction Worker. Check that every recovered job has one dispatch and one recovery audit, succeeded jobs have forecasts, and no recovered forecast has an alert job. The original revision skip reasons must still number 450.
