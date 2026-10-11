# Forecast alert verification and activation gates

The simulated delivery implementation is available; production activation remains blocked by controlled provider observations and deployment authorization.
This report separates application verification from provider readiness, received messages, and production deployment.
No live outcome is inferred from a successful simulation, configured secret, healthy process, or accepted submission.

## Repeatable simulated verification

Run the documented disposable project from [CONTRIBUTING.md](../../CONTRIBUTING.md).
Its fixtures migrate and truncate PostgreSQL; never use a shared development or production URL.

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

The runner supplies both test URLs. Confirm integration cases actually run.
The standard image omits model artifacts and prediction dependencies; its two expected model skips do not verify inference.
Run the separate [actual SEIS checks](local-runtime.md#real-model-integration-checks) when the approved local bundle is available.
Provision the disposable Backend login after worker fixtures finish, then run the Backend integration runner before cleanup.
Worker fixtures recreate migrations and can remove the callback grant; provision immediately before the Backend run.
Run worker unit/contract tests, Ruff, and Backend typecheck/unit tests against the same source.

| Behavior | Existing verification seam |
| --- | --- |
| Actual Redis alert publication and consumption | `workers/tests/integration/test_forecast_alert_queue.py` runs the public Prediction Worker, observes committed forecast/job/dispatch, publishes with Dispatcher, consumes the real Kombu command, and invokes the public Alert Worker. |
| Duplicate queue command and accepted evidence | The same consumed command runs twice, with one attempt per channel and exactly two simulated calls. References remain acceptance, without invented delivery timestamps. |
| Simulated delivery settlement through the queue tracer | Production SMS polling consumes a simulated delivery result; the narrow email function records simulated delivered evidence. Both recipient/attempt records finish delivered, the job completes, and its dispatch stops. Another duplicate command performs no send. |
| Frozen general/nearby content and independent preferences | Forecast-content, resolution, and delivery tests check both variants, original windows, account settings, threshold equality, and known-distance bounds. |
| Concurrency and claims | Resolution/delivery tests cover simultaneous processing, stale tokens, lease expiry after lock waits, committed attempts, and eligibility changes before calls. |
| Retry authority and uncertainty | Delivery/IPROG tests cover confirmed rejection, bounded retries, trusted waits exceeding expiry, interrupted/malformed responses, and unknown calls without automatic resend. |
| Callback/poll reconciliation | Backend Brevo and worker IPROG/runtime tests cover early, repeated, older, conflicting, late, missing-time, and callback-before-submission evidence. |
| Expiry, recovery, and retirement | Resolution/runtime/retirement tests cover unsent expiry, retained command recovery, fair scans, selected reconciliation, explicit retirement, and obsolete commands. |
| Sanitized diagnostics | The Redis tracer observes committed allowlisted evidence and formatted logs, rejecting provider payloads, destinations, content, and execution tokens. Provider and Backend regressions cover error/OTP redaction. |

This queue tracer adds the missing real alert transport seam rather than replacing lifecycle tests or starting a background consumer.
Its simulated providers exercise delivery through the application boundary; they establish no actual provider behavior.

## Recorded evidence on 11 October 2026

Integration base before ticket 52 is `5b5e1e6928c436388de994fac901548fa0b82633`.
The ticket-51 verification completed against its integrated implementation; CI run `38111904816` passed on that base.

| Check | Verified result |
| --- | --- |
| Ticket-51 standard disposable worker suite | 301 passed; two expected real-model skips. |
| Ticket-51 host unit/contract suite | 383 passed; two Windows symlink skips. |
| Separate actual SEIS checks | Two passed; zero skips. |
| Backend checks | Typecheck/build, 28 unit tests, and five restricted integration tests passed. |
| Ticket-52 real Redis tracer | One passed; zero skips in the root-coordinated disposable project. Both channels reached simulated delivered states. |
| Ticket-52 complete disposable worker suite | 302 passed; two expected real-model skips from 304 collected cases. |
| Ticket-52 separate actual SEIS checks | Two passed; zero skips. |
| Ticket-52 normal-build Backend suite | Five restricted integration tests passed; zero skips. TypeScript build passed. |

Record the final tested source and combined ticket-52 results in the implementation handoff after the complete checks finish.
Cold tmpfs PostgreSQL restart evidence does not prove retained-data restart recovery.
The retained-command test establishes bounded simulated dependency failure and recovery against real disposable storage.

## Controlled provider observations still required

Use only previously authorized local destinations, supplied through private finite-runner configuration.
Never commit those destinations, credentials, callback tokens, raw responses, inbox screenshots, or full received content.
Readiness applies separately to each selected channel; email failure does not authorize an SMS-to-email fallback.

| Observation | Status and required proof |
| --- | --- |
| IPROG account/support preflight | Root observed 195 credits and support for the designated mobile. These read-only observations are not a send or receipt. |
| SMS provider header and content | Unverified: compare received general/nearby messages with immutable snapshots and provider-added header behavior. |
| SMS encoding and charging | Unverified: compare local estimates with actual provider evidence. `sms_rate` means credits; `sms_count` remains a separate provider count. |
| SMS delivery polling | Unverified live: persist the actual reference and observe the documented result without resubmission. |
| Brevo authentication | Root observed HTTP 401; email verification is parked pending the specific account/key correction. Never request secret values in chat. |
| Brevo sender/domain and receipt | User reported setup ready, but authenticated preflight and actual received sender/content remain unverified. |
| Brevo callback | Unverified live: observe exact attempt-tag echo, compatible reference/time, bearer authentication, committed updates, and retry behavior. |
| Received event link | The earlier public event route loaded a forecast. Opening the full received link and its updated forecast remain unverified. |

Refresh public event/forecast data immediately before a finite live fixture.
Use separate active public forecasts for general and nearby jobs; one forecast permits only one alert job.
Retain original windows and public event-ID links. Do not extend expiry or rewrite snapshots to enable another send.
If fixture dependency rows use synthetic input/provenance, disclose that scaffolding; do not claim local real prediction produced mirrored outputs.
Run live sends with the existing one-call budget and private destination guard, never an ordinary queue consumer.
Unknown calls stop submission; simulate rate limits and quota failures instead of exhausting provider credit.

A temporary callback route must expose only the literal callback path through a narrow proxy.
Preserve Authorization, strict uncompressed 32 KiB JSON, and Backend status/Retry-After behavior.
Brevo documentation describes dropping 5xx callbacks, so transient processing failure uses 429.
Register and remove only the task-owned webhook; filter account-wide callbacks to the exact disposable fixture.
Actual event echo, retry timing, received content, and charging remain measured gates.
The provider creation reference omits an `error` subscription despite the payload guide describing it; do not invent a subscription spelling.
See [Brevo contracts](https://developers.brevo.com/docs/transactional-webhooks), [webhook creation](https://developers.brevo.com/reference/create-webhook), and [retry policy](https://developers.brevo.com/docs/retry-mechanism).

## Activation and rollback readiness

The intended deployment target is the repository's single VPS runtime; no production deployment occurred during these checks.
Follow the commands and exact service order in [alert-runtime.md](alert-runtime.md#ordered-deployment-and-legacy-retirement).
Before full eligible-user activation, record these environment-specific facts:

1. Record the tested source SHA, compatible previous images, backup, and target environment.
2. Stop publication and consumers while both alert gates remain false.
3. Apply the approved migration through its owner, then refresh worker and narrow Backend grants.
4. Deploy the complete-content Prediction Worker with the correct public Bulletin base URL.
5. Preview and explicitly retire applicable unsent legacy jobs; retain audits and immutable evidence.
6. Deploy the Backend callback with its separate secret and tested HTTPS routing.
7. Complete simulated checks and controlled SMS/email receipt and reconciliation observations.
8. Verify restricted capabilities, migration/model/bootstrap readiness, PostgreSQL, Redis, and process freshness.
9. Start reconciliation and the Alert Worker before enabling Dispatcher publication for all eligible users.

Health proves local process/dependency readiness, not provider authentication, account allowance, inbox delivery, or a working callback.
Keep full activation disabled while required live observations or deployment authorization remain unresolved.
Do not create a production test-account pilot or copy finite destination restrictions into normal consumers.

For rollback, disable publication first, stop the Alert Worker, and pause reconciliation only when late-evidence recording can safely pause.
Restore tested compatible images with both gates false; retain the additive schema, frozen content, audits, and unknown/accepted evidence.
Do not downgrade retained delivery tables, reopen retired jobs, reset attempts, or resend uncertain messages.
Resume reconciliation after corrected readiness; record any interval when callbacks or polls could not record evidence.
