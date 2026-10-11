# Bulletin Backend API

The Backend exposes earthquake and forecast reads at
`https://quakestrikeph.qzz.io/api/v1`. The API reads the production PostgreSQL
container by its Compose service name. It has no database or host port mapping,
does not create tables at startup, and does not use the broad pgAdmin observer
login. The Bulletin UI is not required to start the API.

After initial setup, [routine deployment](continuous-deployment.md#routine-release-sequence) updates the Backend with workers and Bulletin. Secret provisioning remains manual. Reviewed migrations and grants run before the new Backend starts.

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
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml up -d --wait postgres
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml build backend-api
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml up -d --wait backend-api traefik cloudflared
```

The role has column-limited `SELECT` on events, revisions, prediction jobs, and
model releases, plus `SELECT` on forecasts. It has read-only transactions by
default and narrowly scoped account reads/writes plus append-only audits after the account migration. It has no writes to worker records, alerts or technical logs. See [account setup](bulletin-accounts.md). If the VPS
already runs a Cloudflare Tunnel for this hostname, use its managed tunnel
token and do not create an unrelated public route. The Cloudflare mapping is
an explicit operator setup step outside this repository.

## Verify

Check container readiness, then query the public HTTPS path:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml ps backend-api traefik cloudflared
curl -i -X POST 'https://quakestrikeph.qzz.io/api/v1/earthquakes/search' -H 'Content-Type: application/json' --data '{"limit":2,"magnitudeRanges":[{"below":3},{"from":5}]}'
```

Expect HTTP 200 with `items`, `hasMore`, `nextCursor`, and `fetchedAt`. An empty
`items` array is valid if no events match; HTTP 503 means the database path is
unavailable. Use `nextCursor` with the same filters to fetch the next page.
The API uses the explicitly configured model release; an event whose latest
revision has no successful forecast for that release returns `forecast: null`.
The API does not cache rows, so committed changes appear on a later request.

Use an `eventId` from the search response to check the detail path. Replace
`<eventId>` before running this command:

```bash
curl -i 'https://quakestrikeph.qzz.io/api/v1/earthquakes/<eventId>'
```

Expect HTTP 200 with `item`, including `forecast` and `forecastAvailability`.
A null forecast is valid. If search returns no events, use a known existing
event ID before completing rollout verification. Search and `/healthz` do not
check the detail query's column permissions.

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
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml stop cloudflared traefik backend-api
```

Leave the PostgreSQL and worker containers running. Automatic deployment requires
Backend, Traefik, and Cloudflared to run before a routine release.

## Manually upgrade an existing Backend

Routine main releases use automatic deployment. Use these commands only for an
approved manual rollout or recovery.

Run these steps in `/srv/quakestrikeph` on the VPS. Use the tested release
checkout after applying any required migrations. Retain the prior Backend
image and tag for rollback.

1. Set `BACKEND_IMAGE_TAG` in `.env` to the tested Git SHA.
2. Build the new Backend image.

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml build backend-api
```

3. Reapply the restricted Backend grants before replacing `backend-api`.

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend
```

The command updates an existing role and reports `"status":"ready"` on success.
It grants `SELECT` on `earthquake_event_revisions.prediction_skip_reason`,
which the forecast detail query requires. Updating the checkout or rebuilding
the image does not update permissions stored in an existing PostgreSQL volume.
The command also sets the role password from `BACKEND_DB_PASSWORD`; keep
`BACKEND_DATABASE_URL` consistent with that password.

4. If provisioning succeeds, replace only the Backend container.

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml up -d --no-deps --wait backend-api
```

5. Run both public checks in [Verify](#verify), including the earthquake detail request.

If replacement or either public check fails, restore the prior
`BACKEND_IMAGE_TAG` and recreate only `backend-api` with the same command.
The added read grant remains compatible with the prior Backend image.
