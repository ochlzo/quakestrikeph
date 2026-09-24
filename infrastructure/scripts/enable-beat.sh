#!/usr/bin/env bash

release_compose() {
    docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml "$@"
}

release_service_healthy() {
    local id health
    id=$(release_compose ps --status running -q "$1") || return 1
    [[ -n $id ]] || return 1
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id") || return 1
    [[ $health == healthy ]]
}

release_stop_beat() {
    release_compose --profile beat stop beat >/dev/null 2>&1 || true
}

release_enable_beat() {
    local service
    for service in dispatcher data-ingestor; do
        if ! release_service_healthy "$service"; then
            release_stop_beat
            echo "Beat not enabled: $service is unhealthy" >&2
            return 2
        fi
    done

    if ! release_compose --profile beat up -d --wait beat; then
        release_stop_beat
        echo 'Beat not enabled: startup failed' >&2
        return 2
    fi

    for service in beat dispatcher data-ingestor; do
        if ! release_service_healthy "$service"; then
            release_stop_beat
            echo "Beat stopped: $service is unhealthy after startup" >&2
            return 2
        fi
    done

    echo 'Beat enabled with healthy consumers'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    set -Eeuo pipefail
    cd "$(dirname "${BASH_SOURCE[0]}")/../.."
    release_enable_beat
fi
