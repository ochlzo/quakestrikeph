#!/usr/bin/env bash
set -Eeuo pipefail
sha=${1:?Pass the tested Git commit SHA}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || exit 2
cd /srv/quakestrikeph
[[ $(git rev-parse HEAD) == "$sha" ]] || exit 2
export WORKER_IMAGE_TAG=$sha
compose() { docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml "$@"; }
compose --profile init run -T --rm --no-deps release-init quakestrike migrate </dev/null
compose exec -T postgres sh -s grant-worker < database/initialization/provision-roles.sh
compose exec -T postgres sh -s create-backend < database/initialization/provision-roles.sh
