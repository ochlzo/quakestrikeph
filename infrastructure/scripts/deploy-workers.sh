#!/usr/bin/env bash
set -Eeuo pipefail

sha=${1:?Pass the tested Git commit SHA}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA' >&2; exit 2; }

cd /srv/quakestrikeph
[[ -f .env ]] || { echo 'Production .env is missing' >&2; exit 2; }
[[ -z $(git status --porcelain --untracked-files=all) ]] || { echo 'Server checkout is not clean' >&2; exit 2; }

previous_commit=$(git rev-parse HEAD)
previous_tag=$(sed -n 's/^WORKER_IMAGE_TAG=//p' .env)
[[ $previous_tag =~ ^[0-9a-f]{40}$ ]] || { echo 'WORKER_IMAGE_TAG must be the previous tested SHA' >&2; exit 2; }
[[ $(grep -c '^WORKER_IMAGE_TAG=' .env) == 1 ]] || { echo 'Expected one WORKER_IMAGE_TAG in .env' >&2; exit 2; }

compose() {
    docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml "$@"
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
rollback() {
    status=$?
    trap - EXIT
    if (( status != 0 )); then
        echo "Deployment failed; restoring $previous_tag" >&2
        git switch --detach "$previous_commit" >&2 || true
        export WORKER_IMAGE_TAG=$previous_tag
        if (( rollout_started )); then
            compose --profile beat stop beat >&2 || true
            compose up -d --wait --no-deps data-ingestor >&2 || true
            if (( prediction_count > 0 )); then
                compose --profile prediction up -d --wait --no-deps --scale "prediction-worker=$prediction_count" prediction-worker >&2 || true
            fi
            compose up -d --wait --no-deps dispatcher >&2 || true
            if [[ -n $beat_running ]]; then
                compose --profile beat up -d --wait beat >&2 || true
            fi
        fi
    fi
    exit "$status"
}
trap rollback EXIT

git switch --detach "$sha"
export WORKER_IMAGE_TAG=$sha
compose --profile init --profile prediction --profile beat config --quiet

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
compose --profile init run --rm --no-deps release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json

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
    compose --profile beat up -d --wait beat
fi

sed -i "s/^WORKER_IMAGE_TAG=.*/WORKER_IMAGE_TAG=$sha/" .env
echo "Deployed worker commit $sha"
