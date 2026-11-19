# Operate the Backend API

The public API is `https://quakestrikeph.com/api/v1`.
Use [local runtime](local-runtime.md#daily-bulletin-commands) for development and [routine deployment](continuous-deployment.md#deploy-a-tested-release) for releases.

| Task | Section |
| --- | --- |
| Prepare the Backend on a new VPS | [First VPS setup](#first-vps-setup) |
| Check public search and detail routes | [Verify](#verify) |
| Configure guest simulation | [Guest forecast simulation](#guest-forecast-simulation) |
| Diagnose startup or stop the public path | [Failure and rollout notes](#failure-and-rollout-notes) |
| Replace only the Backend during recovery | [Manual upgrade](#manually-upgrade-an-existing-backend) |

Container startup does not create tables or register the model. Apply migrations and restricted grants first.

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
   `quakestrikeph.com` to `http://traefik:80`. Cloudflare Tunnel must preserve
   the public host. The Traefik file route forwards only `/api/v1/` on this
   hostname. [Bulletin hosting](continuous-deployment.md#bulletin-hosting) adds a lower-priority page route on the same hostname. No Console or pgAdmin route is created here.
3. Start PostgreSQL and Redis, provision the restricted role, then build and start the Backend path:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml up -d --wait postgres redis
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml build backend-api
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml up -d --wait backend-api traefik cloudflared
```

**Expected result:** PostgreSQL, Redis, Backend, Traefik, and Cloudflared are healthy.
Continue with [both public checks](#verify).

Use the existing managed Tunnel token for this hostname. Configure its mapping in Cloudflare; the repository does not create that mapping.
See [account setup](bulletin-accounts.md) for authenticated routes.

## Verify

Check container readiness, then query the public HTTPS path:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml ps backend-api traefik cloudflared
curl -i -X POST 'https://quakestrikeph.com/api/v1/earthquakes/search' -H 'Content-Type: application/json' --data '{"limit":2,"magnitudeRanges":[{"below":3},{"from":5}]}'
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
curl -i 'https://quakestrikeph.com/api/v1/earthquakes/<eventId>'
```

Expect HTTP 200 with `item`, including `forecast` and `forecastAvailability`.
A null forecast is valid. If search returns no events, use a known existing
event ID before completing rollout verification. Search and `/healthz` do not
check the detail query's column permissions.

For a local contract check, run `npm ci` and `npm test` in `apps/backend-api`.
The PostgreSQL query integration test runs in the isolated
`quakestrike-data-ingestion-test` Compose project after the worker migration
suite. It creates a disposable Backend role and never contacts production.

## Guest forecast simulation

The Backend registers `POST /api/v1/forecast-simulations` when `SIMULATION_SERVICE_URL` is set.
Use the optional `infrastructure/compose.forecast-simulation.yml` file with the usual Backend Compose files.
The simulator runs from the tested prediction image and listens on the private data network.
Run one simulator instance. Its configured slots serve all Backend instances.

- Configure `SIMULATION_DATABASE_URL` with the `quakestrike_simulator` login and the matching `SIMULATION_DB_PASSWORD`.
  Provision the login with `sh /opt/quakestrike/provision-roles.sh create-simulator` in PostgreSQL after migrations.
  The login can read coverage evidence and event revision fields.
- Set `SIMULATION_SERVICE_URL=http://forecast-simulator:4350` and set `SIMULATION_REDIS_URL` to the shared quota store.
  Set independent 64-character lowercase hex secrets for `SIMULATION_SERVICE_TOKEN`, `SIMULATION_COOKIE_KEY`,
  `SIMULATION_PAGE_TOKEN`, and `SIMULATION_INGRESS_KEY`. Share the signing key across Backend instances.
- For production, pass the ingress key to Traefik and the Backend. The simulation router adds the ingress key.
  The Backend uses `CF-Connecting-IP` on that path. Keep Cloudflare's Pseudo IPv4 overwrite mode disabled.
  For direct local testing, leave the ingress key empty and set `SIMULATION_LOCAL_INGRESS=true`.
- Set `SIMULATION_SLOTS`, `SIMULATION_MEMORY_LIMIT`, and `SIMULATION_CPUS` for the simulator.
  Before opening guest runs, measure guest capacity alongside live forecasts and Bulletin reads as specified in issue #83.

The Bulletin server can call `GET /internal/forecast-simulations/page` on the private Backend URL.
Send the visitor's `Cookie` header and `Authorization: Bearer <SIMULATION_PAGE_TOKEN>`.
The response reports `guestCookieConfirmed` and `catalog`, which contains `status` and `catalogCutoff`.
The catalog status is `current`, `stale`, `too_old`, `insufficient_history`, or `unavailable`.
The cutoff is an ISO 8601 UTC timestamp when known and `null` otherwise.

If the Backend returns `Set-Cookie`, forward it to the browser with one redirect back to the page.
On the redirected request, call the internal endpoint with `?confirm=1` to check the cookie without issuing another.
Serve the redirect and the page with `Cache-Control: no-store`.

## Failure and rollout notes

| Symptom | Check |
| --- | --- |
| Backend is unhealthy | Database connectivity, Backend password/grants, and registered `MODEL_RELEASE_ID`. |
| Search works but detail fails | Run the detail check and reapply the restricted Backend grants. |
| Account requests fail | Account Redis configuration and [account setup](bulletin-accounts.md). |
| Public URL fails while Backend is healthy | Tunnel hostname, preserved Host header, and Traefik routing. |

Inspect recent logs from `/srv/quakestrikeph`:

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.backend.yml -f infrastructure/compose.edge.yml logs --tail 100 backend-api traefik cloudflared
```


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

## Access and routing reference

- The Backend uses the private Compose hostname `postgres`; PostgreSQL has no published host port.
- The Backend uses its restricted login, separate from worker, migration, and pgAdmin observer logins.
- Read grants cover selected event, revision, prediction-job, model-release, and forecast data.
- Account migrations add narrow account writes and append-only audits. The Backend cannot write worker records, alerts, or technical logs directly.
- The Bulletin UI does not need to run for API requests to work.
- `quakestrikeph.com` is the sole public domain. The retired `quakestrikeph.qzz.io` has no API route or redirect.
- Cloudflare Tunnel preserves the public Host header. Traefik rejects unrelated hosts.
