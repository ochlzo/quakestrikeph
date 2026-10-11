# Explicit forecast alert runtime

The runtime defaults to disabled. These commands document operator actions; they do not authorize shared database changes, real sends, or production activation.

See [forecast alert verification](forecast-alert-verification.md) for simulated evidence, unresolved live observations, and full activation gates.

The Alert Worker consumes version-1 identifier-only commands from `alert`. It constructs IPROG SMS and Brevo email providers before consumption.
The worker records an attempt before each external call. Accepted and uncertain submissions never trigger an automatic resend.
Known IPROG references reconcile through polling. Authenticated Brevo callbacks use `POST /api/v1/callbacks/brevo` and the existing narrow database function.
An independent process settles jobs after callbacks, expiry, and abandoned calls. The Backend does not settle jobs.

## Configuration and readiness

Use a tested Git SHA for `WORKER_IMAGE_TAG` and `BACKEND_IMAGE_TAG`. Keep separate worker, migration, and Backend database URLs.
Use `quakestrike_worker` for runtime and retirement. Apply only already approved grants through `provision-roles.sh`.
Verify the registered model, bootstrap coverage, migration head, and private PostgreSQL/Redis connectivity before startup.

| Setting | Consumer and requirement |
|---|---|
| `ALERT_RESOLUTION_ENABLED=false` | Dispatcher publication gate; Alert Worker also requires this gate. |
| `ALERT_DELIVERY_ENABLED=false` | Alert Worker and reconciliation gate. |
| `PUBLIC_BULLETIN_BASE_URL` | Prediction Worker freezes full `/forecasts/{eventId}` links; default `https://quakestrikeph.qzz.io`. |
| `IPROG_API_TOKEN` | Alert Worker, reconciliation, and Backend phone verification only. |
| `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` | Alert Worker only; authenticate the selected account and sender before activation. |
| `BREVO_CALLBACK_TOKEN` | Backend only; separate bearer token of 32–1024 nonspace ASCII characters. Missing configuration denies callbacks. |
| `ALERT_RECONCILIATION_INTERVAL_SECONDS=5` | Reconciliation interval, 1–60 seconds. |
| `ALERT_RECONCILIATION_BATCH_SIZE=20` | Poll and maintenance page limit, 1–100 records. |

Never copy the complete private environment into each service. Compose forwards only each service's required secrets.
The reconciliation process needs IPROG configuration but does not need the Brevo API key.
Process health verifies configuration, restricted capabilities, local queue consumption or a fresh scan marker, migration state, and data-service connectivity.
Health output labels provider authentication and delivery proof as `unverified`. A healthy process does not prove provider authentication or delivery.

```text
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile alerts exec -T alert-worker quakestrike health-alert
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile alerts exec -T alert-reconciliation quakestrike health-alert-reconciliation
```

Polling and maintenance use separate process-owned UUID cursors. Unresolved early records cannot monopolize later pages.
Each pass reserves 30 seconds for polling and a separate five seconds for maintenance.
One phase's failure does not cancel the other phase. Database calls use a five-second statement timeout and a one-second lock timeout.
An individual persistence or settlement failure advances the poll cursor and makes that pass unhealthy. A later sweep retries the read without resubmission.
Restarting reconciliation begins a fresh sweep. Polls do not invent or change provider timestamps.
An unavailable dependency makes health fail; subsequent passes and new connections can recover without recreating delivery evidence.

## Ordered deployment and legacy retirement

First obtain environment-specific approval for migrations, retirement, activation, and real provider verification.
Back up the database and retain the previous tested images. Stop Beat and Dispatcher publication before changing the alert runtime.
Keep `ALERT_RESOLUTION_ENABLED=false` and `ALERT_DELIVERY_ENABLED=false` during preparation.

1. Stop the existing Alert Worker before deploying incompatible content producers.
2. Apply the approved migration through the migration login.
3. Refresh the approved worker and Backend grants.
4. Deploy the tested Prediction Worker with the public Bulletin base URL.
5. Preview and explicitly retire applicable legacy jobs through the worker login.
6. Deploy the tested Backend with the separate callback token.
7. Verify authenticated callbacks and both providers in the restricted disposable environment.
8. Start reconciliation and the Alert Worker before enabling Dispatcher publication.
9. After all verification gates pass, enable publication for the full eligible roster.

Migration preparation and shared execution remain distinct operations. Follow [database maintenance](database-maintenance.md) for private database access.
Run the existing `release-init quakestrike migrate` with the migration URL, then refresh grants:

```text
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh grant-worker
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create-backend
```

Retirement runs through the worker service environment. An explicit service name permits a one-shot command without starting its normal consumer.

```text
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile alerts run --rm --no-deps alert-worker quakestrike retire-legacy-alerts
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile alerts run --rm --no-deps alert-worker quakestrike retire-legacy-alerts --apply --alert-job-id <previewed-job-uuid>
```

Preview returns at most 100 identifiers, statuses, expiry times, content hashes, and recipient counts. It does not return content or destinations.
Apply requires explicit identifiers, up to 100 per transaction. Repeat preview and apply until all intended applicable rows settle.
Legacy means all six forecast-content additions are null. Complete content, terminal jobs, live claims, any attempt, or meaningful recipient outcomes prevent retirement.
Overdue legacy jobs expire. Other applicable jobs fail with `legacy_content_retired`; their unsent recipients become skipped.
The transaction stops dispatch, clears ownership, and inserts the required audit. Audit failure rolls back the entire batch.
Content snapshots remain unchanged. Repeated retirement creates no duplicate audit and preserves terminal or meaningful evidence.
Old valid identifier commands still parse, but terminal retired jobs cannot send. Malformed or unexpected command fields reject before state changes.

After approved full verification, set both gates to `true` in private configuration and start the explicit profile:

```text
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml --profile alerts up -d --wait alert-reconciliation alert-worker
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.release.yml up -d --wait --no-deps dispatcher
```

Normal activation uses every eligible account. Do not add a production test-account filter or copy finite authorization settings into normal consumers.
The automatic deployment script refuses deployments while either alert service runs. Use the ordered alert rollout for subsequent activated releases.

## Finite disposable verification

Use only `compose.integration.yml` plus `compose.alert-verification.yml` in `quakestrike-data-ingestion-test`.
Fixtures migrate and truncate that database; never point those fixtures at shared data.
Provision `quakestrike_worker` inside the disposable database with the approved grants and a disposable password.
Set private `CONTROLLED_DATABASE_URL` to that login on `postgres-test:5432/quakestrike_test`.
Keep private authorization destinations in `ALERT_TEST_SMS_DESTINATION` or `ALERT_TEST_EMAIL_DESTINATION`.
Do not print expanded Compose configuration after loading real secrets.

Prepare exactly one synthetic account and one newly created complete-content job with its matching enqueued dispatch.
Select the recorded account, job, dispatch, correlation, and channels explicitly. Enable only those channels on the fixture account.
The guard rejects additional accounts, a mismatched destination, another database, incomplete content, old jobs, or existing delivery evidence before submission.
The runner permits at most one actual provider call per selected channel. SMS-only verification does not require Brevo settings.
The profile contains no Beat, Dispatcher, queue consumer, public edge, or external network.
Any temporary provider egress or callback tunnel requires separate approval and a temporary override.

```text
docker compose --env-file <private-verification-env> -f infrastructure/compose.integration.yml -f infrastructure/compose.alert-verification.yml --profile controlled-alert run --rm controlled-alert quakestrike controlled-alert --alert-job-id <job-uuid> --dispatch-id <dispatch-uuid> --correlation-id <correlation-uuid> --fixture-user-id <synthetic-user-uuid> --channel sms
```

Add `--channel email` only when that channel's provider and callback prerequisites pass.
Reuse the exact identifiers with `--reconcile` to poll at most one selected known SMS reference and settle the selected job.
Email reconciliation performs local settlement after its authenticated callback. The finite runner never polls an ordinary backlog or repeats submission.
An unknown result without a reference remains unknown. Stop and review that evidence; do not resubmit for verification.
Remove temporary connectivity and disposable resources after the separately approved verification completes.

## Rollback and evidence limits

Disable Dispatcher publication first. Stop the Alert Worker, then stop reconciliation when late-evidence recording can safely pause.
Keep both gates false and restore the previous tested compatible images. Retain database evidence and immutable content.
Do not downgrade the additive schema, reopen retired jobs, clear unknown attempts, or resend accepted/uncertain submissions during rollback.
Reconciliation can resume against retained records after the corrected release passes readiness.
Record simulated outage checks separately from actual service restarts and provider delivery proof.
A cold disposable PostgreSQL restart recreates tmpfs storage; that check cannot prove retained-data or warm-consumer recovery.
