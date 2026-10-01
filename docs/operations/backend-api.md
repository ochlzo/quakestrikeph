# Read-only public Backend API

The Backend exposes earthquake and forecast reads at
`https://quakestrikeph.qzz.io/api/v1`. The API reads the production PostgreSQL
container by its Compose service name. It has no database or host port mapping,
does not create tables at startup, and does not use the broad pgAdmin observer
login. The Bulletin UI is not required to start the API.

## First VPS setup

Run these commands in the VPS checkout at `/srv/quakestrikeph`, after the
existing worker migrations and model release registration. Keep the existing
worker stack running. Use a tested Git commit SHA for `BACKEND_IMAGE_TAG`.

1. In the ignored `.env`, set a new `BACKEND_DB_PASSWORD`, a matching
   `BACKEND_DATABASE_URL` using the `quakestrike_backend` login and `postgres`
   host, the existing `MODEL_RELEASE_ID`, `BACKEND_IMAGE_TAG`, and the remotely
   managed `CLOUDFLARE_TUNNEL_TOKEN`. Do not use the worker, migration, or
   observer login for the Backend.
2. In Cloudflare Tunnel configuration, map the public hostname
   `quakestrikeph.qzz.io` to `http://traefik:80`. Cloudflare Tunnel must preserve
   the public host. The Traefik file route forwards only `/api/v1/` on this
   hostname. [Bulletin hosting](continuous-deployment.md#bulletin-hosting) adds a lower-priority page route on the same hostname. No Console or pgAdmin route is created here.
3. Provision the restricted role and start the three Backend path containers:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml up -d --wait postgres
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml build backend-api
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml up -d --wait backend-api traefik cloudflared
```

The role has column-limited `SELECT` on events, revisions, prediction jobs, and
model releases, plus `SELECT` on forecasts. It has read-only transactions by
default and no grant on users, alerts, audits, or technical logs. If the VPS
already runs a Cloudflare Tunnel for this hostname, use its managed tunnel
token and do not create an unrelated public route. The Cloudflare mapping is
an explicit operator setup step outside this repository.

## Verify

Check container readiness, then query the public HTTPS path:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml ps backend-api traefik cloudflared
curl -i -X POST 'https://quakestrikeph.qzz.io/api/v1/earthquakes/search' -H 'Content-Type: application/json' --data '{"limit":2,"magnitudeRanges":[{"below":3},{"from":5}]}'
```

Expect HTTP 200 with `items`, `hasMore`, `nextCursor`, and `fetchedAt`. An empty
`items` array is valid if no events match; HTTP 503 means the database path is
unavailable. Use `nextCursor` with the same filters to fetch the next page.
The API uses the explicitly configured model release; an event whose latest
revision has no successful forecast for that release returns `forecast: null`.
The API does not cache rows, so committed changes appear on a later request.

For a local contract check, run `npm ci` and `npm test` in `apps/backend-api`.
The PostgreSQL query integration test runs in the isolated
`quakestrike-data-ingestion-test` Compose project after the worker migration
suite. It creates a disposable Backend role and never contacts production.

## Failure and rollout notes

Backend startup checks database connectivity and the configured model release.
The `/healthz` route checks them again for container readiness. A missing role,
wrong password, or unregistered release leaves the Backend unhealthy; inspect
the bounded container diagnostics and correct the VPS `.env` or explicit role
setup. The Backend never runs migrations or model registration itself.

The public path is rate limited by Traefik to 60 requests per minute per
Cloudflare client IP, with a burst of 20. The public origin has no mapped host
ports. The Cloudflare Tunnel is the only public ingress. Queries use a three
second timeout and a five-connection pool. If location search becomes slow on
the live catalog, review its query plan before adding a PostgreSQL text index.

To stop only this public path, run:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml stop cloudflared traefik backend-api
```

Leave the PostgreSQL and worker containers running. For a new Backend image,
build and test the new Git SHA, update `BACKEND_IMAGE_TAG`, and recreate
`backend-api` while retaining the prior image for rollback. The existing
worker CI deploy script does not deploy this Backend.
