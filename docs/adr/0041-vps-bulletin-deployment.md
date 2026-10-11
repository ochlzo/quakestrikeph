# Host the public Bulletin on the VPS with checked releases

**Status**: accepted

[ADR 0049](0049-automatic-full-application-deployment.md) extends routine deployment to the Backend, reviewed migrations, restricted grants, and already-enabled alert services. It replaces unconditional image rollback after a schema change.

Amends the Bulletin checkout and hosting decision in [ADR 0040](0040-scoped-rollover-recovery-and-worker-checkout.md). Its historical recovery rules remain unchanged.

The Bulletin stays in the monorepo and runs in its own production Astro Node container on the existing VPS. Cloudflare Tunnel keeps the public hostname `quakestrikeph.qzz.io` mapped to `http://traefik:80`. Traefik routes `/api/v1/` to the existing Backend with higher priority and other paths on that hostname to `bulletin:4321`. Port 4321 has no host mapping. The Bulletin joins only the edge network and receives no database, broker, or provider secrets. Cloudflare Access remains limited to the Operations Console.

GitHub Actions builds the Bulletin production image, which runs Astro checks and a frozen-lockfile build, and checks production HTML and an emitted asset. A disposable Traefik container checks page routing, API priority against a mock Backend, and rejection of unrelated hostnames. The VPS deployment depends on worker, Backend, and Bulletin checks. It disables the old sparse checkout and builds a SHA-tagged Bulletin image before replacing services. The Backend image remains independently deployed.

The deployment starts Bulletin, recreates Traefik to refresh its route-file mount, then checks the public homepage and API. Failed rollout restores the previous checkout, worker images, Bulletin image, and Traefik configuration. A failed first Bulletin rollout removes the new container and restores the prior API-only route. Image tags are saved only after successful checks. Keep previous images for rollback. The existing deployment flag and Tailscale/SSH credentials control automatic releases; enable it only after the first verified rollout.
