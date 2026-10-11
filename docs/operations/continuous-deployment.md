# Worker CI and VPS deployment

The workflow in `.github/workflows/ci.yml` runs the worker integration tests,
unit tests, and Ruff checks for pull requests and pushes to `main`. After a
successful `main` run, its deploy job can connect to the VPS over Tailscale and
run `infrastructure/scripts/deploy-workers.sh`. The deploy job is disabled until
the repository variable `DEPLOY_ENABLED` is set to `true`.

This deploys Python workers, the Backend, Bulletin, and already-enabled alert services. [ADR 0049](../adr/0049-automatic-full-application-deployment.md) authorizes the explicit migration and grant job. Initial [Backend setup](backend-api.md) and alert activation remain manual.
Bulletin CI builds its Dockerfile (including Astro checks and production build)
and checks the production homepage and an emitted asset. A disposable Traefik
container also checks page/API routing and unrelated-host rejection. Deployment waits for
all three checks and uses the tested main SHA for all application images.
The Operations Console deployment remains planned.

## Bulletin hosting

Follow [ADR 0041](../adr/0041-vps-bulletin-deployment.md). The existing Cloudflare
Tunnel hostname `quakestrikeph.qzz.io` continues pointing at `http://traefik:80`.
Traefik sends `/api/v1/` to Backend port 3000 with priority 100 and other paths
to Bulletin port 4321 with priority 10. No public host port is added.

Complete the existing Backend setup first. The deploy script restores the full
Git checkout, builds Bulletin before replacing services, and starts it using
`compose.yml`, `compose.backend.yml`, `compose.edge.yml`, and `compose.bulletin.yml`. The script
sets `BULLETIN_IMAGE_TAG` to the tested SHA and saves it in the ignored VPS
`.env` only after the public checks pass. The first rollout requires no prior
Bulletin tag. Subsequent releases retain the previous tagged image for rollback.

Bulletin joins only `backend-edge`; it has no PostgreSQL or Redis access.
Its Dockerfile supplies a root-page health check, production Node command,
and a non-root user. Compose adds bounded logs, restart policy, and memory limit.
Traefik is recreated after Bulletin is healthy so its mounted route file uses
the current checkout. The script checks the public homepage and earthquake API.
When the database revision remains unchanged, a failed rollout restores previous
application images and routing. A failed first rollout also removes Bulletin
and restores the API-only configuration.
Do not prune prior images until the release is verified.

For the first release, keep `DEPLOY_ENABLED=false`, wait for green main checks,
and run `bash infrastructure/scripts/deploy-workers.sh <tested-main-sha>` on
the VPS using the new script. Confirm homepage, assets, map, earthquake list,
and forecast reads over HTTPS, then set `DEPLOY_ENABLED=true` in GitHub.
Future successful main runs deploy the full application. A failed rollout restores previous images only when the database revision remains unchanged. A changed or unreadable schema leaves processing and Backend stopped for repair forward. Deployment never restores or downgrades the live database automatically.

## Routine release sequence

Deployment verifies the clean checkout, previous images, and current main SHA. It builds images before downtime. The installed encrypted backup and isolated restore services must both succeed. A second main check rejects stale releases before stopping services.

Deployment stops Beat, Dispatcher, consumers, reconciliation, and Backend. The existing host maintenance lock serializes migration and grants with backup, restore, and retention. `release-init` uses the migration login for reviewed DDL. The reviewed checkout's provisioning script refreshes approved grants through stdin.

Readiness checks verify migration state, model release, bootstrap, PostgreSQL, and Redis. Backend starts before consumers and already-enabled alerts. Reconciliation starts before Alert Worker; Dispatcher resumes afterward. Prediction replica count and previous Beat enablement are preserved. Bulletin, Traefik, and public endpoint checks complete the rollout.

The deployment account needs noninteractive `sudo` for the installed backup services and maintenance-locked database job. Initial secret provisioning, alert activation, model registration, bootstrap, and legacy retirement remain operator actions. Only previously running alert services resume. The workflow never changes alert gates.

Successful releases save Worker, Backend, and Bulletin tags atomically in private `.env`. Protected environment backups remain under the deployment user's `.local/state/quakestrikeph/env-backups`. Previous images remain available. If a changed schema prevents rollback, retain the target checkout and repair forward with publication stopped. A retry requires restoring the documented running-service preconditions.

## Initialize the VPS once

Use a non-root deployment user with access to Docker and a clean Git checkout
at `/srv/quakestrikeph`. The existing `ubuntu` account can serve this role for
the first release. Docker access grants powerful host privileges, so keep its
SSH keys restricted. The repository is private, so
give the VPS read-only Git access with a separate
[GitHub deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).
Keep `.env`, the SEIS model package, the
preserved bootstrap snapshot, and the generated readiness manifest on the VPS
outside Git. Set `.env` permissions so only the deployment user can read it.

In the VPS console, create the directory with ownership for your deployment
user, generate a repository read key, and add its `.pub` line under the GitHub
repository's **Settings > Deploy keys** without write access. Configure SSH to
use that key for this repository and clone `main` into `/srv/quakestrikeph`.
Verify GitHub's SSH host key against
[GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
before the first connection. Then run `cp .env.example .env`, `chmod 600 .env`,
and edit the production values. The VPS must be able to fetch `origin main`
without a password prompt before automatic deployment can work.

Follow the initialization order in [ADR 0025](../adr/0025-explicit-local-runtime-enablement.md):

1. Fill in the VPS `.env` with production credentials and set
   `WORKER_IMAGE_TAG` to the full checked-out Git SHA. Put the model artifacts
   and preserved source snapshot in the configured host directories.
   Percent-encode reserved characters in the passwords embedded in
   `DATABASE_URL` and `MIGRATION_DATABASE_URL`; leave the matching standalone
   database password values unchanged.
2. Build the `quakestrike-workers:<SHA>` and
   `quakestrike-prediction:<SHA>` images from that exact checkout. Start
   PostgreSQL and Redis with Compose.
3. Provision the separate database roles. Run migrations, register and verify
   the model release, import the historical snapshot, and run `startup-check`.
   Confirm it prints `"ready": true`.
4. Start Dispatcher and Data Ingestor, wait for both to become healthy, then
   start Prediction Worker. Enable Beat only after the consumers are healthy.

Data Ingestor joins a separate outbound network to fetch PHIVOLCS over HTTPS.
PostgreSQL and Redis stay on the internal data network without host ports.

On the Linux VPS, run the equivalent Compose commands from
`/srv/quakestrikeph` after preparing `.env`, the reviewed model bundle, and
`bootstrap-snapshots/input.json`:

```bash
cd /srv/quakestrikeph
set -euo pipefail
sha=$(git rev-parse HEAD)
test -z "$(git status --porcelain --untracked-files=all)"
grep -qx "WORKER_IMAGE_TAG=$sha" .env
if docker image inspect "quakestrike-workers:$sha" >/dev/null 2>&1 ||
   docker image inspect "quakestrike-prediction:$sha" >/dev/null 2>&1; then
    echo 'A SHA-tagged image already exists; inspect it rather than overwriting it.' >&2
    exit 1
fi
export WORKER_IMAGE_TAG=$sha
docker build --label "org.opencontainers.image.revision=$sha" -t "quakestrike-workers:$sha" -f workers/Dockerfile workers
docker build --build-arg "BASE_IMAGE_TAG=$sha" --label "org.opencontainers.image.revision=$sha" -t "quakestrike-prediction:$sha" -f workers/prediction-worker/Dockerfile workers
compose=(docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml)
"${compose[@]}" up -d --wait postgres redis
"${compose[@]}" exec -T postgres sh /opt/quakestrike/provision-roles.sh create
"${compose[@]}" --profile init run --rm release-init quakestrike migrate
"${compose[@]}" exec -T postgres sh /opt/quakestrike/provision-roles.sh grant-worker
"${compose[@]}" --profile init run --rm release-init quakestrike register-model-release
"${compose[@]}" --profile init run --rm release-init quakestrike verify-model-release
"${compose[@]}" --profile init run --rm release-init quakestrike bootstrap --snapshot /app/bootstrap-snapshots/input.json --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
"${compose[@]}" --profile init run --rm release-init quakestrike startup-check --run-manifest /app/bootstrap-snapshots/bootstrap-readiness.json
"${compose[@]}" up -d --wait dispatcher
"${compose[@]}" up -d --wait data-ingestor
"${compose[@]}" --profile prediction up -d --wait prediction-worker
bash infrastructure/scripts/enable-beat.sh
```

Stop at any failed command and inspect its error. Confirm Dispatcher and Data
Ingestor remain healthy after enabling Beat. The Beat helper checks consumer
health before and after startup, and stops Beat if a consumer becomes unhealthy.
The snapshot must be a preserved
raw or enriched source snapshot with provenance, as described in
[ADR 0018](../adr/0018-bootstrap-source-enrichment.md); a cleaned CSV is insufficient. The generated readiness manifest
belongs to this VPS database and cannot be copied from another machine.

These are operator steps because an empty database cannot become ready by
starting containers. A database backup and restore plan is also needed before
using this as a production service. See [PostgreSQL backups](postgres-backups.md)
for the B2 setup and isolated restore test. Routine deployment applies reviewed migrations and approved grants as an explicit release job. It never reimports history or changes the model registry. The scheduled checkpoint cleanup in ADR 0034 retains the worker's `DELETE` grant on `ingestion_run_inputs`.

The deploy script requires PostgreSQL, Redis, Dispatcher, and Data Ingestor to
already be running. It updates Prediction Worker and Beat only if they were
running before the release. It builds images tagged with the tested commit,
backs up and tests a restore, pauses application processing, and applies reviewed
migrations and grants. It checks readiness and restores services in the routine
release order above. Recovery depends on whether the database revision changed.
Check container health and logs after any failed run.

## Give GitHub access to the VPS

The existing personal public key is already in `ubuntu`'s
`~/.ssh/authorized_keys`; interactive login works with
`ssh ubuntu@quakestrike-vps`. If a noninteractive local command needs that
passphrase-protected key, load it into the Windows SSH agent first with
`ssh-add "$env:USERPROFILE\.ssh\quakestrike_vps"` and enter the passphrase
locally. Never put that passphrase or personal private key in GitHub or a chat.

Create a separate SSH key for GitHub deployment. On Windows, run
`ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\quakestrike_github_deploy" -C "quakestrike-github-deploy"`
and leave its passphrase empty so the noninteractive job can use it. Add its
`.pub` line to the same VPS `authorized_keys` file. Put the contents of the
private key file in the GitHub `DEPLOY_SSH_PRIVATE_KEY` repository secret.
Keep the private file readable only by your Windows account. This key can be
revoked by removing its public line from `authorized_keys`.

For `DEPLOY_KNOWN_HOSTS`, copy the VPS's `ssh-ed25519` host-key line into the
secret. Verify its fingerprint against
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` in the VPS console before
trusting it. The hostname in that line must match `VPS_TAILSCALE_HOST`.

Set these GitHub repository secrets. The workflow runs deployment only for a
successful push to `main`. This private repository's current GitHub plan
returns an upgrade requirement for branch protection, so restrict who can
push to `main`. Add required reviews and worker checks if branch protection
becomes available.

| Name | Value |
| --- | --- |
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth client ID with `auth_keys` write scope for `tag:github-deploy`. |
| `TS_OAUTH_SECRET` | Secret for that OAuth client. |
| `DEPLOY_SSH_PRIVATE_KEY` | Private half of a dedicated SSH key whose public half is in the VPS deployment user's `authorized_keys`. |
| `DEPLOY_KNOWN_HOSTS` | Verified SSH host-key line for the VPS Tailscale name. |

Set these GitHub repository variables:

| Name | Value |
| --- | --- |
| `VPS_TAILSCALE_HOST` | The VPS MagicDNS name or Tailscale IP used for SSH. |
| `VPS_DEPLOY_USER` | The dedicated VPS deployment username. |
| `DEPLOY_ENABLED` | `true` only after the initial runtime is ready and a manual SSH login works. |

In the tailnet policy, permit `tag:github-deploy` to reach only the VPS SSH
port. A broad `*` to `*` grant also permits the CI node to reach every device;
replace any such grant with narrower rules while preserving your own access.
Create the tag in **Access controls > Definitions > Tags > Create tag**.
Enter `github-deploy` as the name, without the `tag:` prefix, and select a tag
owner. In **Settings > Trust credentials**, create an OAuth client with the
`auth_keys` write scope limited to `tag:github-deploy`, then put its client ID
and secret in the two `TS_OAUTH_*` GitHub repository secrets. The tag identifies
the temporary GitHub runner; do not apply it to your personal computer or VPS.
The Tailscale action creates a temporary CI node for each run. Verify the
VPS SSH host key on the server before copying its `known_hosts` line into
GitHub; do not trust an unverified `ssh-keyscan` result. See the
[Tailscale GitHub Action](https://github.com/tailscale/github-action) and
[GitHub deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
for the current setup screens.

After the first green CI run and manual VPS initialization, set
`DEPLOY_ENABLED=true`. The next push to `main` will run tests first and then
deploy that exact SHA. A newer `main` commit makes an older pending deploy
exit without replacing it. Keep the previous tagged images for rollback and
watch VPS disk usage; this workflow does not prune images.
