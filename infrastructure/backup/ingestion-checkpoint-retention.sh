#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root=${QUAKESTRIKE_REPO_ROOT:-/srv/quakestrikeph}
script_directory=$(dirname "$0")
sql_file="$script_directory/ingestion-checkpoint-retention.sql"
test -r "$sql_file"

exec 9>/run/quakestrike-postgres-backup.lock
flock -w 7200 9 || { echo 'Timed out waiting for another maintenance job' >&2; exit 1; }

compose=(docker compose --env-file "$repo_root/.env" -f "$repo_root/infrastructure/compose.yml")
maintenance_database_name=$("${compose[@]}" config --format json | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["services"]["postgres"]["environment"]["POSTGRES_DB"])')
# shellcheck source=maintenance-run.sh
source "$script_directory/maintenance-run.sh"

affected=0
cleanup() {
  local result=$?
  if (( result != 0 )); then
    maintenance_end failed '' '' '' '' 'Checkpoint retention failed; see systemd journal' "$affected"
  fi
  exit "$result"
}
trap cleanup EXIT
maintenance_begin retention_cleanup 'ingestion_run_inputs:scheduled:24h'

for (( batch=0; batch<20; batch++ )); do
  deleted=$(maintenance_psql -f - < "$sql_file")
  [[ $deleted =~ ^[0-9]+$ ]] || { echo 'Invalid checkpoint deletion count' >&2; exit 1; }
  affected=$((affected + deleted))
  if (( deleted < 5000 )); then
    break
  fi
done

maintenance_end succeeded '' '' '' '' '' "$affected"
echo "Removed $affected old successful-run input checkpoints"
if (( ${maintenance_logging_failed:-0} )); then
  exit 1
fi
