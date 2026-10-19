# CI and VPS deployment

Use this guide to inspect CI, deploy a tested release, or initialize the VPS.
CI means the automated checks in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

| Task | Section |
| --- | --- |
| See what runs automatically | [CI checks](#ci-checks) |
| Deploy a tested main commit manually | [Deploy a tested release](#deploy-a-tested-release) |
| Understand downtime and recovery | [Routine release sequence](#routine-release-sequence) |
| Prepare a new server | [Initialize the VPS once](#initialize-the-vps-once) |
| Configure deployment access | [GitHub access](#give-github-access-to-the-vps) |
| Check Bulletin routing and image cleanup | [Bulletin hosting](#bulletin-hosting) |
| Complete an unfinished domain cutover | [Public domain transition](#public-domain-transition) |

## CI checks

Pull requests to `main` and pushes to `main` run these jobs:

| Job | What it checks |
| --- | --- |
| `workers` | Python unit tests, Ruff, shell syntax, local Compose isolation, worker/Backend integration, and the private testing workflow. |
| `backend-unit` | Locked Backend install, TypeScript build, and unit tests. |
| `bulletin` | Production Docker build, homepage/assets, page/API routing, and rejection of unrelated hosts. |
| `alert-testing-package` | Private Compose isolation, image builds, and packaged smoke checks without provider credentials. |

Open the repository's **Actions** page and select the run for your commit.
Check each failed job's first failing step. For local commands, follow [contributor checks](../../CONTRIBUTING.md#local-setup-for-contributor-checks).

The deploy job waits for all four jobs. It runs only for a successful push to `main` with `DEPLOY_ENABLED=true`.
A pull request run does not deploy. The workflow uses the tested main SHA for application images.
Ordinary deployment updates workers, Backend, Bulletin, and already-running alert services.
Routine deployment stops pgAdmin and private alert-testing services, including their separate Redis.
After cleanup passes, deployment and rollback do not restart optional tools; start them explicitly when needed.
Deployment also disables the Backend's optional test Redis connection without changing its saved `.env` setting.
The manual private-testing rollout can recreate the Backend with that saved setting when needed.
Deployment first stops the private control service so operators cannot start or submit another test during the cleanup check.
Before stopping consumers, it requires no session or a closed/expired session with completed cleanup.
If cleanup cannot be verified, deployment restores the previously running control service and aborts before public application downtime.
After consumers stop, deployment rechecks cleanup and stops private Redis last.
If this final check fails, Redis remains running and private controls remain stopped; resolve the dependency failure before retrying.
Private alert-testing services use their [separate manual rollout](alert-testing.md#build-and-activate-after-separate-authorization).
The Operations Console deployment remains planned.

## Deploy a tested release

**Environment:** Bash on the VPS, checkout `/srv/quakestrikeph`.
**Prerequisites:** Complete first-time setup and confirm the selected main commit passed required CI checks.
End any private test session before changing the application or schema.

For routine releases, push the reviewed change through the team's normal main workflow.
If automatic deployment is enabled, inspect the resulting deploy job.

For an approved manual release, replace the placeholder with the full tested main SHA:

```bash
cd /srv/quakestrikeph
bash infrastructure/scripts/deploy-workers.sh REPLACE_WITH_TESTED_40_CHARACTER_MAIN_SHA
```

Stop after a failed release. Read the deploy log before retrying.
A retry requires the documented running-service preconditions.

**Expected result:** Service health and public checks pass before the script saves release tags.
The script rejects an older release when a newer main commit exists.

## Routine release sequence

The deployment script performs these steps. Run the script rather than reproducing individual release actions manually.

1. Verify the clean checkout, current main SHA, and retained previous images.
2. Stop private controls before verifying private-test cleanup.
3. Stop optional tools.
4. Build application images before downtime.
5. Complete an encrypted backup and isolated restore test.
6. Check main again to reject a stale release.
7. Stop Beat, Dispatcher, consumers, reconciliation, and Backend.
8. Acquire the host maintenance lock.
9. Run reviewed migrations through the `release-init` migration login.
10. Apply restricted grants from the reviewed provisioning script through stdin.
11. Check migrations, model release, bootstrap, PostgreSQL, and Redis.
12. Restore Backend before consumers and already-enabled alerts.
13. Start reconciliation before Alert Worker.
14. Resume Dispatcher and the previously enabled Beat schedule.
15. Check Bulletin, Traefik, and public endpoints.
16. Save release tags only after verification succeeds.

The script preserves prediction replica count and previous service enablement.
This preservation excludes pgAdmin and private alert-testing services.
An enabled Beat uses `unless-stopped` after an unexpected exit or Docker daemon restart.
Docker restarts do not rerun the enable helper; verify consumer health after recovery.
An explicitly stopped Beat stays stopped until enabled again.
The maintenance lock prevents overlap with backup, restore, and retention jobs.
The deployment account needs noninteractive `sudo` for installed backup services and the database maintenance job.
Secrets, model registration, bootstrap, legacy retirement, and first alert activation remain explicit operator actions.

### Worker health-check cost

Release workers run health checks every 30 seconds through `python -m quakestrike.operator_runtime`.
The command avoids unrelated operator commands and loads bootstrap/model adapters only when the selected check needs them.
Worker images compile application Python files during build to avoid repeated source compilation during checks.
All existing database, migration, queue-consumption, process, and model checks remain in place.
Three failed checks mark a worker unhealthy after approximately 90 seconds plus probe execution time.
Startup grace periods and probe timeouts still apply.

### Failure and rollback

| Database revision after failure | Required recovery |
| --- | --- |
| Verified unchanged | The script can restore previous application images and checkout. |
| Changed or unreadable | Keep processing and Backend stopped; retain the target checkout and repair forward. |

Deployment never automatically restores or downgrades the live database.
A retry requires the documented running-service preconditions.
Successful releases save Worker, Backend, and Bulletin tags atomically in private `.env`.
Protected environment backups remain under the deployment user's `.local/state/quakestrikeph/env-backups`.
Previous compatible images remain available.

### Repository layout reference

Database tools live under `database/`. Worker images use the repository root as build context.
Routine deployment streams grants into PostgreSQL without recreating the PostgreSQL container.
Installed maintenance tools keep their existing host paths.

When adopting a changed database bind mount, plan a database restart with producers and consumers stopped.
Follow [the local runtime sequence](local-runtime.md#4-start-postgresql-and-redis) and preserve the named volume.

## Initialize the VPS once

On a 4 GB VPS, complete [the 1 GB swap setup](#configure-a-1-gb-swap-reserve) before building application images.

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

Initialize the server in this order:

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
docker build --label "org.opencontainers.image.revision=$sha" -t "quakestrike-workers:$sha" -f workers/Dockerfile .
docker build --build-arg "BASE_IMAGE_TAG=$sha" --label "org.opencontainers.image.revision=$sha" -t "quakestrike-prediction:$sha" -f workers/prediction-worker/Dockerfile .
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
raw or enriched source snapshot with source IDs, URLs, retrieval metadata, and validated coverage. A cleaned CSV is insufficient. The generated readiness manifest
belongs to this VPS database and cannot be copied from another machine.

These are operator steps because an empty database cannot become ready by
starting containers. A database backup and restore plan is also needed before
using this as a production service. See [PostgreSQL backups](postgres-backups.md)
for the B2 setup and isolated restore test. Routine deployment applies reviewed migrations and approved grants as an explicit release job. It never reimports history or changes the model registry. Checkpoint cleanup retains the worker's `DELETE` grant on `ingestion_run_inputs`. See [checkpoint retention](ingestion-checkpoint-retention.md).

The deploy script requires PostgreSQL, Redis, Dispatcher, and Data Ingestor to
already be running. It updates Prediction Worker and Beat only if they were
running before the release. It builds images tagged with the tested commit,
backs up and tests a restore, pauses application processing, and applies reviewed
migrations and grants. It checks readiness and restores services in the routine
release order above. Recovery depends on whether the database revision changed.
Check container health and logs after any failed run.

### Configure a 1 GB swap reserve

**Environment:** Bash on the Ubuntu VPS host, outside Docker.
**Prerequisites:** You have `sudo` access, an ext4 root filesystem, and at least 2 GB of free disk space.
The procedure allocates 1 GiB (1,024 MiB), described here as the 1 GB swap reserve.
Other filesystems can require different swap-file preparation; consult the [Linux swap-file requirements](https://man7.org/linux/man-pages/man8/swapon.8.html).

Swap gives Linux slower disk space for memory overflow during brief RAM spikes.
Swap does not increase physical RAM or replace sufficient RAM for normal operation.
Docker containers can use host swap within their memory and swap limits.
These host settings survive deployments; CI does not configure swap.

Run each step separately. Stop if a command fails.

1. Inspect existing swap and the root filesystem.

   ```bash
   sudo swapon --show
   free -h
   findmnt -no FSTYPE /
   df -h /
   ```

   Confirm the filesystem is `ext4` and disk space meets the prerequisite.
   If a suitable swap reserve already exists, skip creation and use the verification steps below.
   If `/swapfile` already exists, inspect that file before continuing; the creation command refuses to overwrite it.

2. Create the private swap file.

   ```bash
   sudo sh -eu -c 'umask 077; dd if=/dev/zero of=/swapfile bs=1M count=1024 conv=excl status=progress'
   sudo chmod 600 /swapfile
   ```

   `dd` writes allocated blocks; `conv=excl` prevents overwriting an existing file.
   Permissions `600` restrict reading and writing to the file owner, root.

3. Format the file for swap.

   ```bash
   sudo mkswap /swapfile
   ```

4. Enable the swap file.

   ```bash
   sudo swapon /swapfile
   ```

5. Back up the boot configuration.

   ```bash
   sudo cp -a /etc/fstab "/etc/fstab.before-swap.$(date +%Y%m%d%H%M%S)"
   ```

6. Register swap for subsequent boots.

   ```bash
   if ! sudo grep -qE '^[[:space:]]*/swapfile[[:space:]]' /etc/fstab; then
       printf '/swapfile none swap sw 0 0\n' | sudo tee -a /etc/fstab
   fi
   sudo findmnt --verify --verbose
   sudo systemctl daemon-reload
   ```

   The guard prevents adding a duplicate `/swapfile` entry.
   Resolve any configuration errors reported by `findmnt` before a reboot.

7. Configure a low preference for disk swap.

   ```bash
   printf 'vm.swappiness = 10\n' | sudo tee /etc/sysctl.d/99-quakestrike-swap.conf
   sudo sysctl -p /etc/sysctl.d/99-quakestrike-swap.conf
   ```

   Start with `10` for this disk-based reserve and adjust only after measuring the workload.
   Swappiness controls relative memory-reclaim costs; `10` does not mean Linux waits for 90% RAM usage.
   See the [kernel documentation for swappiness](https://docs.kernel.org/admin-guide/sysctl/vm.html#swappiness).

8. Verify the active swap configuration.

   ```bash
   sudo swapon --show --bytes
   free -h
   sudo stat -c '%a %U:%G %n' /swapfile
   sysctl vm.swappiness
   ```

   **Expected results:** `/swapfile` appears as an active file with approximately 1 GiB of usable swap.
   `free -h` reports approximately `1.0Gi` total swap if no other swap exists.
   Permissions read `600 root:root /swapfile`, and swappiness reads `vm.swappiness = 10`.
   Zero used swap is normal when RAM is sufficient; usage need not increase to confirm activation.

9. Observe paging during normal operation.

   ```bash
   vmstat 1 5
   ```

   Ignore the first sample, which summarizes activity since boot.
   The `si` and `so` columns show swap reads and writes per second.
   Sustained paging with slow responses means the workload needs investigation or more RAM.

After the next planned reboot, repeat step 8 to verify swap activation and the persistent swappiness setting.

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
watch VPS disk usage; successful deployments now perform the bounded cleanup above.

## Bulletin hosting

Complete [Backend setup](backend-api.md#first-vps-setup) before the first Bulletin rollout.
Cloudflare Tunnel sends `quakestrikeph.com` to `http://traefik:80` and preserves the public Host header.

| Request | Destination | Traefik priority |
| --- | --- | --- |
| `/api/v1/` | Backend port 3000. | 100 |
| Other paths | Bulletin port 4321. | 10 |
| Unrelated or retired host | Rejected. | No matching route. |

No service publishes a public host port. Bulletin joins only `backend-edge` and cannot access PostgreSQL or Redis directly.
The production Dockerfile provides a non-root Node process and root-page health check.
Compose sets bounded logs, restart policy, and memory limits.

### First Bulletin rollout

1. Keep `DEPLOY_ENABLED=false`.
2. Wait for the reviewed main commit's CI checks to pass.
3. Run `bash infrastructure/scripts/deploy-workers.sh <tested-main-sha>` on the VPS.
4. Verify the homepage, emitted assets, map, earthquake list, and forecast reads over HTTPS.
5. If those checks pass, set `DEPLOY_ENABLED=true` in GitHub.

The first rollout requires no previous Bulletin tag. Later rollouts retain a compatible previous tagged image for recovery.
A failed first rollout removes Bulletin and restores API-only routing when the database revision is unchanged.
A saved domain-cutover override preserves verified new-host-only routing during that recovery.

### Release behavior

The script restores the full Git checkout and builds Bulletin before replacing services.
It uses `compose.yml`, `compose.backend.yml`, `compose.edge.yml`, and `compose.bulletin.yml`.
It recreates Traefik after Bulletin becomes healthy so the mounted route file matches the checkout.
It checks the public homepage and earthquake API before saving `BULLETIN_IMAGE_TAG` to private `.env`.

If the database revision changes or becomes unreadable, keep processing and Backend stopped and repair forward.
Deployment never automatically restores or downgrades the live database.

### Image cleanup

After public checks pass and tags are saved, cleanup removes unused build cache and older application images.
It retains the current and previous distinct release for Worker, Prediction Worker, Backend, and Bulletin.
Repeating the same SHA does not discard the previous distinct release.
Images referenced by running or stopped containers remain protected.
Private testing images, third-party images, volumes, backups, and model files remain outside cleanup.
Future builds recreate their cache.

Cleanup reads previous tags from protected environment backups.
Missing or invalid history, or missing required rollback images, stops cleanup before deletion.
A cleanup failure produces a workflow warning; it does not undo a successful deployment.

After inspection, retry cleanup from `/srv/quakestrikeph`:

```bash
python3 infrastructure/scripts/cleanup-release-images.py .env <deployed-sha>
```

## Public domain transition

Use this section only when completing the retired-domain cutover. Routine releases use [the release procedure](#deploy-a-tested-release).

`quakestrikeph.com` is the sole public domain. The retired domain is
`quakestrikeph.qzz.io`; no compatibility route or redirect remains in the
release configuration. Keep the existing Tunnel, Traefik, Bulletin, and
Backend. Do not add public host ports, wildcard routes, or public private-tool
routes.

Set these values in the ignored VPS `.env`:

```dotenv
PUBLIC_BULLETIN_BASE_URL=https://quakestrikeph.com
ALERT_TEST_PUBLIC_BULLETIN_URL=https://quakestrikeph.com
BREVO_SENDER_EMAIL=forecast@quakestrikeph.com
ALERT_TEST_BREVO_SENDER_EMAIL=forecast@quakestrikeph.com
```

Set `CLERK_AUTHORIZED_PARTIES=https://quakestrikeph.com` on the VPS.
Preserve the existing production Clerk keys, Brevo credentials,
callback token, image tags, and delivery enablement. The Bulletin build embeds
the publishable key. Ordinary and private test delivery remain separately gated.
The branded Brevo subdomain `alerts.quakestrikeph.com` is provider infrastructure;
it is not the sender address or a Bulletin API target. Webhook setup remains
deferred; this release does not establish email delivery verification.

Recreate already-running Prediction Worker replicas to apply the public URL.
Between private test sessions, recreate the already-running private control and
consumer with the same private URL. Preserve their image tags and Redis data.
Frozen alert messages and prepared previews retain their original URLs.
Links containing the retired domain stop working after retirement.

If the live routes accept only the old hostname, use a maintenance window for
the staged cutover. Keep `DEPLOY_ENABLED=false` until the cutover is verified.
New-only routing briefly rejects rewritten requests until the Host override is
cleared. Never restore the retired hostname to recover from a failed release.

1. Fetch the reviewed PR revision on the VPS.
2. Save its new-host-only route file outside the tracked checkout.

Run from `/srv/quakestrikeph` with the reviewed 40-character SHA:

```bash
reviewed_sha=REPLACE_WITH_REVIEWED_40_CHARACTER_SHA
[[ $reviewed_sha =~ ^[0-9a-f]{40}$ ]] || exit 2
mkdir -p .local/domain-cutover
git show "$reviewed_sha:infrastructure/traefik/backend.yml" > .local/domain-cutover/backend.yml
git show "$reviewed_sha:infrastructure/compose.domain-cutover.yml" > .local/domain-cutover/compose.yml
```

The `.local/` directory is ignored by Git. Its files survive checkout rollback
and keep the deployment's clean-checkout check valid. The Compose override
replaces the route mount and sets Bulletin's server API target to
`http://backend-api:3000`. Previous Bulletin images otherwise fetch forecasts
from the retired hostname. The override adds no public port or legacy route.

3. Recreate Bulletin and Traefik with the saved override:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml -f infrastructure/compose.bulletin.yml -f .local/domain-cutover/compose.yml up -d --wait --no-deps --force-recreate bulletin traefik
```

4. Verify the new hostname directly through Traefik for pages and API requests.
5. Verify the retired hostname receives HTTP 404 directly through Traefik.
6. Clear the old-domain HTTP Host Header override on the new-domain Tunnel route.
7. Verify the new domain's public HTTPS homepage, emitted asset, API, and forecast page.
8. Remove the retired hostname's Tunnel route and DNS records.
9. Remove old-domain Google OAuth origins and redirect URIs from the existing OAuth client.
10. Deploy the reviewed release using its updated deployment script after main CI passes.

The deployment script loads `.local/domain-cutover/compose.yml` when present.
An unchanged-schema rollback restores previous application images and checkout
while retaining the saved new-host-only route mount and internal server API target. The same override covers
a failed first Bulletin rollout's API-only recovery. Leave both cutover files
in place after failure, including across host or container restarts. If the
schema changes, keep processing stopped and repair forward.

After a successful release, retire the override and recreate Bulletin and
Traefik from the new checkout. Keep the saved files until public checks succeed:

```bash
mv .local/domain-cutover/compose.yml .local/domain-cutover/compose.saved.yml
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml -f infrastructure/compose.bulletin.yml up -d --wait --no-deps --force-recreate bulletin traefik
```

Verify new-domain pages and API requests again. Verify the retired hostname
still receives HTTP 404 directly through Traefik. If recreation or verification
fails, rename `compose.saved.yml` back to `compose.yml` and repeat step 3.
Keep the saved files for recovery until the cutover is confirmed complete.

Retain the new domain's Clerk and Brevo DNS records. Recreate Backend after
changing its authorized origins. Do not deploy new-host-only routes while
Cloudflare still replaces the new Host header with the old hostname.
