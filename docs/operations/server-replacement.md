# Back up and replace the server

Use `backup-server.sh` to create one recovery folder.
Use its packaged `restore-server.sh` to install the saved system on a fresh Ubuntu server.
Assume no usable backup exists until the package and restoration checks pass.

The scripts preserve the application release, Docker images, PostgreSQL data, Redis data, model files, and bootstrap evidence.
They also preserve production settings, backup credentials, authorized SSH public keys, and deployment history.
They do not delete the old server.

## Prepare the old server

1. Deploy a tested release that includes these recovery scripts.
2. Keep the source checkout clean at `/srv/quakestrikeph`.
3. Install Bash, Python 3.11+, Git, Docker Engine, Compose v2, Buildx, Restic, GitHub CLI, Tailscale, and UFW.
4. Authenticate GitHub CLI as `ubuntu` using `gh auth login`.
5. Set the repository variable `DEPLOY_ENABLED=false`.
6. Wait for running GitHub workflows to finish.
7. End any private test session and confirm cleanup completes.
8. Arrange a maintenance window before the old server expires.

The scripts use Ubuntu's `ubuntu` account with sudo access.
Application image tags must match the checked-out release; an incomplete or mixed release blocks backup.
Python performs structured file checks; Bash coordinates system commands.
No Python packages or host Node installation are required for the transfer scripts.
Automated checks install locked application dependencies inside Docker images.
The verification image also installs Git, Docker CLI, and PowerShell for the existing operator tests.
Those builds require internet access and additional disk space.

## Create the recovery package

**Old VPS — Bash, from `/srv/quakestrikeph`:**

```bash
sudo bash infrastructure/scripts/backup-server.sh --check
```

**Expected result:** The script reports that preflight checks passed.
The check creates no package and changes no services or provider settings.

If preflight passes, create the final package:

```bash
sudo bash infrastructure/scripts/backup-server.sh --output /home/ubuntu/quakestrike-transfer
```

Type `BACKUP` at the terminal prompt to approve production shutdown.
The script exports images before downtime, then stops maintenance, private tools, scheduled work, consumers, web services, PostgreSQL, and Redis.
It copies database volumes only after clean shutdown.
It leaves the old system and maintenance timers stopped.

**Expected result:** The script reports `Backup verified` and names the package folder.
If a command fails, inspect the error and partial files. The script does not restart production automatically.
If shutdown already occurred, recover the old services deliberately before retrying the backup.
An existing output folder is refused, including an incomplete earlier package.
Keep partial evidence until you understand the failure; use another new output name for a corrected attempt.

| Package contents | Purpose |
| --- | --- |
| `repository.bundle`, `manifest.json`, `compose.json` | Git history, release identity, image IDs, service inventory, counts, and resolved deployment settings. |
| `images.tar.gz` | Existing Docker images, avoiding application rebuilds for restoration. |
| `postgres_data.tar.gz`, `redis_data.tar.gz` | Physical copies of the stopped production volumes. |
| `pgadmin_data.tar.gz`, if present | Optional saved pgAdmin data; initial restoration leaves pgAdmin disabled. |
| `application.tar.gz` | `.env`, model artifacts, bootstrap files, optional datasets, and ignored `.local` settings. |
| `host-settings.tar.gz` | Backup credentials, SSH/firewall reference files, and deployment history. |
| `server-settings.txt` | Private routing, firewall rules, and installed maintenance timers for reference. |
| `restore-server.sh` and support files | The installer and its verification tools. |
| `SHA256SUMS` | Checksums for every package file. |

The host archive includes all three `/etc/quakestrike-backup/` files: `config`, `credentials`, and `restic-password`.
Without the Restic password, existing B2 snapshots cannot be decrypted.
The package contains readable secrets and personal data; checksums do not encrypt them or prove who created them.
Use only your trusted package.

The package belongs to `ubuntu:ubuntu`.
Directories use `700`, data files use `600`, and the restore entry point uses `700`.
Root and users with unrestricted sudo or Docker access can still read the package.

## Download and retain the package

**Local — PowerShell:**

```powershell
scp -r ubuntu@quakestrike-vps:/home/ubuntu/quakestrike-transfer "$env:USERPROFILE\"
```

1. Keep a second copy in encrypted external storage or another protected storage service.
2. Keep both copies outside Git and shared folders.
3. Keep the old server stopped after the final backup.

If you resume the old system, create another final backup before transferring.
You can retain the package while waiting to purchase the replacement, but the application remains unavailable during that interval.

## Prepare the new server

1. Provision fresh **x86_64 Ubuntu**, matching the inspected deployment.
2. Configure the `ubuntu` account and recovery-console access.
3. Install Tailscale and enroll the new server in the existing tailnet.
4. Assign a temporary name, such as `quakestrike-vps-new`, while the old device still exists.
5. Configure key-only OpenSSH access and verify a second connection from your computer.
6. Install the transfer prerequisites listed above.
7. Give `ubuntu` access to the local Docker daemon.
8. Authenticate `gh` as `ubuntu` with access to repository variables, secrets, and deploy keys.
9. Verify GitHub's SSH host key before adding `github.com` to `ubuntu`'s `known_hosts`.
10. Configure the provider firewall and UFW to permit SSH through Tailscale.

Follow [Docker's Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/) and [GitHub SSH fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints).
Your external `quakestrike-vps-tailscale-ssh-access.md` guide remains useful for Tailscale and OpenSSH enrollment.
Do not copy Tailscale state or SSH host private keys from the old server.
If needed, follow the [swap procedure](continuous-deployment.md#configure-a-1-gb-swap-reserve) before running builds.

The installer refuses an existing `/srv/quakestrikeph` or `/etc/quakestrike-backup` directory.
It also refuses production containers, networks, or volumes, including empty volumes.
It does not offer force-overwrite or confirmation-bypass options.
Docker and Tailscale prerequisites may already be installed.

## Rehearse without affecting production

You can rehearse on the old server if sufficient RAM and disk remain available.
Use the same uploaded package and restoration code:

```bash
sudo bash /home/ubuntu/quakestrike-transfer/restore-server.sh \
  --check --rehearse --backup-dir /home/ubuntu/quakestrike-transfer
```

```bash
sudo bash /home/ubuntu/quakestrike-transfer/restore-server.sh \
  --rehearse --backup-dir /home/ubuntu/quakestrike-transfer
```

Type `REHEARSE` to begin.
The rehearsal creates the `quakestrike-restore-test` project and files under `/var/lib/quakestrike-restore-test`.
Its application networks are internal, with separate data volumes and no published ports.
Its configuration excludes Cloudflare, consumers, scheduling, provider credentials, and GitHub updates.
The separate automated package check uses fixture credentials and loopback port `4341`; that port must be free.
No real email or SMS is sent.

**Expected result:** The script reports that rehearsal checks passed and names the reports directory.
This proves data and application restoration in Docker, not fresh-host SSH, systemd, or provider setup.
Use a disposable Ubuntu VM for a complete installation rehearsal.

After inspection, remove the disposable rehearsal:

```bash
sudo bash /home/ubuntu/quakestrike-transfer/restore-server.sh --cleanup-rehearsal
```

Type `CLEANUP` to approve removal.
Cleanup checks every resource's project and ownership label before deleting anything.
An unknown owner blocks cleanup. Production resources and the original package remain untouched.
Another rehearsal cannot start until the previous rehearsal has been removed.

## Restore the new server

**Local — PowerShell:** Replace `NEW_SERVER_ADDRESS` with the new Tailscale name or reachable address.

```powershell
scp -r "$env:USERPROFILE\quakestrike-transfer" ubuntu@NEW_SERVER_ADDRESS:/home/ubuntu/
```

**New VPS — Bash:**

```bash
chmod 700 /home/ubuntu/quakestrike-transfer
sudo bash /home/ubuntu/quakestrike-transfer/restore-server.sh \
  --check --backup-dir /home/ubuntu/quakestrike-transfer
```

If preflight passes, run the installation:

```bash
sudo bash /home/ubuntu/quakestrike-transfer/restore-server.sh \
  --backup-dir /home/ubuntu/quakestrike-transfer
```

Answer the GitHub prompts, for example:

```text
GitHub repository [ochlzo/quakestrikeph]:
SSH destination for future GitHub deployments [ubuntu@quakestrike-vps-new]:
```

Press Enter to accept each default.
All prompts read the interactive terminal; piped input cannot approve operations.
The destination must identify this new server; the prompt does not rename the Tailscale device.
The script stores the username and hostname in GitHub's `VPS_DEPLOY_USER` and `VPS_TAILSCALE_HOST` variables.
It stores the new server's own public host key in `DEPLOY_KNOWN_HOSTS`.
It restores authorized public keys and registers a new read-only repository key.
GitHub automatic deployment stays disabled.

Type `RESTORE` to approve installation.
The script restores the saved images, release, volume contents, model files, and readiness evidence.
It checks the restored earthquake count and application readiness before running automated checks.
It does not rerun migrations, register a model, or import bootstrap history.
Model and bootstrap files keep their numeric owners for the worker account.

The script restores `/etc/quakestrike-backup/` with owner `root:root` and directory mode `700`.
Its three files use owner `root:root` and mode `600`.
The script installs maintenance jobs, then runs a fresh B2 backup and an isolated PostgreSQL restore test.
SSH, sudo, and firewall snapshots remain reference files; the installer does not replace the new server's access configuration.

## Check external systems before public traffic

| Service | Required check or change |
| --- | --- |
| Cloudflare | Reuse the saved tunnel token. Keep `quakestrikeph.com` routed to `http://traefik:80` with its Host header preserved. Stop the old connector first. |
| Cloudflare DNS | Keep the existing tunnel record and Clerk/Brevo domain records. A reused tunnel normally needs no public-IP update. |
| Brevo | Add the new public outbound IP under **Settings > Security > Authorized IPs**. Preserve other required addresses. Check IPv4/IPv6 where applicable. |
| Brevo sender/callback | Preserve the sender and verified domain. Check existing callback configuration separately; production webhook setup was previously deferred. |
| Clerk / Google | Keep the existing production instance and keys. Verify sign-in and redirect settings for `https://quakestrikeph.com`. |
| IPROG | Preserve the token and sender. Check balance, destination support, and any account-specific IP restriction. |
| Tailscale | Check device rules, machine shares, and CI access to the replacement's SSH port. Recreate optional private routes only when needed. |
| GitHub | Confirm deployment access and the existing `TS_OAUTH_*` credentials. The installer updates the destination and host key through `gh`. |
| Backblaze B2 | Reuse the saved repository and encryption password. Do not run `restic init` over the existing backup repository. |
| VPS provider | Check billing, firewall, recovery access, and any separately billed disks or addresses. |

Brevo checks the request's public source IP, not the Tailscale address or incoming Cloudflare IP.
See [Brevo authorized IPs](https://help.brevo.com/hc/en-us/articles/5740111683858-Authorize-and-block-IP-addresses-for-API-and-SMTP-security).
When the existing tunnel is reused, Cloudflare normally needs no dashboard change.
Two connectors can receive traffic for one tunnel; keep the old connector stopped.
See [Cloudflare replicas](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-availability/deploy-replicas/).

After the checks pass, type `CONNECT` at the installer prompt.
The script starts Cloudflare, checks public HTTPS, and starts ingestion and prediction.
It preserves the previous Prediction Worker replica count, including a disabled Prediction Worker.
It restores the Beat schedule only if Beat ran before backup.
Ordinary alerts and private testing remain disabled.

## Understand verification and failures

The installer requires these checks to pass before reporting success:

- Archive integrity, image IDs, architecture, empty destination volumes, and restored earthquake count.
- Registered model verification and startup readiness.
- Python unit and integration suites, including both real-model checks with no pytest skips.
- Python style, shell syntax, Compose isolation, Backend unit/integration tests, and the private testing workflow/package checks.
- Bulletin check/build, portable Node tests, and internal page/API/host-routing checks.
- For a live installation: B2 backup, isolated restore test, GitHub updates, and public HTTPS checks.

Automated database tests use only `quakestrike-data-ingestion-test`; fixtures never point at restored production data.
Existing resources in that test project block the test runner instead of being reused or truncated.
The Microsoft Edge forecast-navigation browser test remains a separate manual acceptance check.
Automated checks do not establish real email/SMS receipt, production Clerk sign-in, or complete recovery of observations missed during downtime.
Real sends require a designated destination and explicit authorization.

Live reports reside under `/home/ubuntu/.local/state/quakestrikeph/server-restore/tests`.
Rehearsal reports reside under `/var/lib/quakestrike-restore-test/tests`.
If restoration fails, public ingress stays stopped and partial files remain for diagnosis.
The installation refusal also applies to partial installations; repair deliberately instead of rerunning over existing data.
Do not restart the old database after the replacement accepts new writes.

## Retire the old server

1. Confirm both protected package copies remain available.
2. Confirm public reads, sign-in, ingestion, and prediction work on the replacement.
3. Confirm the new backup and isolated restore test succeeded.
4. Review alert activation separately using [alert operations](alert-runtime.md).
5. Enable GitHub deployment only after deployment access and runtime checks pass.
6. Remove the old Brevo IP and Tailscale device after verifying their replacements.
7. Revoke credentials used only by the discarded server.
8. Delete the old VPS through its provider.
9. Remove obsolete billed disks, snapshots, and addresses.

Private pgAdmin and alert testing remain optional manual setups.
Follow [database maintenance](database-maintenance.md) and [private alert testing](alert-testing.md) when those tools are needed.
Restore their private Tailscale Serve routes separately; do not expose those tools through the public Cloudflare tunnel.
