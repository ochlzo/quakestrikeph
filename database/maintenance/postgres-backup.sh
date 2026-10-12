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
staging=$(mktemp -d /var/tmp/quakestrike-postgres.XXXXXXXX)
snapshot_output=$(mktemp /var/tmp/quakestrike-restic.XXXXXXXX)
cleanup() {
  local result=$?
  if (( result != 0 )); then
    maintenance_end failed '' '' '' '' 'See systemd journal for failed command'
  fi
  rm -rf -- "$staging"
  rm -f -- "$snapshot_output"
  exit "$result"
}
trap cleanup EXIT
maintenance_begin backup "$RESTIC_REPOSITORY"

"${compose[@]}" exec -T postgres sh -ec \
  'exec pg_dump --username=quakestrike_backup --dbname="$POSTGRES_DB" --format=custom' \
  > "$staging/database.dump"
"${compose[@]}" exec -T postgres sh -ec \
  'exec pg_dumpall --username=quakestrike_backup --globals-only --no-role-passwords' \
  > "$staging/globals.sql"
"${compose[@]}" exec -T postgres sh -ec 'printf "%s\n" "$POSTGRES_DB"' \
  > "$staging/database-name"
"${compose[@]}" exec -T postgres sh -ec 'printf "%s\n" "$POSTGRES_USER"' \
  > "$staging/database-user"

pg_restore_image=$("${compose[@]}" images -q postgres)
test -n "$pg_restore_image"
docker run --rm -i --network none --entrypoint pg_restore "$pg_restore_image" \
  --list < "$staging/database.dump" > /dev/null

(cd "$staging" && sha256sum database.dump globals.sql database-name database-user > SHA256SUMS)
restic backup --json --tag quakestrike-postgres "$staging" > "$snapshot_output"
snapshot_id=$(python3 - "$snapshot_output" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    summaries = [item for line in stream if (item := json.loads(line)).get("message_type") == "summary"]
if len(summaries) != 1 or not summaries[0].get("snapshot_id"):
    raise SystemExit("Restic did not return one saved snapshot")
print(summaries[0]["snapshot_id"])
PY
)
manifest_checksum=$(sha256sum "$staging/SHA256SUMS" | cut -d ' ' -f1)
maintenance_end succeeded "restic snapshot:$snapshot_id" "$manifest_checksum"

maintenance_begin retention_cleanup "$RESTIC_REPOSITORY"
restic forget --tag quakestrike-postgres \
  --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune
maintenance_end succeeded

echo 'PostgreSQL backup uploaded and retention applied'
if (( ${maintenance_logging_failed:-0} )); then
  exit 1
fi
