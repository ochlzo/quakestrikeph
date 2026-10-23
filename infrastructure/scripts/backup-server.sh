#!/usr/bin/env bash
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/server-transfer-common.sh"

usage() {
    cat <<'HELP'
Usage: sudo bash backup-server.sh [--check] [--output /home/ubuntu/quakestrike-transfer]
  --check   Read-only checks. Does not create a package or stop services.
  --output  New private folder under /home/ubuntu. Existing paths are refused.
  --help    Show this help.
The backup stops production after terminal confirmation and leaves it stopped.
HELP
}
check=0 output_given=0
output=/home/ubuntu/quakestrike-transfer
while (( $# )); do
    case $1 in
        --help) usage; exit 0 ;;
        --check) (( check == 0 )) || fail 'Duplicate --check.'; check=1; shift ;;
        --output) [[ $# -ge 2 && $2 != --* && $output_given == 0 ]] || fail '--output needs one folder.'; output=$2; output_given=1; shift 2 ;;
        *) usage >&2; fail "Unknown option: $1" ;;
    esac
done
prerequisites
live_prerequisites
output=$(realpath -m -- "$output")
[[ $output == /home/ubuntu/* && $output != /home/ubuntu/.* ]] || fail 'Choose a new folder directly under /home/ubuntu.'
[[ $(dirname -- "$output") == /home/ubuntu && ! -e $output && ! -L $output ]] || fail 'The output path already exists or is outside /home/ubuntu.'
cd "$transfer_repo"
[[ -z $(GIT_OPTIONAL_LOCKS=0 git -c safe.directory="$transfer_repo" status --porcelain --untracked-files=all) ]] || fail 'The server checkout must be clean, with committed transfer scripts.'
git -c safe.directory="$transfer_repo" cat-file -e HEAD:infrastructure/scripts/server-transfer.py \
    || fail 'Commit the recovery implementation in the source release before creating a package.'
[[ -f .env && -d model-artifacts && -f bootstrap-snapshots/bootstrap-readiness.json ]] || fail 'Production settings, model artifacts, or readiness evidence are missing.'
for file in config credentials restic-password; do
    [[ -s /etc/quakestrike-backup/$file && ! -L /etc/quakestrike-backup/$file ]] || fail "Missing recovery file: /etc/quakestrike-backup/$file"
done
[[ -s /home/ubuntu/.ssh/authorized_keys && ! -L /home/ubuntu/.ssh/authorized_keys ]] \
    || fail 'The ubuntu authorized_keys file is missing or is a symbolic link.'
source_files=(-f infrastructure/compose.yml -f infrastructure/compose.release.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml -f infrastructure/compose.bulletin.yml)
[[ ! -f .local/domain-cutover/compose.yml ]] || source_files+=(-f .local/domain-cutover/compose.yml)
source_compose() { docker compose -p infrastructure --env-file .env "${source_files[@]}" --profile '*' "$@"; }
# No saved dotenv file is executed as shell code, and resolved secrets never reach the terminal.
source_compose config --format json | helper inventory "$transfer_repo" "$output"
[[ $(as_operator gh variable get DEPLOY_ENABLED -R ochlzo/quakestrikeph) == false ]] || fail 'Set GitHub DEPLOY_ENABLED=false and finish any active deployment first.'
[[ $(as_operator gh run list -R ochlzo/quakestrikeph --limit 100 --json status --jq 'map(select(.status != "completed")) | length') == 0 ]] || fail 'Wait for active or queued GitHub workflows to finish.'
notice 'Preflight passed. A backup will stop all production work and public traffic.'
(( check == 0 )) || exit 0
confirm 'Create the final recovery package and leave the old system stopped?' BACKUP
lock_transfer
trap failure_notice EXIT
install -d -m 700 -o ubuntu -g ubuntu "$output"
source_compose config --format json > "$output/compose.json"
helper inventory "$transfer_repo" "$output" "$output/manifest.json" < "$output/compose.json"
{
    printf 'Tailscale Serve:\n'
    tailscale serve status
    printf '\nFirewall:\n'
    ufw status verbose
    printf '\nMaintenance timers:\n'
    systemctl list-timers --all --no-pager 'quakestrike-*'
} > "$output/server-settings.txt"
git -c safe.directory="$transfer_repo" bundle create "$output/repository.bundle" --all HEAD
git -c safe.directory="$transfer_repo" bundle verify "$output/repository.bundle"
mapfile -t images < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["images"]))' "$output/manifest.json")
notice 'Exporting the existing Docker images.'
docker image save "${images[@]}" | gzip > "$output/images.tar.gz"

sudo systemctl stop quakestrike-postgres-backup.timer quakestrike-postgres-restore-test.timer quakestrike-ingestion-checkpoint-retention.timer
exec 8>/run/quakestrike-postgres-backup.lock
flock -w 120 8 || fail 'Maintenance is still running. Retry after maintenance finishes.'
source infrastructure/scripts/stop-optional-services.sh
stop_optional_services
source_compose stop -t 360 beat
source_compose stop -t 360 dispatcher
source_compose stop -t 360 alert-worker alert-reconciliation data-ingestor prediction-worker
source_compose stop -t 360 bulletin backend-api traefik cloudflared
# The SQL command expands PostgreSQL variables inside the container.
# shellcheck disable=SC2016
count=$(source_compose exec -T postgres sh -ec 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM earthquake_events"')
helper event-count "$output" "$count"
source_compose stop -t 360 postgres redis
[[ -z $(docker ps -q --filter label=com.docker.compose.project=infrastructure) ]] || fail 'A project container is still running. No volume copy was taken.'
for service in postgres redis; do
    id=$(source_compose ps --all -q "$service")
    [[ $(docker inspect --format '{{.State.ExitCode}}:{{.State.OOMKilled}}' "$id") == 0:false ]] || fail "$service did not stop cleanly. Investigate before copying data."
done
application_paths=(.env model-artifacts bootstrap-snapshots)
for path in .local datasets data; do
    [[ ! -d $path ]] || application_paths+=("$path")
done
tar -czpf "$output/application.tar.gz" -C "$transfer_repo" "${application_paths[@]}"
host_paths=(etc/quakestrike-backup)
for path in etc/ssh/sshd_config.d etc/sudoers.d etc/ufw usr/local/libexec/quakestrike home/ubuntu/.ssh/authorized_keys home/ubuntu/.local/state/quakestrikeph; do
    [[ ! -e /$path ]] || host_paths+=("$path")
done
for path in /etc/systemd/system/quakestrike-*.service /etc/systemd/system/quakestrike-*.timer; do
    [[ ! -f $path ]] || host_paths+=("${path#/}")
done
tar --exclude=home/ubuntu/.local/state/quakestrikeph/server-restore \
    -czpf "$output/host-settings.tar.gz" -C / "${host_paths[@]}"
postgres_image=$(helper image "$output/compose.json" postgres)
for logical in postgres_data redis_data pgadmin_data; do
    volume=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["volumes"].get(sys.argv[2],""))' "$output/manifest.json" "$logical")
    [[ -n $volume ]] || continue
    docker run --rm --network none --user 0 \
        --mount "type=volume,src=$volume,dst=/source,readonly" \
        --mount "type=bind,src=$output,dst=/backup" \
        --entrypoint tar "$postgres_image" -czpf "/backup/$logical.tar.gz" -C /source .
done
for file in restore-server.sh server-transfer-common.sh server-transfer.py server-transfer-tests.sh; do
    install -m 600 "$script_dir/$file" "$output/$file"
done
helper seal "$output"
private_tree "$output"
chmod 700 "$output/restore-server.sh"
helper verify "$output"
notice "Backup verified: $output"
notice 'The old system and maintenance timers remain stopped. Download the package and keep two protected copies.'
