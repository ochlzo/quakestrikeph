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

staging=$(mktemp -d /var/tmp/quakestrike-postgres.XXXXXXXX)
trap 'rm -rf -- "$staging"' EXIT

compose=(docker compose --env-file "$repo_root/.env" -f "$repo_root/infrastructure/compose.yml")

"${compose[@]}" exec -T postgres sh -ec \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' \
  > "$staging/database.dump"
"${compose[@]}" exec -T postgres sh -ec \
  'exec pg_dumpall --username="$POSTGRES_USER" --globals-only' \
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
restic backup --tag quakestrike-postgres "$staging"
restic forget --tag quakestrike-postgres \
  --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune

echo 'PostgreSQL backup uploaded and retention applied'
