# Recover bootstrap readiness evidence

Use this procedure when an existing database has a succeeded history bootstrap
but its run sidecar is missing. Keep processing and public ingress stopped.
Keep the original database and source snapshot. Do not import the snapshot again.
Create and verify a database backup first.

The command checks the selected model, migration state, exact source snapshot,
run identity and counters, event revisions, and usable history. It requires all
checkpoints, or zero checkpoints for a run completed more than 30 days ago.
Partial checkpoints fail. The age check does not prove why checkpoints vanished.
For raw source snapshots, provide the original bound enrichment cache using
`--enriched-snapshot`.

The command searches `source-snapshots` beside the target readiness file. If
more than one succeeded run has matching evidence, select one with `--run-id`.
Use `--snapshot` to specify a source snapshot explicitly. The command never
replaces a readiness file. Choose a new path if one already exists.

**VPS — Bash, from `/srv/quakestrikeph`:**

```bash
compose=(docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml)
"${compose[@]}" --profile init run --rm --no-deps release-init \
  quakestrike recover-bootstrap-readiness --check \
  --run-manifest /app/bootstrap-snapshots/recovered-readiness.json
```

Review the report. If it reports `ready_to_apply`, repeat with `--apply`:

```bash
"${compose[@]}" --profile init run --rm --no-deps release-init \
  quakestrike recover-bootstrap-readiness --apply \
  --run-manifest /app/bootstrap-snapshots/recovered-readiness.json
```

The command records verified evidence in `audit_logs` before publishing the
file. The audit action records verification; it does not prove publication.
If publication fails, inspect the error and rerun the command. A retry resumes
only if the recorded evidence still matches. An existing conflicting file or
audit record stops recovery.

Set `BOOTSTRAP_RUN_MANIFEST=/app/bootstrap-snapshots/recovered-readiness.json`
in the protected VPS `.env`, then run the full startup check:

```bash
"${compose[@]}" --profile init run --rm --no-deps release-init \
  quakestrike startup-check \
  --run-manifest /app/bootstrap-snapshots/recovered-readiness.json
```

Proceed only if `ready` is true. Follow the normal consumer and public cutover
checks before enabling ingestion or Cloudflare. Keep the original failed report
and the reconstructed file in protected recovery storage.
