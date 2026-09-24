# PostgreSQL backups on the VPS

The host runs installed copies of `infrastructure/backup/postgres-backup.sh`
daily and `infrastructure/backup/postgres-restore-test.sh` weekly, independently of Celery
Beat. The backup takes a PostgreSQL logical dump and a cluster-role export,
records SHA-256 checksums, and uploads the files through Restic's encrypted S3
repository in a private Backblaze B2 bucket. Temporary plaintext files are
root-only and removed after each run. The restore test downloads the latest
snapshot and restores it in a disposable, network-isolated PostgreSQL container;
it does not write to the live database.

The `maintenance_runs` table from the database design has not been migrated
yet. Until it is, systemd's journal is the run record. An operator must check
failed units and timer runs; a missing failure notification is not proof that
backups succeeded.

## One-time B2 and VPS setup

Create a private B2 bucket and a bucket-scoped **Read and Write** application
key. Enable **Allow List All Bucket Names** for S3 API compatibility. Do not use
the master application key. Keep Object Lock disabled so Restic can prune old
snapshots. Set the bucket lifecycle to **Keep only the last version of the file**
so B2 eventually removes hidden versions after Restic prunes them.

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

Install the reviewed scripts outside the application checkout so deployments
cannot interrupt a running backup. Reinstall them after reviewing a script
change:

```bash
sudo install -d -m 755 /usr/local/libexec/quakestrike
sudo install -m 755 infrastructure/backup/*.sh /usr/local/libexec/quakestrike/
sudo install -m 644 infrastructure/backup/*.service infrastructure/backup/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start quakestrike-postgres-backup.service
sudo systemctl start quakestrike-postgres-restore-test.service
sudo systemctl enable --now quakestrike-postgres-backup.timer quakestrike-postgres-restore-test.timer
systemctl list-timers 'quakestrike-postgres-*'
```

The backup timer runs at 19:00 UTC each day (03:00 Philippine time the next
day). The restore test runs at 20:00 UTC each Sunday (04:00 Philippine time on
Monday). Both have `Persistent=true`, so systemd catches up after downtime.
Restic keeps seven daily, four weekly, and three monthly snapshots, then prunes
unreferenced data. Retention groups by host and tag because the temporary dump
path changes on each run. Check B2 usage as the database grows.

## Check a run

```bash
systemctl status quakestrike-postgres-backup.service quakestrike-postgres-restore-test.service
sudo journalctl -u quakestrike-postgres-backup.service -u quakestrike-postgres-restore-test.service --since '7 days ago' --no-pager
sudo bash -c 'set -a; . /etc/quakestrike-backup/config; . /etc/quakestrike-backup/credentials; set +a; restic snapshots --tag quakestrike-postgres'
```

The snapshot list proves that an encrypted upload exists. A successful weekly
restore test proves more: it downloads the snapshot, checks its source files
against `SHA256SUMS`, restores roles and data in a fresh PostgreSQL 16
container, and queries the restored `earthquake_events` table. The test
restores schema first and sets `search_path` on the existing snapshot-check
function before loading rows; this is needed because the current function
calls `public.digest` without a schema qualifier. Use the same order in a
manual recovery until a reviewed migration fixes that function. Keep the Restic
password and B2 key available to authorized operators for disaster recovery.
