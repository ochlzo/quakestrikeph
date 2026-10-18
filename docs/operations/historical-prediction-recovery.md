# Recover historical predictions

Use this procedure for current live revisions previously skipped because source coverage was unavailable.
Run Bash commands from `/srv/quakestrikeph` on the VPS with the reviewed recovery release deployed.
Keep Beat and live workers running; recovery uses normal event locks and durable dispatches.
Recovery preserves original skip decisions and creates no automatic alerts.

## Recover one selected run

1. Select a succeeded live run and its original coverage skip reason.
2. Replace `<run-uuid>` and run the dry run.

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile init run --rm release-init quakestrike recover-historical-predictions --source-run-id <run-uuid> --skip-reason history_ends_before_anchor
```

3. Inspect eligible, skipped, and conflicting records before applying.
4. Repeat the command with `--apply --batch-size 50`.
5. Wait for that batch to drain.
6. Rerun the dry run to check remaining work and reused jobs.
Only `history_coverage_unavailable` and `history_ends_before_anchor` are supported.
Select each affected run separately; do not recover superseded revisions or
fabricate coverage. Recovery preserves the original skip and never creates
automatic alerts. Omitting the selectors retains the September 24 defaults below.

## September 24 default recovery

The no-selector command targets only ingestion run `adc80d19-d105-4ef7-b427-6bc52f133b4d` from 24 September 2026.
Use explicit selectors for other runs. The original recovery release required no migration.

From `/srv/quakestrikeph`, use the same Compose files and `.env` as the runtime:

```bash
compose=(docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml)
"${compose[@]}" --profile init run --rm release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
"${compose[@]}" --profile init run --rm release-init quakestrike recover-historical-predictions
"${compose[@]}" --profile init run --rm release-init quakestrike recover-historical-predictions --apply
"${compose[@]}" --profile init run --rm release-init quakestrike recover-historical-predictions
```

### Expected results

| Check | Expected result |
| --- | --- |
| Initial dry run | `total=450`, `superseded=4`, up to 446 eligible revisions. |
| Each apply | At most 50 jobs; remaining work appears as `deferred`. |
| Final dry run | `deferred=0`, 446 `reused`, zero new jobs. |
| Each recovered job | One dispatch and one recovery audit. |
| Succeeded job | A forecast exists. |
| Recovered forecast | No alert job exists. |
| Original skip decisions | All 450 remain recorded. |

Investigate coverage skips or conflicts before applying. Confirm scheduled runs remain healthy between batches.
An interrupted batch can run again safely. Normal Prediction Workers process the recovered jobs.
