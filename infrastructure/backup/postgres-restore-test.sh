#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root=${QUAKESTRIKE_REPO_ROOT:-/srv/quakestrikeph}
config_file=/etc/quakestrike-backup/config
credentials_file=/etc/quakestrike-backup/credentials

for file in "$config_file" "$credentials_file"; do
  if [[ ! -r $file ]]; then
    echo "Backup configuration is missing: $file" >&2
    exit 1
  fi
done

set -a
# These files are root-owned and readable only by root.
# shellcheck disable=SC1090
source "$config_file"
# shellcheck disable=SC1090
source "$credentials_file"
set +a
: "${RESTIC_REPOSITORY:?}"
: "${RESTIC_PASSWORD_FILE:?}"
: "${AWS_ACCESS_KEY_ID:?}"
: "${AWS_SECRET_ACCESS_KEY:?}"
test -r "$RESTIC_PASSWORD_FILE"

exec 9>/run/quakestrike-postgres-backup.lock
flock -w 7200 9 || { echo 'Timed out waiting for another backup or restore test' >&2; exit 1; }

compose=(docker compose --env-file "$repo_root/.env" -f "$repo_root/infrastructure/compose.yml")
maintenance_database_name=$("${compose[@]}" config --format json | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["services"]["postgres"]["environment"]["POSTGRES_DB"])')
# shellcheck source=maintenance-run.sh
source "$(dirname "$0")/maintenance-run.sh"
restored=$(mktemp -d /var/tmp/quakestrike-restore.XXXXXXXX)
container="quakestrike-restore-test-$$"
cleanup() {
  local result=$?
  if (( result != 0 )); then
    maintenance_end failed '' '' '' '' 'See systemd journal for failed command'
  fi
  docker rm -fv "$container" > /dev/null 2>&1 || true
  rm -rf -- "$restored"
  exit "$result"
}
trap cleanup EXIT

snapshot_id=$(restic snapshots --json --tag quakestrike-postgres | python3 -c \
  'import json,sys; rows=json.load(sys.stdin); print(max(rows, key=lambda row: row["time"])["id"])')
if backup_run_id=$(maintenance_psql -v snapshot_ref="restic snapshot:$snapshot_id" <<'SQL'
SELECT maintenance_run_id FROM maintenance_runs
WHERE operation_type = 'backup' AND status = 'succeeded'
  AND artifact_reference = :'snapshot_ref'
ORDER BY started_at DESC LIMIT 1;
SQL
); then
  if [[ -z $backup_run_id ]]; then
    echo 'Snapshot predates maintenance records; recording restore in systemd journal' >&2
  fi
else
  backup_run_id=
  echo 'Backup record unavailable; recording restore in systemd journal' >&2
fi
maintenance_begin restore_test "restic snapshot:$snapshot_id" "$backup_run_id"
restic restore "$snapshot_id" --target "$restored"
dump_file=$(find "$restored" -type f -name database.dump -print -quit)
test -n "$dump_file"
backup_dir=${dump_file%/*}
(cd "$backup_dir" && sha256sum --check SHA256SUMS)

postgres_image=$("${compose[@]}" images -q postgres)
test -n "$postgres_image"

# The test container has no network and no persistent volume. Trust auth is
# confined to its local Unix socket and disappears when the container exits.
docker run --rm --detach --name "$container" --network none \
  --env POSTGRES_HOST_AUTH_METHOD=trust "$postgres_image" > /dev/null
ready=false
for _ in {1..60}; do
  if docker exec "$container" pg_isready -U postgres -d postgres > /dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [[ $ready != true ]]; then
  echo 'Isolated PostgreSQL container did not become ready' >&2
  exit 1
fi

docker exec -i "$container" psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
  < "$backup_dir/globals.sql"
database_name=$(< "$backup_dir/database-name")
database_user=$(< "$backup_dir/database-user")
docker exec "$container" createdb -U postgres -O "$database_user" "$database_name"
docker exec -i "$container" pg_restore --exit-on-error -U postgres \
  --section=pre-data --dbname="$database_name" < "$backup_dir/database.dump"
# The existing snapshot-check function calls public.digest without a schema.
# pg_restore's empty search_path otherwise breaks COPY on prediction_jobs.
docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d "$database_name" \
  -c 'ALTER FUNCTION public.quakestrike_prediction_input_snapshot_sha256(jsonb) SET search_path = public, pg_catalog'
docker exec -i "$container" pg_restore --exit-on-error -U postgres \
  --section=data --section=post-data --dbname="$database_name" \
  < "$backup_dir/database.dump"
event_count=$(docker exec "$container" psql -v ON_ERROR_STOP=1 -At -U postgres \
  -d "$database_name" \
  -c 'SELECT count(*) FROM earthquake_events')
maintenance_end succeeded "restic snapshot:$snapshot_id" '' "$backup_run_id" \
  "Checksums and isolated PostgreSQL restore passed; earthquake_events=$event_count" '' "$event_count"

echo "Isolated PostgreSQL restore test succeeded; earthquake_events=$event_count"
if (( ${maintenance_logging_failed:-0} )); then
  exit 1
fi
