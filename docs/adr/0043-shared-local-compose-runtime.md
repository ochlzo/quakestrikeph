# Use one local Compose project for accounts and workers

**Status**: accepted by the user on 4 October 2026.

Local application development uses the existing `infrastructure` Compose
project. Accounts and workers share its PostgreSQL and Redis services and
durable volumes. Separate migration, worker, and Backend database roles remain
required. Root `.env` supplies shared local settings and stays outside Git.
Each service receives only its required environment values.

`compose.yml` defines the data services, `compose.backend.yml` defines the
Backend, and `compose.local.yml` adds loopback HTTP ports and the Bulletin
development server. The local Bulletin proxies both public and account API
requests to the local Backend. `compose.release.yml` adds worker services to
the same project through the existing explicit enablement workflow.

Local web and migration builds use development-only `:local` image tags.
Rebuilding a dirty development checkout cannot overwrite a tested release image.
Worker release images and all production images retain the tested SHA rules
in ADR 0025. The profiled `local-init` service applies migrations explicitly
from the development checkout with the migration role.
The Bulletin development image uses the existing pinned Node and pnpm versions
and frozen lockfile. Production continues to build the final Dockerfile stage.

Traefik and Cloudflare Tunnel belong to the explicit `compose.edge.yml`
configuration. Local development never includes that file. Production includes
it explicitly; no host port mapping is added to production services.

Database initialization remains explicit. Moving configuration does not move
rows or merge databases. Preserve the former account-development volume and
configuration as recovery evidence; do not drop it or automatically import its
accounts. Migrations and restricted grants precede Backend startup against
the shared database. No fake model release is copied into the shared runtime.

The disposable `quakestrike-data-ingestion-test` project stays separate.
Its migrations and truncation fixtures never target a development database.

References: [ADR 0019](0019-explicit-startup-and-runtime-configuration.md),
[ADR 0025](0025-explicit-local-runtime-enablement.md),
[local runtime guide](../operations/local-runtime.md), and
[account implementation](0042-bulletin-account-implementation.md).
