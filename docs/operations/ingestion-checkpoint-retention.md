# Ingestion checkpoint retention

The hourly host job removes `ingestion_run_inputs` rows only for successful
scheduled ingestion runs finished more than 24 hours ago. It leaves failed,
active, manual, and backfill runs untouched. `ingestion_runs` summary counters
and earthquake, forecast, source coverage, and audit records remain. See
[ADR 0034](../adr/0034-bound-successful-ingestion-checkpoints.md).

Install it on the VPS after the updated repository is deployed, migrations are
applied, and a verified PostgreSQL backup exists. From `/srv/quakestrikeph`:

```bash
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-maintenance
sudo install -m 755 infrastructure/backup/ingestion-checkpoint-retention.sh /usr/local/libexec/quakestrike/
sudo install -m 755 infrastructure/backup/maintenance-run.sh /usr/local/libexec/quakestrike/
sudo install -m 644 infrastructure/backup/ingestion-checkpoint-retention.sql /usr/local/libexec/quakestrike/
sudo install -m 644 infrastructure/backup/quakestrike-ingestion-checkpoint-retention.service infrastructure/backup/quakestrike-ingestion-checkpoint-retention.timer /etc/systemd/system/
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
