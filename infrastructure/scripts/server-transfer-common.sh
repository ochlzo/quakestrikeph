#!/usr/bin/env bash
# Shared implementation for the two operator entry points. Never source a saved .env.
# Library variables are assigned and consumed by the entry points.
# shellcheck disable=SC2034,SC2154
set -Eeuo pipefail
umask 077

transfer_scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
transfer_helper=$transfer_scripts/server-transfer.py
transfer_project=infrastructure
transfer_repo=/srv/quakestrikeph

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
notice() { printf '%s\n' "$*"; }
require() { command -v "$1" >/dev/null || fail "Install $1 before continuing."; }
helper() { python3 "$transfer_helper" "$@"; }
confirm() {
    local answer
    [[ -r /dev/tty ]] || fail 'An interactive terminal is required for confirmation.'
    printf '%s\nType %s to continue: ' "$1" "$2" >/dev/tty
    read -r answer </dev/tty || fail 'Confirmation was not received.'
    [[ $answer == "$2" ]] || fail 'Cancelled. No confirmation was given.'
}
prompt() {
    local answer
    printf '%s [%s]: ' "$1" "$2" >/dev/tty
    read -r answer </dev/tty || fail 'Input was not received.'
    printf '%s' "${answer:-$2}"
}
as_operator() { sudo -H -u "$transfer_operator" -- "$@"; }
prerequisites() {
    [[ $(uname -s) == Linux ]] || fail 'Run this script on the Ubuntu server.'
    [[ $(uname -m) == x86_64 ]] || fail 'The inspected deployment and verification image require x86_64.'
    for command in python3 docker git tar gzip sha256sum flock sudo realpath; do require "$command"; done
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail 'Python 3.11 or later is required.'
    [[ $EUID == 0 ]] || fail 'Run with sudo bash, from your ubuntu account.'
    transfer_operator=${SUDO_USER:-root}
    [[ ${DOCKER_HOST:-unix:///var/run/docker.sock} == unix:///var/run/docker.sock ]] \
        || fail 'Use the local Docker socket, not a remote Docker host.'
    [[ $(docker context inspect --format '{{.Endpoints.docker.Host}}') == unix:///var/run/docker.sock ]] \
        || fail 'Use the default local Docker context.'
    docker info >/dev/null
    docker compose version >/dev/null
    docker buildx version >/dev/null || fail 'Install the Docker Buildx plugin before running the verification suite.'
    if [[ -e /run/quakestrike-server-transfer.lock ]]; then
        exec 6</run/quakestrike-server-transfer.lock
        flock -n 6 || fail 'Another backup or restore is running.'
        flock -u 6
        exec 6<&-
    fi
}
live_prerequisites() {
    [[ $transfer_operator == ubuntu ]] || fail 'Run sudo bash from the ubuntu account.'
    as_operator docker info >/dev/null || fail 'Give ubuntu access to the local Docker daemon first.'
    for command in systemctl tailscale gh restic curl ssh-keygen ufw; do require "$command"; done
    [[ $(ps -p 1 -o comm=) == systemd ]] || fail 'The production host must use systemd.'
    tailscale status --json | helper tailscale-name >/dev/null
    as_operator gh auth status >/dev/null 2>&1 || fail 'Run gh auth login as ubuntu first.'
}
lock_transfer() {
    exec 9>/run/quakestrike-server-transfer.lock
    flock -n 9 || fail 'Another backup or restore is running.'
}
project_empty() { helper empty-project "$1"; }
compose() { docker compose --env-file /dev/null -p "$transfer_project" -f "$transfer_config" "$@"; }
database_count() {
    # PostgreSQL variables expand inside the container, not in the host shell.
    # shellcheck disable=SC2016
    compose exec -T postgres sh -ec \
        'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM earthquake_events"'
}
private_tree() {
    chown -R "$transfer_operator:$transfer_operator" "$1"
    find "$1" -type d -exec chmod 700 {} +
    find "$1" -type f -exec chmod 600 {} +
}
restore_volume() {
    local logical=$1 volume
    volume=$(helper volume-name "$transfer_config" "$logical")
    docker run --rm --network none --user 0 \
        --mount "type=volume,src=$volume,dst=/restore" \
        --mount "type=bind,src=$backup_dir,dst=/backup,readonly" \
        --entrypoint sh "$postgres_image" -ec \
        'test -z "$(ls -A /restore)"; tar -xzpf "/backup/$1.tar.gz" -C /restore' sh "$logical"
}
failure_notice() {
    local status=$?
    if (( status != 0 )); then
        printf 'Operation failed. Services and partial files remain available for diagnosis. No automatic retry or deletion occurred.\n' >&2
    fi
}
