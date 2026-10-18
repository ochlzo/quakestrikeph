# Maintain ingestion checkpoints

Use this guide to install or check the hourly cleanup of temporary ingestion inputs.
Run Bash commands from `/srv/quakestrikeph` on the VPS.

| Records | Retention |
| --- | --- |
| Successful scheduled-run checkpoints | Deleted when the run summary commits; the host job drains older leftovers. |
| Other terminal-run checkpoints | Deleted 30 days after `finished_at`. |
| Active-run checkpoints | Kept, including old pending, running, and retry-wait runs. |
| Run summaries, events, forecasts, coverage, and audits | Preserved by this cleanup. |

## Install and enable cleanup

**Prerequisites:** Deploy the reviewed scripts, apply migrations, and verify a PostgreSQL backup.

Install it on the VPS after the updated repository is deployed, migrations are
applied, and a verified PostgreSQL backup exists. From `/srv/quakestrikeph`:

```bash
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-maintenance
sudo install -m 755 database/maintenance/ingestion-checkpoint-retention.sh /usr/local/libexec/quakestrike/
sudo install -m 755 database/maintenance/maintenance-run.sh /usr/local/libexec/quakestrike/
sudo install -m 644 database/maintenance/ingestion-checkpoint-retention.sql /usr/local/libexec/quakestrike/
sudo install -m 644 database/maintenance/quakestrike-ingestion-checkpoint-retention.service database/maintenance/quakestrike-ingestion-checkpoint-retention.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start quakestrike-ingestion-checkpoint-retention.service
sudo systemctl enable --now quakestrike-ingestion-checkpoint-retention.timer
```

## Check cleanup

The first cleanup is bounded to 100,000 rows. Later hourly runs continue until
old eligible inputs are drained. The job uses the same lock as backup and
restore tests, so they do not overlap. Check its result and the retained row
count without reading input contents:

```bash
systemctl status quakestrike-ingestion-checkpoint-retention.service
sudo journalctl -u quakestrike-ingestion-checkpoint-retention.service --since '24 hours ago' --no-pager
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres psql -U quakestrike -d quakestrike -c "SELECT count(*) FROM ingestion_run_inputs"
```

## Space and recovery reference

Normal PostgreSQL autovacuum makes deleted space reusable. The table file does
not have to become smaller after the first cleanup. Do not run `VACUUM FULL`
against the live table as routine maintenance.

Failed backfills may be requeued with the same run and checkpoints for 30 days
after finishing. After that boundary, recovery starts a new logical run from
the preserved source snapshot. Investigate old pending, running, or retry-wait
runs through normal lease and retry operations; their checkpoints are not
age-deleted.
