# Remove disposable test accounts on the VPS

Run this manual procedure in Bash from `/srv/quakestrikeph`.
Use it only for accounts that you own and created for testing.
Deletion removes their PostgreSQL rows, audit and delivery evidence, Clerk identities, and Redis phone state.
PostgreSQL backups cannot restore deleted Clerk identities.

The cleanup service is separate from deployment and ordinary startup.
It uses the tested worker image already installed on the VPS, with no build step, published port, or automatic restart.
Do not include `compose.local.yml` on the VPS.

## Prepare

1. Confirm that no database migration or other account cleanup is underway.
2. Confirm that the installed worker image includes this procedure's `--confirm-plan` flag.
3. Check root `.env` for the matching migration URL, account Redis URL, Clerk secret, and worker image tag.
4. Start a fresh PostgreSQL backup.

```bash
sudo systemctl start quakestrike-postgres-backup.service
```

5. Verify its [successful record](postgres-backups.md#check-a-run) and keep the snapshot ID.

Stop the sequence if any command fails. Never change the active checkout or rebuild a release image during this operation.
Coordinate concurrent rollouts so they do not restart the paused services during cleanup.
The configured Clerk instance must match the selected Bulletin accounts.
A missing matching Clerk identity refuses the VPS operation before deletion.

Define these commands in the same Bash session:

```bash
cd /srv/quakestrikeph
runtime=(docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.release.yml --profile alerts)
cleanup=(sudo flock -n --close /run/quakestrike-postgres-backup.lock docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.account-cleanup.yml run --rm --no-deps -T account-cleanup quakestrike delete-accounts)
```

The shared maintenance lock refuses overlap with migrations, backups, and retention operations that hold that lock.
`--no-deps` prevents cleanup from starting or recreating PostgreSQL and Redis.
There is no workflow dependency or automatic cleanup after deployment.

## Preview and delete

1. Record which services are running.

```bash
"${runtime[@]}" ps backend-api alert-worker alert-reconciliation
```

2. Pause account writes, callbacks, and ordinary alert consumers.

```bash
"${runtime[@]}" stop -t 120 backend-api alert-worker alert-reconciliation
```

The Backend also serves public data, so its API is unavailable during this short maintenance window.
Keep these services paused through deletion. Coordinate private alert tests using the selected accounts separately.

3. Set an explicit list of test accounts.

```bash
emails='tester1@example.com,tester2@example.com'
```

VPS mode refuses the implicit default list. Replace the example list if your targets differ.

4. Preview the accounts without deleting anything.

```bash
"${cleanup[@]}" --emails "$emails"
```

Review every local user ID, Clerk user ID, missing email, and dependent-row count.
Keep the private output for recovery. The final JSON contains `plan_sha256`.
If that field is absent, stop and install the tested worker version that includes VPS confirmation.

5. Copy the reviewed token into `confirmation`.

```bash
confirmation='paste-the-reviewed-plan_sha256-here'
```

6. Apply that exact selection.

```bash
"${cleanup[@]}" --emails "$emails" --apply --confirm-plan "$confirmation"
```

The command rechecks the plan before deletion and rechecks local accounts and dependent counts inside the locked database transaction.
Changed accounts, counts, Clerk selection, or database target require another preview.
The token confirms a selection; it does not prove that the selected accounts are disposable.

7. Restore only services that were running before maintenance.

If the Backend was running, start it:

```bash
"${runtime[@]}" start backend-api
```

If both alert services were running, start them:

```bash
"${runtime[@]}" start alert-reconciliation alert-worker
```

If only one alert service was running, start only that service.
Check service health and the public API using the [Backend verification procedure](backend-api.md#verify).
Restore these services after a refusal or failure too, once you inspect the result.
Do not run `up`, `down`, or volume removal as part of cleanup.

## Results and recovery

| Result | Action |
| --- | --- |
| Exit 0, `preview` | Review the plan; no deletion occurred. |
| Exit 0, `deleted` | Inspect the counts and restore previously running services. |
| Exit 1, `empty` | No selected account exists locally or in Clerk. |
| Exit 2, `refused` | Nothing was deleted; inspect the reason and preview again. |
| Exit 2, `partial` or `failed` | Some systems may already have changed. Inspect the private output before retrying. |

PostgreSQL deletion commits before Clerk and Redis cleanup. These systems do not share one transaction.
Failed Clerk deletions list the affected emails and user IDs. A new preview can find remaining Clerk identities.
After local rows disappear, a repeat run cannot reconstruct all Redis keys from those rows.
Inspect residual Redis state using the retained identifiers; phone rate-limit keys expire within 24 hours.
Never restore the live database automatically or repeat provider sends to repair cleanup.
