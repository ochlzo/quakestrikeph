#!/usr/bin/env bash

private_test_cleanup_complete() {
    local redis_id=$1 exists cleanup lifecycle
    exists=$(docker exec "$redis_id" redis-cli --raw EXISTS quakestrike:alert-testing:session) || return
    if [[ $exists == 1 ]]; then
        cleanup=$(docker exec "$redis_id" redis-cli --raw HGET quakestrike:alert-testing:session cleanup) || return
        lifecycle=$(docker exec "$redis_id" redis-cli --raw HGET quakestrike:alert-testing:session lifecycle) || return
        if [[ $cleanup != complete || $lifecycle != closed && $lifecycle != expired ]]; then
            echo 'End the private test and confirm closure_phase=complete before deployment.' >&2
            return 2
        fi
    elif [[ $exists != 0 ]]; then
        echo 'Private test cleanup could not be verified.' >&2
        return 2
    fi
}

# Source from deployment after selecting the target checkout.
stop_optional_services() {
    local ids service id status=0 consumer_running=0
    local controls=() containers=() redis_containers=()
    for service in alert-test-control pgadmin alert-test-consumer alert-test-relay alert-test-redis; do
        ids=$(docker ps --filter label=com.docker.compose.project=infrastructure \
            --filter "label=com.docker.compose.service=$service" --format '{{.ID}}') || return
        while IFS= read -r id; do
            [[ -n $id ]] || continue
            case $service in
                alert-test-control) controls+=("$id") ;;
                alert-test-redis) redis_containers+=("$id") ;;
                *) containers+=("$id") ;;
            esac
            [[ $service != alert-test-consumer ]] || consumer_running=1
        done <<< "$ids"
    done
    # Terminate all control requests before examining session state.
    if (( ${#controls[@]} )); then
        docker stop --time 20 "${controls[@]}" || return
    fi
    if (( ${#redis_containers[@]} == 0 && (${#controls[@]} > 0 || consumer_running) )); then
        echo 'Private test Redis is not running; cleanup cannot be verified.' >&2
        status=2
    fi
    for id in "${redis_containers[@]}"; do
        private_test_cleanup_complete "$id" || status=$?
    done
    if (( status != 0 )); then
        if (( ${#controls[@]} )); then
            docker start "${controls[@]}" || echo 'Restore the private control service to resolve cleanup.' >&2
        fi
        return "$status"
    fi
    if (( ${#containers[@]} )); then
        docker stop --time 20 "${containers[@]}" || return
    fi
    # Keep volatile session evidence until consumers stop and cleanup is rechecked.
    for id in "${redis_containers[@]}"; do
        private_test_cleanup_complete "$id" || return
    done
    if (( ${#redis_containers[@]} )); then
        docker stop --time 20 "${redis_containers[@]}" || return
    fi
}
