#!/usr/bin/env bash
set -Eeuo pipefail

sha=${1:?Pass the tested Git commit SHA}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 2; }

cd /srv/quakestrikeph
[[ -f .env ]] || { echo 'Production .env is missing' >&2; exit 2; }
[[ -z $(git status --porcelain --untracked-files=all) ]] || { echo 'Server checkout is not clean' >&2; exit 2; }

previous_commit=$(git rev-parse HEAD)
previous_bulletin_tag=$(sed -n 's/^BULLETIN_IMAGE_TAG=//p' .env)
[[ $(grep -c '^BULLETIN_IMAGE_TAG=' .env || true) -le 1 ]] || { echo 'Duplicate BULLETIN_IMAGE_TAG' >&2; exit 2; }
if [[ -n $previous_bulletin_tag ]]; then
    [[ $previous_bulletin_tag =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid previous Bulletin SHA' >&2; exit 2; }
    docker image inspect "quakestrike-bulletin:$previous_bulletin_tag" >/dev/null
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-bulletin:$previous_bulletin_tag") == "$previous_bulletin_tag" ]]
fi
previous_tag=$(sed -n 's/^WORKER_IMAGE_TAG=//p' .env)
[[ $previous_tag =~ ^[0-9a-f]{40}$ ]] || { echo 'WORKER_IMAGE_TAG must be the previous tested SHA' >&2; exit 2; }
[[ $(grep -c '^WORKER_IMAGE_TAG=' .env) == 1 ]] || { echo 'Expected one WORKER_IMAGE_TAG in .env' >&2; exit 2; }

compose() {
    docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml "$@"
}

web_compose() {
    local edge_files=(); [[ ! -f infrastructure/compose.edge.yml ]] || edge_files=(-f infrastructure/compose.edge.yml)
    docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml "${edge_files[@]}" -f infrastructure/compose.bulletin.yml "$@"
}

for service in postgres redis dispatcher data-ingestor; do
    [[ -n $(compose ps --status running -q "$service") ]] || { echo "$service is not running" >&2; exit 2; }
done
prediction_count=$(compose --profile prediction ps --status running -q prediction-worker | wc -l)
beat_running=$(compose --profile beat ps --status running -q beat)
docker image inspect "quakestrike-workers:$previous_tag" >/dev/null
[[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-workers:$previous_tag") == "$previous_tag" ]]
if (( prediction_count > 0 )); then
    docker image inspect "quakestrike-prediction:$previous_tag" >/dev/null
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-prediction:$previous_tag") == "$previous_tag" ]]
fi

git fetch --no-tags origin main
[[ $(git rev-parse FETCH_HEAD) == "$sha" ]] || { echo 'A newer main commit exists; skipping stale deployment' >&2; exit 2; }

rollout_started=0
web_started=0
rollback() {
    status=$?
    trap - EXIT
    if (( status != 0 )); then
        echo "Deployment failed; restoring $previous_tag" >&2
        if (( web_started )) && [[ -z $previous_bulletin_tag ]]; then
            web_compose stop bulletin >&2 || true
            web_compose rm -f bulletin >&2 || true
        fi
        git switch --detach "$previous_commit" >&2 || true
        if (( web_started )); then
            if [[ -n $previous_bulletin_tag ]]; then
                export BULLETIN_IMAGE_TAG=$previous_bulletin_tag
                web_compose up -d --wait --no-deps bulletin >&2 || true
                web_compose up -d --wait --no-deps --force-recreate traefik >&2 || true
            else
                rollback_edge=(); [[ ! -f infrastructure/compose.edge.yml ]] || rollback_edge=(-f infrastructure/compose.edge.yml)
                docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml "${rollback_edge[@]}" up -d --wait --no-deps --force-recreate traefik >&2 || true
            fi
        fi
        export WORKER_IMAGE_TAG=$previous_tag
        if (( rollout_started )); then
            compose --profile beat stop beat >&2 || true
            compose up -d --wait --no-deps data-ingestor >&2 || true
            if (( prediction_count > 0 )); then
                compose --profile prediction up -d --wait --no-deps --scale "prediction-worker=$prediction_count" prediction-worker >&2 || true
            fi
            compose up -d --wait --no-deps dispatcher >&2 || true
            if [[ -n $beat_running ]]; then
                release_enable_beat >&2 || true
            fi
        fi
    fi
    exit "$status"
}
trap rollback EXIT

# Restore the full checkout, including VPS-hosted Bulletin source.
git sparse-checkout disable
git switch --detach "$sha"
export BULLETIN_IMAGE_TAG=$sha
export WORKER_IMAGE_TAG=$sha
source infrastructure/scripts/enable-beat.sh
compose --profile init --profile prediction --profile beat config --quiet
web_compose config --quiet
for service in backend-api traefik cloudflared; do
    [[ -n $(web_compose ps --status running -q "$service") ]] || { echo "$service is not running; complete Backend setup first" >&2; exit 2; }
done
if docker image inspect "quakestrike-bulletin:$sha" >/dev/null 2>&1; then
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-bulletin:$sha") == "$sha" ]]
else
    docker build --quiet --label "org.opencontainers.image.revision=$sha" -t "quakestrike-bulletin:$sha" -f apps/quakestrikeph-bulletin/Dockerfile .
fi

if docker image inspect "quakestrike-workers:$sha" >/dev/null 2>&1; then
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-workers:$sha") == "$sha" ]]
else
    docker build --quiet --label "org.opencontainers.image.revision=$sha" -t "quakestrike-workers:$sha" -f workers/Dockerfile workers
fi
if (( prediction_count > 0 )); then
    if docker image inspect "quakestrike-prediction:$sha" >/dev/null 2>&1; then
        [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-prediction:$sha") == "$sha" ]]
    else
        docker build --quiet --build-arg "BASE_IMAGE_TAG=$sha" --label "org.opencontainers.image.revision=$sha" -t "quakestrike-prediction:$sha" -f workers/prediction-worker/Dockerfile workers
    fi
fi

# A schema change fails here until an operator runs the migration and readiness steps.
compose --profile init run -T --rm --no-deps release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json </dev/null

rollout_started=1
if [[ -n $beat_running ]]; then
    compose --profile beat stop beat
fi
compose stop dispatcher
compose up -d --wait --no-deps data-ingestor
if (( prediction_count > 0 )); then
    compose --profile prediction up -d --wait --no-deps --scale "prediction-worker=$prediction_count" prediction-worker
fi
compose up -d --wait --no-deps dispatcher
if [[ -n $beat_running ]]; then
    release_enable_beat
fi

web_started=1
web_compose up -d --wait --no-deps bulletin
# Recreate Traefik so its file bind mount sees the new checkout's route file.
web_compose up -d --wait --no-deps --force-recreate traefik
curl --connect-timeout 10 --max-time 20 --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 2 https://quakestrikeph.qzz.io/ -o /dev/null
curl --connect-timeout 10 --max-time 20 --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 2 https://quakestrikeph.qzz.io/api/v1/earthquakes/search -H 'Content-Type: application/json' --data '{"limit":1}' -o /dev/null

sed -i "s/^WORKER_IMAGE_TAG=.*/WORKER_IMAGE_TAG=$sha/" .env
if [[ -n $previous_bulletin_tag ]]; then
    sed -i "s/^BULLETIN_IMAGE_TAG=.*/BULLETIN_IMAGE_TAG=$sha/" .env
else
    sed -i '/^BULLETIN_IMAGE_TAG=/d' .env
    printf '\nBULLETIN_IMAGE_TAG=%s\n' "$sha" >> .env
fi
echo "Deployed workers and Bulletin commit $sha"
