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
previous_backend_tag=$(sed -n 's/^BACKEND_IMAGE_TAG=//p' .env)
[[ $previous_backend_tag =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid Backend image SHA' >&2; exit 2; }
[[ $(grep -c '^BACKEND_IMAGE_TAG=' .env) == 1 ]] || exit 2
docker image inspect "quakestrike-backend:$previous_backend_tag" >/dev/null
# Legacy manually built Backend images have no revision label; verify their live ID below.
backend_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-backend:$previous_backend_tag")
[[ -z $backend_revision || $backend_revision == '<no value>' || $backend_revision == "$previous_backend_tag" ]] || exit 2
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
alert_running=''
reconciliation_running=''
# The first alert release can start from a checkout without alert service definitions.
previous_services=$(compose --profile alerts config --services)
if grep -qx alert-worker <<< "$previous_services"; then
    alert_running=$(compose --profile alerts ps --status running -q alert-worker)
fi
if grep -qx alert-reconciliation <<< "$previous_services"; then
    reconciliation_running=$(compose --profile alerts ps --status running -q alert-reconciliation)
fi
[[ -z $alert_running && -z $reconciliation_running || -n $alert_running && -n $reconciliation_running ]] || { echo 'Both alert services must run together' >&2; exit 2; }
if [[ -n $alert_running ]]; then
    compose --profile alerts config --format json | python3 -c 'import json,sys; e=json.load(sys.stdin)["services"]["alert-worker"]["environment"]; sys.exit(0 if str(e["ALERT_RESOLUTION_ENABLED"]).lower()=="true" and str(e["ALERT_DELIVERY_ENABLED"]).lower()=="true" else 2)'
fi
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
migration_before=''
database_revision() {
    compose exec -T postgres sh -ec 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 -c "SELECT version_num FROM public.alembic_version"' </dev/null
}
stop_processing() {
    compose --profile beat stop beat
    compose stop dispatcher
    compose --profile alerts stop --timeout 180 alert-worker alert-reconciliation
    compose --profile prediction stop --timeout 180 data-ingestor prediction-worker
}
start_processing() {
    compose up -d --wait --no-deps data-ingestor || return
    if (( prediction_count > 0 )); then
        compose --profile prediction up -d --wait --no-deps --scale "prediction-worker=$prediction_count" prediction-worker || return
    fi
    if [[ -n $alert_running ]]; then
        compose --profile alerts up -d --wait --no-deps alert-reconciliation || return
        compose --profile alerts up -d --wait --no-deps alert-worker || return
    fi
    compose up -d --wait --no-deps dispatcher || return
    if [[ -n $beat_running ]]; then release_enable_beat || return; fi
}
rollback() {
    status=$?
    trap - EXIT
    if (( status != 0 )); then
        if (( rollout_started )); then
            stop_processing >&2 || true
            revision=$(database_revision) || revision='unverified'
            if [[ -z $migration_before || $revision != "$migration_before" ]]; then
                web_compose stop backend-api >&2 || true
                echo 'Schema changed or is unverified; processing remains stopped. Repair forward with this release. No database restore or downgrade was attempted.' >&2
                exit "$status"
            fi
        fi
        echo "Deployment failed; restoring $previous_tag" >&2
        if (( web_started )) && [[ -z $previous_bulletin_tag ]]; then
            web_compose stop bulletin >&2 || true
            web_compose rm -f bulletin >&2 || true
        fi
        if ! git switch --detach "$previous_commit" >&2; then
            echo 'Previous checkout could not be restored; processing remains stopped.' >&2
            exit "$status"
        fi
        export BACKEND_IMAGE_TAG=$previous_backend_tag
        source infrastructure/scripts/enable-beat.sh
        if (( web_started )); then
            if ! web_compose up -d --wait --no-deps backend-api >&2; then
                echo 'Previous Backend is unhealthy; processing remains stopped.' >&2
                exit "$status"
            fi
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
            if ! start_processing >&2; then
                compose --profile beat stop beat >&2 || true
                compose stop dispatcher >&2 || true
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
export BACKEND_IMAGE_TAG=$sha
source infrastructure/scripts/enable-beat.sh
compose --profile init --profile prediction --profile beat --profile alerts config --quiet
web_compose config --quiet
for service in backend-api traefik cloudflared; do
    [[ -n $(web_compose ps --status running -q "$service") ]] || { echo "$service is not running; complete Backend setup first" >&2; exit 2; }
done
[[ $(docker inspect --format '{{.Image}}' "$(web_compose ps --status running -q backend-api)") == $(docker image inspect --format '{{.Id}}' "quakestrike-backend:$previous_backend_tag") ]] || { echo 'Backend image does not match its configured previous tag' >&2; exit 2; }
if docker image inspect "quakestrike-backend:$sha" >/dev/null 2>&1; then
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-backend:$sha") == "$sha" ]]
else
    docker build --quiet --label "org.opencontainers.image.revision=$sha" -t "quakestrike-backend:$sha" -f apps/backend-api/Dockerfile .
fi
if docker image inspect "quakestrike-bulletin:$sha" >/dev/null 2>&1; then
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-bulletin:$sha") == "$sha" ]]
else
    web_compose build --quiet bulletin
fi

if docker image inspect "quakestrike-workers:$sha" >/dev/null 2>&1; then
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-workers:$sha") == "$sha" ]]
else
    docker build --quiet --label "org.opencontainers.image.revision=$sha" -t "quakestrike-workers:$sha" -f workers/Dockerfile .
fi
if (( prediction_count > 0 )); then
    if docker image inspect "quakestrike-prediction:$sha" >/dev/null 2>&1; then
        [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "quakestrike-prediction:$sha") == "$sha" ]]
    else
        docker build --quiet --build-arg "BASE_IMAGE_TAG=$sha" --label "org.opencontainers.image.revision=$sha" -t "quakestrike-prediction:$sha" -f workers/prediction-worker/Dockerfile .
    fi
fi

# Verify encrypted off-VPS upload and an isolated restore before downtime.
sudo -n systemctl start quakestrike-postgres-backup.service
sudo -n systemctl start quakestrike-postgres-restore-test.service
git fetch --no-tags origin main
[[ $(git rev-parse FETCH_HEAD) == "$sha" ]] || { echo 'A newer main commit exists; skipping stale deployment' >&2; exit 2; }
migration_before=$(database_revision)
[[ -n $migration_before ]] || { echo 'Database revision is unavailable' >&2; exit 2; }
rollout_started=1
stop_processing
web_started=1
web_compose stop backend-api
# Serialize database writes with host backup, restore, and retention jobs.
sudo -n env WORKER_IMAGE_TAG="$sha" flock -w 120 --close /run/quakestrike-postgres-backup.lock bash database/initialization/prepare-release-database.sh "$sha" </dev/null
compose --profile init run -T --rm --no-deps release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json </dev/null
web_compose up -d --wait --no-deps backend-api
start_processing
web_compose up -d --wait --no-deps bulletin
# Recreate Traefik so its file bind mount sees the new checkout's route file.
web_compose up -d --wait --no-deps --force-recreate traefik
curl --connect-timeout 10 --max-time 20 --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 2 https://quakestrikeph.qzz.io/ -o /dev/null
curl --connect-timeout 10 --max-time 20 --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 2 https://quakestrikeph.qzz.io/api/v1/earthquakes/search -H 'Content-Type: application/json' --data '{"limit":1}' -o /dev/null

python3 infrastructure/scripts/save-release-tags.py .env "$sha"
# Cleanup cannot undo a release that has passed its checks and saved its tags.
trap - EXIT
echo "Deployed application commit $sha"
if ! python3 infrastructure/scripts/cleanup-release-images.py .env "$sha"; then
    echo '::warning::Deployment succeeded, but Docker cleanup failed. Review cleanup logs before retrying.' >&2
fi
