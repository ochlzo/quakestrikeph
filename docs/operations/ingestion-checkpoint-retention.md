# Ingestion checkpoint retention

Successful scheduled runs delete their own checkpoints when their summary
commits. The hourly host job drains older successful scheduled checkpoints
and deletes checkpoints of any other terminal run 30 days after `finished_at`.
Active runs keep their checkpoints. `ingestion_runs` summary counters and
earthquake, forecast, source coverage, and audit records remain. See
[ADR 0034](../adr/0034-bound-successful-ingestion-checkpoints.md).

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

The first cleanup is bounded to 100,000 rows. Later hourly runs continue until
old eligible inputs are drained. The job uses the same lock as backup and
restore tests, so they do not overlap. Check its result and the retained row
count without reading input contents:

```bash
systemctl status quakestrike-ingestion-checkpoint-retention.service
sudo journalctl -u quakestrike-ingestion-checkpoint-retention.service --since '24 hours ago' --no-pager
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres psql -U quakestrike -d quakestrike -c "SELECT count(*) FROM ingestion_run_inputs"
```

Normal PostgreSQL autovacuum makes deleted space reusable. The table file does
not have to become smaller after the first cleanup. Do not run `VACUUM FULL`
against the live table as routine maintenance.

Failed backfills may be requeued with the same run and checkpoints for 30 days
after finishing. After that boundary, recovery starts a new logical run from
the preserved source snapshot. Investigate old pending, running, or retry-wait
runs through normal lease and retry operations; their checkpoints are not
age-deleted.
