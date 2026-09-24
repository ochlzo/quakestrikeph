# Provide a private production database browser through Tailscale

**Status**: accepted

Operators may browse the live production PostgreSQL database with pgAdmin 4 in
an optional Docker Compose profile. pgAdmin joins the private data network and
connects to PostgreSQL by its Compose service name. Its HTTP port is published
only on the VPS loopback address. Tailscale Serve proxies that loopback port to
an HTTPS name available within the tailnet. Do not add a Cloudflare Tunnel or
Traefik route for pgAdmin, publish PostgreSQL port 5432, or bind pgAdmin to a
public VPS interface.

The pgAdmin database connection uses a dedicated `quakestrike_observer` login.
It has `CONNECT`, schema `USAGE`, and table `SELECT` grants for the application
database, including default `SELECT` grants on future tables created by the
migration role. It has no application write or schema grants. Its default
transactions are read-only. Provisioning is an explicit operator command after
migrations, and credentials stay outside Git. The pgAdmin web login is separate
from the PostgreSQL login. Tailnet policy should limit access to authorized
operators; pgAdmin authentication remains required.

This is a maintenance tool, not part of the Operations Console or the public
application. It can display sensitive production records, so operators use it
for direct investigation and do not embed it in either application. The
production database remains the live source of truth. Browsing does not create
a copy, and newly committed records appear after refresh or a new query.

This decision adds an optional private operator path to the architecture's
network rules. The existing public edge still routes only the two application
hostnames. The [operator steps](../../README.md#browse-production-postgresql-over-tailscale)
define how to enable and stop the browser.
