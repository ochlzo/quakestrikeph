# Back up PostgreSQL on the VPS

Use this guide to check backups, install the backup jobs, or prepare database recovery.
Run Bash commands on the VPS from `/srv/quakestrikeph` unless a step specifies another folder.

| Task | Section |
| --- | --- |
| Inspect an installed job | [Check a run](#check-a-run) |
| Configure storage and timers | [One-time setup](#one-time-b2-and-vps-setup) |
| Understand retained data and recovery credentials | [Backup and recovery reference](#backup-and-recovery-reference) |

| Job | Philippine time | Storage or scope |
| --- | --- | --- |
| PostgreSQL backup | Daily, 03:00 | Encrypted Restic snapshot in private Backblaze B2. |
| Isolated restore test | Monday, 04:00 | Temporary network-isolated PostgreSQL container. |
| Checkpoint cleanup | Hourly | Only [eligible ingestion inputs](ingestion-checkpoint-retention.md). |

Keep protected recovery copies of `.env`, model artifacts, and bootstrap snapshots separately. These jobs protect PostgreSQL only.

## Check a run

```bash
systemctl status quakestrike-postgres-backup.service quakestrike-postgres-restore-test.service
sudo journalctl -u quakestrike-postgres-backup.service -u quakestrike-postgres-restore-test.service --since '7 days ago' --no-pager
sudo bash -c 'set -a; . /etc/quakestrike-backup/config; . /etc/quakestrike-backup/credentials; set +a; restic snapshots --tag quakestrike-postgres'
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh -ec 'psql -U quakestrike_maintenance -d "$POSTGRES_DB" -c "SELECT operation_type, status, started_at, finished_at, artifact_reference, verification_summary FROM maintenance_runs ORDER BY started_at DESC LIMIT 10"'
```

**Expected result:** The services report success, the backup has a snapshot ID, and its restore test has a successful linked record.
If PostgreSQL is available but the latest snapshot has no successful backup row, run a fresh backup before testing restoration.

| Evidence | What it proves |
| --- | --- |
| Restic snapshot listing | An encrypted upload exists. |
| Successful linked restore test | Download, file checksums, role/data restoration, and a query of restored `earthquake_events` succeeded. |
| Scheduled restore test | Does not verify recovered application passwords; the isolated container uses socket authentication. |

Keep the Restic password, B2 key, and database credentials in protected recovery storage.
See [recovery requirements](#recovery-requirements) for role restoration details.

## One-time B2 and VPS setup

1. Create a private B2 bucket.
2. Create a bucket-scoped **Read and Write** application key.
3. Enable **Allow List All Bucket Names** for S3 compatibility.
4. Keep Object Lock disabled so Restic can prune snapshots.
5. Set the lifecycle to **Keep only the last version of the file**.

Use the scoped application key rather than the master key. B2 removes hidden versions after Restic prunes them.

On the VPS, install Restic and create root-only configuration:

```bash
sudo apt-get install restic
sudo install -d -m 700 -o root -g root /etc/quakestrike-backup
sudo test -e /etc/quakestrike-backup/config || sudo install -m 600 -o root -g root /dev/null /etc/quakestrike-backup/config
sudo test -e /etc/quakestrike-backup/credentials || sudo install -m 600 -o root -g root /dev/null /etc/quakestrike-backup/credentials
sudo nano /etc/quakestrike-backup/config
```

The config file contains these two lines, with the actual bucket endpoint and
name substituted:

```text
RESTIC_REPOSITORY=s3:s3.REGION.backblazeb2.com/BUCKET_NAME
RESTIC_PASSWORD_FILE=/etc/quakestrike-backup/restic-password
```

Use `sudo nano /etc/quakestrike-backup/credentials` to enter the B2 key without
putting it in shell history or Git:

```text
AWS_ACCESS_KEY_ID=KEY_ID
AWS_SECRET_ACCESS_KEY=APPLICATION_KEY
```

Generate the separate Restic encryption password once:

```bash
if ! sudo test -e /etc/quakestrike-backup/restic-password; then
  sudo sh -c 'umask 077; openssl rand -base64 48 > /etc/quakestrike-backup/restic-password'
fi
sudo chmod 600 /etc/quakestrike-backup/{config,credentials,restic-password}
```

Save the Restic password outside the VPS in a team password manager. Without
it, the B2 backup cannot be restored after losing the VPS. The B2 key also
belongs in that password manager. Never commit either file or paste its contents
into a GitHub issue, pull request, or chat.

Initialize the empty B2 repository once:

```bash
sudo bash -c 'set -a; . /etc/quakestrike-backup/config; . /etc/quakestrike-backup/credentials; set +a; restic init'
```

After applying the reviewed Alembic migration, provision the two host-job
database roles from the VPS repository root. Repeat this after restoring a new
PostgreSQL cluster:

```bash
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-maintenance
```

Install the reviewed scripts outside the application checkout so deployments
cannot interrupt a running backup. Reinstall them after reviewing a script
change:

```bash
sudo install -d -m 755 /usr/local/libexec/quakestrike
sudo install -m 755 database/maintenance/*.sh /usr/local/libexec/quakestrike/
sudo install -m 644 database/maintenance/*.sql /usr/local/libexec/quakestrike/
sudo install -m 644 database/maintenance/*.service database/maintenance/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start quakestrike-postgres-backup.service
sudo systemctl start quakestrike-postgres-restore-test.service
sudo systemctl start quakestrike-ingestion-checkpoint-retention.service
sudo systemctl enable --now quakestrike-postgres-backup.timer quakestrike-postgres-restore-test.timer quakestrike-ingestion-checkpoint-retention.timer
systemctl list-timers 'quakestrike-*'
```

The backup timer runs at 19:00 UTC each day (03:00 Philippine time the next
day). The restore test runs at 20:00 UTC each Sunday (04:00 Philippine time on
Monday). Both have `Persistent=true`, so systemd catches up after downtime.
Restic keeps seven daily, four weekly, and three monthly snapshots, then prunes
unreferenced data. Retention groups by host and tag because the temporary dump
path changes on each run. Check B2 usage as the database grows.

Successful scheduled runs delete their checkpoints when their summaries commit.
The separate hourly cleanup drains older successful scheduled checkpoints and
deletes other terminal-run checkpoints after 30 days. It needs the
`create-maintenance` grants above. See the
[ingestion checkpoint retention guide](ingestion-checkpoint-retention.md) for
its scope, checks, and manual run command.


## Backup and recovery reference

The host runs installed copies of `database/maintenance/postgres-backup.sh`
daily and `database/maintenance/postgres-restore-test.sh` weekly, independently of Celery
Beat. The backup takes a PostgreSQL logical dump and a cluster-role export,
records SHA-256 checksums, and uploads the files through Restic's encrypted S3
repository in a private Backblaze B2 bucket. Temporary plaintext files are
root-only and removed after each run. The restore test downloads the latest
snapshot and restores it in a disposable, network-isolated PostgreSQL container;
it does not write to the live database.

Each backup, retention cleanup, and isolated restore test records its attempt
and result in `maintenance_runs`. The backup row stores the Restic snapshot ID
and the SHA-256 of its `SHA256SUMS` manifest; a restore-test row links to that
backup and records the verified event count. Interrupted attempts become
`abandoned` at the next run. If PostgreSQL is unavailable, inspect the systemd
journal for the fallback result. If PostgreSQL is healthy but a record cannot
be written, the service fails after its backup or restore work. Missing rows
never prove a backup succeeded.
The restore test requires the latest snapshot to have a successful backup row
when PostgreSQL is healthy; if it predates this ledger or its record is missing,
run a fresh backup before rerunning the restore test.

### Credentials and role scope

The database dump uses a dedicated `quakestrike_backup` login with
`pg_read_all_data`, no schema or write grant, and no superuser privilege. The
role export uses `pg_dumpall --no-role-passwords`. Passwords are intentionally
absent from the snapshot: keep a protected, off-VPS recovery copy of `.env`
(including database role passwords and URLs) alongside the B2 key and Restic
password. Restore those secrets from the team password manager and reprovision
database roles before starting services. Recreate the optional observer login
separately. The `quakestrike_maintenance` login can only read and write
`maintenance_runs`; both host-job logins use the container's local Unix socket
and have no password for remote login.

### Recovery requirements

For a real recovery, initialize the replacement PostgreSQL cluster with the
recovered `.env` so its bootstrap superuser receives `POSTGRES_PASSWORD`.
After restoring the role export and database dump, run
`provision-roles.sh create` with that same `.env` to reset the migration and
worker passwords, then run `create-maintenance` below. If the bootstrap
superuser already exists, reconcile that expected `CREATE ROLE` conflict when
loading `globals.sql`; do not skip its other role grants. Recreate the observer
login with `create-observer.py` if needed. The isolated scheduled test uses
socket authentication and does not test recovered application passwords.

### Restore compatibility reference

The isolated test restores into fresh PostgreSQL 16 storage using the backed-up bootstrap superuser.
It skips only that role's duplicate `CREATE ROLE` statement and preserves the other role grants.
It restores schema before data and sets the snapshot-check function's `search_path` before loading rows.
This also permits restoration of older snapshots created before that migration.
