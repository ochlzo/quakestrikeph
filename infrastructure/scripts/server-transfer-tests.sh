#!/usr/bin/env bash
# Internal test runner. It never receives production provider credentials.
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/server-transfer-common.sh"
[[ $# == 2 ]] || fail 'Pass the restored repository and a new report directory.'
root=$(realpath -e -- "$1")
reports=$2
[[ ! -e $reports ]] || fail 'The test report directory already exists.'
require docker
require python3
require flock
exec 7>/run/quakestrike-transfer-tests.lock
flock -n 7 || fail 'Another transfer test suite is running.'
helper empty-project quakestrike-data-ingestion-test
install -d -m 700 "$reports"
install -d -m 700 "$reports/tmp"
export TMPDIR=$reports/tmp
owner=$(helper uuid)
tag=transfer-check-$owner
export QUAKESTRIKE_TRANSFER_OWNER=$owner
export MODEL_ARTIFACT_HOST_DIRECTORY=$root/model-artifacts
cd "$root"
docker compose --env-file /dev/null -p quakestrike-data-ingestion-test \
    -f infrastructure/compose.integration.yml --profile '*' config --format json \
    | python3 -c '
import json,sys
c=json.load(sys.stdin)
for section in ("services","networks","volumes"):
    for item in c.get(section,{}).values(): item["labels"]={"io.quakestrike.transfer":sys.argv[1]}
json.dump(c,sys.stdout)
' "$owner" > "$reports/compose.json"
tc() { docker compose --env-file /dev/null -p quakestrike-data-ingestion-test -f "$reports/compose.json" "$@"; }
finish_tests() {
    local status=$?
    trap - EXIT
    helper cleanup quakestrike-data-ingestion-test "$owner" || status=1
    exit "$status"
}
trap finish_tests EXIT
exec > >(tee "$reports/checks.log") 2>&1
for script in infrastructure/scripts/*.sh database/initialization/*.sh database/maintenance/*.sh; do bash -n "$script"; done
python3 infrastructure/scripts/check-local-compose.py
python3 infrastructure/scripts/check-alert-testing-compose.py
if [[ -d infrastructure/tests ]]; then python3 -m unittest discover -s infrastructure/tests -v; fi
tc up -d --wait postgres-test redis-test
tc --profile prediction-smoke build prediction-smoke-runner
docker build --build-arg BASE_IMAGE=quakestrike-data-ingestion-test-prediction-smoke-runner:latest \
    -t "quakestrike-transfer-checks:$tag" -f infrastructure/Dockerfile.transfer-tests .
python3 - "$reports/compose.json" "quakestrike-transfer-checks:$tag" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]); config=json.loads(path.read_text())
runner=config['services']['prediction-smoke-runner']
runner.pop('build',None); runner['image']=sys.argv[2]
path.write_text(json.dumps(config))
PY
tc --profile prediction-smoke run --rm --no-deps \
    -v "$reports:/reports" prediction-smoke-runner pytest --config-file workers/pyproject.toml \
    workers/tests/unit workers/tests/integration --junitxml=/reports/workers.xml
helper junit "$reports/workers.xml"
python_checks=(workers database infrastructure/scripts/save-release-tags.py infrastructure/scripts/cleanup-release-images.py infrastructure/scripts/server-transfer.py infrastructure/scripts/smoke-alert-testing-package.py infrastructure/tests)
tc --profile prediction-smoke run --rm --no-deps prediction-smoke-runner ruff check "${python_checks[@]}"
tc --profile prediction-smoke run --rm --no-deps prediction-smoke-runner ruff format --check "${python_checks[@]}"
tc exec -T postgres-test sh /opt/quakestrike/provision-roles.sh create-backend
tc run --build --rm --no-deps backend-test-runner npm test
tc run --rm --no-deps backend-test-runner
tc --profile alert-testing-workflow up --build -d --wait alert-testing-backend-fixture
tc run --build --rm --no-deps -v "$reports:/reports" \
    -e TEST_ALERT_BACKEND_URL=http://alert-testing-backend-fixture:3000 test-runner \
    pytest --config-file workers/pyproject.toml workers/tests/release/test_alert_testing_workflow.py \
    --junitxml=/reports/release.xml
helper junit "$reports/release.xml"

# Mirror the CI package check using fixture credentials and loopback-only ingress.
docker build -t "quakestrike-workers:$tag" -f workers/Dockerfile .
docker build --build-arg "BASE_IMAGE_TAG=$tag" -t "quakestrike-alert-testing:$tag" -f apps/quakestrikeph-alert-testing/Dockerfile .
python3 infrastructure/scripts/smoke-alert-testing-package.py "$tag"

docker build --target development -t "quakestrike-bulletin-checks:$tag" -f apps/quakestrikeph-bulletin/Dockerfile .
docker run --rm --network none --label "io.quakestrike.transfer=$owner" \
    --mount "type=bind,src=$root/apps/quakestrikeph-bulletin/tests,dst=/app/tests,readonly" \
    "quakestrike-bulletin-checks:$tag" sh -ec '
    pnpm check
    pnpm build
    for name in test:event-results test:mobile-drawer test:location-edit test:identity test:sms-enrollment test:forecast test:forecast-replay; do
        pnpm run "$name"
    done'
docker build -t "quakestrike-bulletin-checks:$tag-production" -f apps/quakestrikeph-bulletin/Dockerfile .
notice 'Required CI checks, real-model tests, and portable Bulletin tests passed without pytest skips.'
notice 'The separately documented Microsoft Edge browser acceptance test remains manual.'
