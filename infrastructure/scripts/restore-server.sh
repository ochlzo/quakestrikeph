#!/usr/bin/env bash
set -Eeuo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/server-transfer-common.sh"

usage() {
    cat <<'HELP'
Usage: sudo bash restore-server.sh [--check] [--rehearse] --backup-dir FOLDER
       sudo bash restore-server.sh --cleanup-rehearsal
  --check               Read-only package and destination checks.
  --backup-dir FOLDER   Uploaded quakestrike-transfer folder.
  --rehearse            Isolated Docker restore; no providers, scheduling, or public ports.
  --cleanup-rehearsal   Confirm and delete only labeled rehearsal resources.
  --help                Show this help.
Production restoration refuses an existing installation. There is no force option.
HELP
}
check=0 rehearsal=0 cleanup=0
backup_dir=''
while (( $# )); do
    case $1 in
        --help) usage; exit 0 ;;
        --check) (( check == 0 )) || fail 'Duplicate --check.'; check=1; shift ;;
        --rehearse) (( rehearsal == 0 )) || fail 'Duplicate --rehearse.'; rehearsal=1; shift ;;
        --cleanup-rehearsal) (( cleanup == 0 )) || fail 'Duplicate cleanup mode.'; cleanup=1; shift ;;
        --backup-dir) [[ $# -ge 2 && -z $backup_dir && $2 != --* ]] || fail '--backup-dir needs one folder.'; backup_dir=$2; shift 2 ;;
        *) usage >&2; fail "Unknown option: $1" ;;
    esac
done
prerequisites
rehearsal_state=/var/lib/quakestrike-restore-test
if (( cleanup )); then
    [[ -z $backup_dir && $check == 0 && $rehearsal == 0 ]] || fail 'Cleanup cannot be combined with other options.'
    [[ -d $rehearsal_state && ! -L $rehearsal_state && -f $rehearsal_state/owner ]] || fail 'No recorded rehearsal exists.'
    owner=$(cat "$rehearsal_state/owner")
    [[ $owner =~ ^[0-9a-f-]{36}$ ]] || fail 'Invalid rehearsal owner record.'
    lock_transfer
    helper check-owner quakestrike-restore-test "$owner"
    test_owner=''
    if [[ -f $rehearsal_state/tests/compose.json ]]; then
        test_owner=$(helper test-owner "$rehearsal_state/tests/compose.json")
        helper check-owner quakestrike-data-ingestion-test "$test_owner"
    fi
    confirm 'Remove the recorded disposable rehearsal containers, networks, volumes, and files?' CLEANUP
    [[ -z $test_owner ]] || helper cleanup quakestrike-data-ingestion-test "$test_owner"
    helper cleanup quakestrike-restore-test "$owner"
    # The target is a fixed root-owned directory, never a caller-supplied path.
    rm -rf -- /var/lib/quakestrike-restore-test
    notice 'Disposable rehearsal removed. Production was not changed.'
    exit 0
fi
[[ -n $backup_dir ]] || { usage >&2; fail '--backup-dir is required.'; }
[[ ! -L $backup_dir ]] || fail 'The package path cannot be a symbolic link.'
backup_dir=$(realpath -e -- "$backup_dir")
notice 'Checking package checksums and archive paths.'
helper verify "$backup_dir"
helper architecture "$backup_dir"
helper image-conflicts "$backup_dir"
postgres_image=$(helper image "$backup_dir/compose.json" postgres)
if (( rehearsal )); then
    transfer_project=quakestrike-restore-test
    [[ ! -e $rehearsal_state && ! -L $rehearsal_state ]] || fail 'A previous rehearsal exists. Inspect it, then use --cleanup-rehearsal.'
    project_empty "$transfer_project"
    transfer_repo=$rehearsal_state/repository
else
    live_prerequisites
    helper fresh-host
    [[ -f /home/ubuntu/.ssh/known_hosts ]] || fail 'Verify GitHub SSH access as ubuntu before restoring.'
    ssh-keygen -F github.com -f /home/ubuntu/.ssh/known_hosts >/dev/null || fail 'Verify GitHub host keys in ubuntu known_hosts first.'
    [[ ! -e /home/ubuntu/.ssh/quakestrike_repository && ! -e /home/ubuntu/.ssh/quakestrike_repository.pub ]] \
        || fail 'Reserve the quakestrike_repository SSH key path for this installation.'
fi
helper empty-project quakestrike-data-ingestion-test
helper space "$(dirname -- "$transfer_repo")" "$(helper get "$backup_dir" required_bytes)"
notice 'Package, architecture, disk space, and destination checks passed.'
(( check == 0 )) || exit 0
lock_transfer
# Refuse resources created between the initial check and lock acquisition.
if (( rehearsal )); then project_empty "$transfer_project"; else helper fresh-host; fi
if (( rehearsal )); then
    confirm 'Restore private data into a separate Docker project? Cloudflare and providers stay excluded.' REHEARSE
    install -d -m 700 "$rehearsal_state"
    owner=$(helper uuid)
    printf '%s\n' "$owner" > "$rehearsal_state/owner"
    state=$rehearsal_state
else
    repository=$(prompt 'GitHub repository' ochlzo/quakestrikeph)
    [[ $repository =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail 'Use OWNER/REPOSITORY.'
    machine=$(tailscale status --json | helper tailscale-name)
    destination=$(prompt 'SSH destination for future GitHub deployments' "ubuntu@${machine%%.*}")
    [[ $destination == ubuntu@"$machine" || $destination == ubuntu@"${machine%%.*}" ]] || fail 'Use ubuntu and the Tailscale name of this server.'
    as_operator gh repo view "$repository" --json nameWithOwner >/dev/null
    confirm 'Install the saved system on this fresh server, update GitHub, and keep alert delivery disabled?' RESTORE
    as_operator gh variable set DEPLOY_ENABLED --body false --repo "$repository"
    state=/home/ubuntu/.local/state/quakestrikeph/server-restore
    install -d -m 700 "$state"
    owner=$(helper uuid)
fi
transfer_config=$state/compose.json
public_started=0
restore_failed() {
    local status=$?
    if (( status != 0 )); then
        if (( public_started )); then
            compose stop -t 360 beat dispatcher data-ingestor prediction-worker cloudflared >/dev/null 2>&1 || true
        fi
        notice 'Restore failed. Public ingress remains stopped. Keep the old server stopped if replacement data has changed.' >&2
        notice "Inspect the partial installation and test reports at $state. An existing installation cannot be overwritten." >&2
    fi
}
trap restore_failed EXIT
notice 'Loading the saved Docker images.'
gzip -dc "$backup_dir/images.tar.gz" | docker image load
python3 - "$backup_dir" <<'PY'
import json, subprocess, sys
from pathlib import Path
manifest = json.loads((Path(sys.argv[1]) / 'manifest.json').read_text())
for tag, expected in manifest['images'].items():
    actual = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], text=True).strip()
    if actual != expected:
        raise SystemExit('A loaded Docker image does not match the saved image ID.')
PY
install -d -m 755 "$transfer_repo"
git clone "$backup_dir/repository.bundle" "$transfer_repo"
git -C "$transfer_repo" checkout --detach "$(helper get "$backup_dir" sha)"
tar -xzpf "$backup_dir/application.tar.gz" -C "$transfer_repo"
install -d -m 700 "$state/host-reference"
tar -xzpf "$backup_dir/host-settings.tar.gz" -C "$state/host-reference"
mode=live
(( rehearsal == 0 )) || mode=rehearsal
helper config "$backup_dir" "$transfer_repo" "$mode" "$owner" "$transfer_config"
# Persist delivery gates in .env too, so later Compose invocations remain disabled.
python3 - "$transfer_repo/.env" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
for name, value in {'ALERT_RESOLUTION_ENABLED':'false', 'ALERT_DELIVERY_ENABLED':'false',
                    'ALERT_TEST_CONSUMER_ENABLED':'false', 'ALERT_TEST_REDIS_URL':''}.items():
    text = re.sub(rf'(?m)^(?:export )?{name}=.*\n?', '', text)
    text += f'{name}={value}\n'
path.write_text(text)
path.chmod(0o600)
PY
cd "$transfer_repo"
compose create --no-build postgres redis
restore_volume postgres_data
restore_volume redis_data
compose up -d --wait --no-build --pull never postgres redis
[[ $(database_count) == "$(helper get "$backup_dir" event_count)" ]] || fail 'The restored earthquake count differs from the backup.'
compose --profile init run --rm --no-deps release-init quakestrike verify-model-release
compose --profile init run --rm --no-deps release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
compose up -d --wait --no-build --pull never backend-api bulletin traefik
notice 'Running the required automated checks against separate disposable databases.'
bash "$script_dir/server-transfer-tests.sh" "$transfer_repo" "$state/tests"
# These requests stay inside the application network, including in rehearsal.
event_id=$(compose exec -T -e "QUAKESTRIKE_TRANSFER_REHEARSAL=$rehearsal" bulletin node --input-type=module - <<'JS'
const headers = {Host: 'quakestrikeph.com', 'Content-Type': 'application/json'};
const home = await fetch('http://traefik/', {headers});
const html = await home.text();
if (!home.ok || !html.includes('/_astro/')) throw Error('Homepage failed');
const asset = html.match(/(?:src|href)="(\/_astro\/[^\"]+)"/)?.[1];
if (!asset || !(await fetch(`http://traefik${asset}`, {headers})).ok) throw Error('Asset failed');
const search = await fetch('http://traefik/api/v1/earthquakes/search', {method:'POST', headers, body:'{"limit":1}'});
if (!search.ok) throw Error('Search failed');
const body = await search.json();
if (!body.items?.length) throw Error('No restored earthquake available for the detail check');
const id = body.items[0].eventId;
if (!(await fetch(`http://traefik/api/v1/earthquakes/${id}`, {headers})).ok) throw Error('Detail failed');
if (process.env.QUAKESTRIKE_TRANSFER_REHEARSAL === '1' &&
    !(await fetch(`http://traefik/forecasts/${id}`, {headers})).ok) throw Error('Forecast page failed');
for (const host of ['quakestrikeph.qzz.io', 'unrelated.example']) {
  if ((await fetch('http://traefik/', {headers:{Host:host}})).status !== 404) throw Error('Host rejection failed');
  const api = await fetch('http://traefik/api/v1/earthquakes/search', {
    method:'POST', headers:{...headers,Host:host}, body:'{"limit":1}'});
  if (api.status !== 404) throw Error('API host rejection failed');
}
console.log(id);
JS
)
if (( rehearsal )); then
    notice "Rehearsal checks passed. No cloudflared, providers, schedulers, or production volumes were started. Reports: $state/tests"
    notice 'Keep the rehearsal for inspection, then use --cleanup-rehearsal.'
    exit 0
fi

notice 'Restoring root-only backup credentials and maintenance jobs.'
if [[ -d $state/host-reference/home/ubuntu/.local/state/quakestrikeph ]]; then
    cp -a "$state/host-reference/home/ubuntu/.local/state/quakestrikeph/." /home/ubuntu/.local/state/quakestrikeph/
    chown -R ubuntu:ubuntu /home/ubuntu/.local/state/quakestrikeph
    chmod 700 /home/ubuntu/.local/state/quakestrikeph
fi
install -d -m 700 /etc/quakestrike-backup
for file in config credentials restic-password; do
    install -o root -g root -m 600 "$state/host-reference/etc/quakestrike-backup/$file" "/etc/quakestrike-backup/$file"
done
install -d -m 755 /usr/local/libexec/quakestrike
install -m 755 database/maintenance/*.sh /usr/local/libexec/quakestrike/
install -m 644 database/maintenance/*.sql /usr/local/libexec/quakestrike/
install -m 644 database/maintenance/*.service database/maintenance/*.timer /etc/systemd/system/
systemctl daemon-reload
compose exec -T postgres sh /opt/quakestrike/provision-roles.sh create-maintenance
systemctl start quakestrike-postgres-backup.service
systemctl start quakestrike-postgres-restore-test.service

notice 'Updating GitHub access. Automatic deployment remains disabled.'
install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
if [[ -f $state/host-reference/home/ubuntu/.ssh/authorized_keys ]]; then
    cat "$state/host-reference/home/ubuntu/.ssh/authorized_keys" >> /home/ubuntu/.ssh/authorized_keys
    chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
    chmod 600 /home/ubuntu/.ssh/authorized_keys
fi
key=/home/ubuntu/.ssh/quakestrike_repository
[[ ! -e $key && ! -e $key.pub ]] || fail 'The repository key path already exists; review GitHub access manually.'
as_operator ssh-keygen -q -t ed25519 -N '' -f "$key" -C "quakestrike-repository-$owner"
as_operator gh repo deploy-key add "$key.pub" --repo "$repository" --title "server-restore-$owner"
git remote set-url origin "git@github.com:$repository.git"
git config core.sshCommand "ssh -i $key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
# Keep the original numeric owners of model and bootstrap files for the worker UID.
find "$transfer_repo" \( -path "$transfer_repo/model-artifacts" -o -path "$transfer_repo/bootstrap-snapshots" \) \
    -prune -o -exec chown ubuntu:ubuntu {} +
as_operator git -C "$transfer_repo" fetch origin
host=${destination#*@}
as_operator gh variable set VPS_TAILSCALE_HOST --body "$host" --repo "$repository"
as_operator gh variable set VPS_DEPLOY_USER --body ubuntu --repo "$repository"
printf '%s %s\n' "$host" "$(cut -d ' ' -f 1-2 /etc/ssh/ssh_host_ed25519_key.pub)" \
    | as_operator gh secret set DEPLOY_KNOWN_HOSTS --repo "$repository"

confirm 'Confirm the old cloudflared is stopped and provider IP restrictions are updated. Start public traffic?' CONNECT
public_started=1
compose up -d --wait --no-build --pull never cloudflared
curl --fail --silent --show-error --retry 5 --retry-all-errors https://quakestrikeph.com/ >/dev/null
curl --fail --silent --show-error -H 'Content-Type: application/json' --data '{"limit":1}' https://quakestrikeph.com/api/v1/earthquakes/search >/dev/null
curl --fail --silent --show-error "https://quakestrikeph.com/api/v1/earthquakes/$event_id" >/dev/null
curl --fail --silent --show-error "https://quakestrikeph.com/forecasts/$event_id" >/dev/null
compose up -d --wait --no-build --pull never data-ingestor dispatcher
prediction_count=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["running"].get("prediction-worker",0))' "$backup_dir/manifest.json")
if (( prediction_count > 0 )); then
    compose up -d --wait --no-build --pull never --scale "prediction-worker=$prediction_count" prediction-worker
fi
if [[ $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["running"].get("beat",0))' "$backup_dir/manifest.json") != 0 ]]; then
    compose up -d --wait --no-build --pull never beat
    for service in beat dispatcher data-ingestor; do
        id=$(compose ps -q "$service")
        [[ $(docker inspect --format '{{.State.Health.Status}}' "$id") == healthy ]] || fail "$service is unhealthy after enabling Beat."
    done
fi
systemctl enable --now quakestrike-postgres-backup.timer quakestrike-postgres-restore-test.timer quakestrike-ingestion-checkpoint-retention.timer
private_tree "$state"
notice "Restoration and required checks passed. Reports: $state/tests"
notice 'Alert delivery and GitHub deployment remain disabled. Verify sign-in and ingestion before retiring the old server.'
