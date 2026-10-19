# Isolate private alert testing and its temporary Redis session

**Status**: accepted implementation decision within issues 56 and 57, 13 October 2026.

## Amendment: autosaved workspaces and public previews — 14 October 2026

This amendment supersedes the browser-memory-only and submitted-only read
restrictions below. Issues 56 and 58–63 now include workspace recovery and
public preview before sending.

Each browser tab has an independent workspace UUID retained in sessionStorage.
Only that identifier enters browser storage. Redis stores bounded editable
input strings, selected tester UUIDs, a workspace revision, and the exact signed
preparation. Restore once after active-session admission, before defaults can
autosave or preparation can run. Missing workspaces use defaults; empty fields
and an empty selection in an existing workspace remain empty.

Private workspace reads and revision-checked writes use the existing private
origin admission. Writes serialize per workspace and reject obsolete revisions.
Invalid editable input strings may be saved, but only validated signed
preparations produce public previews. Selection changes do not regenerate replay.
All keys use the session prefix and expire at its original fixed deadline.
Atomic Redis gates reject closure, expiry, or replacement before reading/writing.
Failed restoration blocks edits and autosave until retry; failed saves retain
local edits and show toaster feedback. Navigation does not restart restoration.

Each preparation creates one immutable preview record under a separate preview
key. It contains approved synthetic data and stable forecast/revision identities,
never tester selections or workspace inputs. Public readers select it with
`/forecasts/{eventId}?test=true`, retain normal projection and no-store behavior,
and prefer a submitted scenario when both exist. Editing creates a new preview
identity; earlier links remain stable until session invalidation.

Autosave creates no history row, alert job, queue entry, or provider request.
Simulate and Send separately validates and freezes the reviewed preparation and
selected accounts, then uses the existing idempotent submission workflow.
Preview keys must not collide with submitted scenario keys. Submission and
workspace restoration never regenerate the reviewed observations.

The alert testing tool is a separate Astro/React application at
`apps/quakestrikeph-alert-testing`, backed by the isolated Python module
`quakestrike.alert_testing`. It is separate from both the public Backend and
the Cloudflare Access Operations Console. No public control route is added.

For the session slice, Python's standard-library threaded HTTP server serves
the Astro static build and same-origin JSON controls. It binds only to
`127.0.0.1`. An explicitly configured HTTPS `.ts.net` origin supports Tailscale
Serve; configuring an origin does not enable Serve or authorize deployment.
Tailnet policy controls operator admission. Exact Host validation applies to
all requests; mutations additionally require an exact Origin, JSON content,
and a custom request header. No CORS or proxy-header trust is enabled.
This avoids another web runtime dependency for three bounded control actions.
Requests have body limits, transport timeouts, and bounded concurrency.

Reuse the incumbent theme and the prototype's existing React Aria controls through
`packages/ui`; preserve Bulletin import paths through a re-export. The shared
Astro layout composes the prototype sidebar, header, and session presentation.
Its React shell receives page content; it does not select screens. Scenario,
Testers, and History remain separate pages. Later-ticket workflows are not
simulated or enabled by this slice.

This is a synthetic-only exception to ADRs 0012 and 0047: Redis is the
authoritative temporary store for the test session and its synthetic records.
Ordinary durable jobs, delivery evidence, queues, and PostgreSQL ownership
remain unchanged. The eventual isolated test queue uses one Redis Stream per
session under the session prefix, with identifier-only versioned commands.
Issue 57 creates no stream, job, scenario, provider request, or consumer.
Queue publication and consumption belong to later tickets.

The control hash is `quakestrike:alert-testing:session`. Session-owned keys use
`quakestrike:alert-testing:<UUID>:`. Lua operations use Redis time to serialize
starts, preserve the original four-hour deadline, close before deletion, and
fence cleanup completion with a token. Application workflows expose session
operations; callers do not coordinate Redis keys. Every future child record
must expire at the original deadline and use an atomic active-session gate.
The metadata hash is not a synthetic business record: it retains only session
identity, times, lifecycle, and cleanup coordination until 24 hours after the
fixed deadline, without extending that retention on reads or retries.
This bounded tombstone makes expired and failed-cleanup states observable.
No provider-call coordination exists in this slice. A later consumer must add
bounded authorized-call coordination before enabling submissions.

Expiry closes access independently of cleanup. End and retry cleanup require
the owning UUID, so stale tabs cannot close a replacement session. New starts
are refused until the previous session's cleanup completes. Cleanup scans only
that UUID's prefix in bounded batches, unlinks matching keys, and never flushes
Redis. A ten-second cleanup lease allows recovery after process loss; tokens
prevent late cleanup results from altering a replacement session. Failures
retain a closed session and permit explicit idempotent retry. A small runtime
maintenance loop closes expired sessions and advances pending cleanup; failed
cleanup requires an operator retry. No production worker is changed or enabled.

The metadata hash eventually expires even if cleanup fails. Child deadlines
remain the final deletion safeguard. A dependency outage cannot establish
inactivity; the private HTTP interface returns dependency-unavailable without
claiming a completed start, closure, or cleanup. Runtime enablement, provider
verification, and deployment gates in ADRs 0025 and 0047â€“0049 still apply.

References: [issue 56](https://github.com/ochlzo/quakestrikeph/issues/56),
[issue 57](https://github.com/ochlzo/quakestrikeph/issues/57).

## Ticket 58: account reads and browser memory

The private tool uses a separate `quakestrike_alert_testing` PostgreSQL login.
Explicit provisioning grants SELECT only on account identity, display name,
alert destinations, verification, channel settings, status, onboarding, and
saved nearby rules. The reader rejects broader application permissions and
uses read-only, parameterized queries with two-second timeouts and at most
50 returned rows. The browser receives names and masked destinations, never
complete destinations, Clerk identities, or saved coordinates. Existing Domain
rules determine provisional eligibility; SMS support remains unknown without
provider requests. Reads require the owning active session before and after
the database query. No account or production worker changes are introduced.

On 13 October 2026, the user replaced the published Redis draft and recovery
requirements with browser-memory drafts and future preparation. There is no
autosave, Redis draft storage, revision check, browser recovery storage, or
unsaved-navigation guard.
Separate Astro pages use Astro's ClientRouter and one tab-local memory
workspace. Internal navigation preserves edits; reload or leaving the tool
may discard them. Tabs remain independent. Session closure, expiry, and
replacement reset the workspace. The shared session's Redis ownership,
fixed deadline, and cleanup remain unchanged.

Scenario submission stays outside ticket 58. Ticket 59 owns preparation in
browser memory. Simulate and Send will be the explicit save/freeze and queue
boundary when ticket 61 implements submission. It remains unavailable here,
along with replay randomization, the prepared replay diagram, and public preview.
Incumbent prototype controls
move to `packages/ui`; Bulletin re-exports preserve their existing callers.

## Ticket 60: submitted public reads

The public Backend reads Redis directly through a purpose-specific read-only
Infrastructure adapter and the `SyntheticScenarioReader` Application interface.
The private Python control server remains private. The reader performs one
atomic Lua operation using Redis time, active lifecycle, the fixed deadline,
and the active UUID's scoped scenario key. It neither mutates lifecycle nor
extends TTL. Closure and expiry reject reads before cleanup completes.
Replacement selects only the new UUID's keys. Event identities are globally
unique and cannot be reused by the producer across sessions.

The versioned submitted envelope is recorded in
`packages/contracts/alert-testing/README.md`. Ticket 61 writes that envelope
only at Simulate and Send, retaining the exact prepared scenario and allocating
stable revision and forecast identities. Ticket 60 adds only disposable test
fixtures. Domain validates stored values and projects approved public fields;
Application coordinates reads and observation paging; Interface validates
request windows and maps responses. No production PostgreSQL ownership changes.

`ALERT_TEST_REDIS_URL` supplies a separate Backend client. Missing configuration
or a storage failure returns 503 for synthetic requests while ordinary reads
remain independent. No new deployment configuration or target activation is
part of ticket 60. The existing detail endpoint selects synthetic data with
`test=true`; a scenario-scoped observations endpoint cannot read production.
Public responses and synthetic HTML use `no-store`. Open pages check validity
every 15 seconds, on focus/visibility restoration, and at the fixed deadline.
Confirmed absence or dependency failure clears the replay cache and reloads
through the incumbent server-rendered invalid-link or unavailable state.
Back/forward cache restoration also reloads. No test labels or layout changes.
Without JavaScript, validity is checked on each server request; automatic
open-page invalidation requires JavaScript, as do the incumbent replay controls.

## Ticket 61: signed preparation, submission, and isolated consumption

Preparation remains stateless. The control process adds a SHA-256 HMAC
`preparation_token` over the complete preparation and editable input strings.
`ALERT_TEST_PREPARATION_KEY` is an explicit server-only key of at least 32 bytes.
Keep the key stable across control restarts to validate retained browser requests.
Canonical JSON normalizes whole floats to integers for browser interoperability.
Submission validates the input rules, signature, owning active session, original
deadline, preparation time, and forecast expiry. A stale preparation means
changed reviewed values or inputs, wrong ownership/deadline, or an expired
forecast. Multiple independent valid preparations may coexist in browser memory;
there is no persisted preparation revision or global newest-preparation rule.

The prepared event UUID is the logical submission and job identity. Retry the
same reviewed request and selected-ID set after an uncertain response. A changed
payload or roster cannot reuse that identity. A new deliberate submission
requires a new preparation and event UUID. Public scenario envelopes remain
write-once at ticket 60's key. Revision, forecast, and model UUIDs are assigned
once. The public reader ignores the signature and projects only approved data.

An atomic owning-session gate saves the envelope, private job, and history entry.
The private job is an outbox: `pending` never claims queue acceptance. A second
gated Lua operation publishes versioned identifier-only commands to the session
Stream and records `enqueued`. Lost responses reuse the original job. Stream
duplicates remain possible after interrupted publication; recipient reservations
make those duplicates safe. The separately enabled consumer repairs pending
publication and uses one group, `test-delivery-v1`, with 30-second pending-entry
recovery. Neither runtime uses production queues or Dispatcher code.
The job's original envelope JSON repairs an interrupted first save without
allocating another identity. A separate scoped outbox index limits publication
repair to 50 pending jobs per pass. History uses 50-row pages rather than
truncating older scenarios; every earlier saved link remains addressable.

Consumer execution freezes production general/nearby content using unchanged
rendering and geographic functions, then appends `?test=true` to the complete
forecast URL. The restricted account adapter reads only selected IDs. Each
channel rechecks eligibility; SMS additionally checks ordinary sender support
and reads account settings again afterward. SMS uncertainty does not block email.

The consumer persists one fenced attempt before transport. An authorized attempt
starts as unknown, so process loss cannot authorize an automatic resend. A final
gate checks the attempt token, active ownership, and sufficient transport time.
The caller also rejects a reservation older than three monotonic seconds.
Existing provider adapters bound actual calls to 12 seconds on the Linux main
thread, without transport retries. Explicit rejections become failed; accepted
and unknown remain distinct. This slice does not automatically retry failed
provider submissions or establish delivered evidence.

The control hash retains only `calls_until_ms`, the maximum 15-second reservation
deadline, as additional coordination metadata. Cleanup waits through that bound,
including after session expiry; business records still expire at the original
deadline. Completed calls do not shorten this conservative grace period.
The field has the control hash's existing fixed retention of 24 hours after the
session deadline. It contains no account, destination, message, or delivery
history. Closure blocks reservations before waiting. Outcome writes require the
same active owner and an existing attempt token; late results cannot recreate
records or modify a replacement session.

Brevo receives `quakestrike-attempt:test:<session>:<event>:<attempt>` through the
incumbent adapter's custom-header construction. The marker identifies test
callbacks after deletion. Authenticated callback reconciliation, delivered proof,
and full closure presentation remain ticket 62. Packaging and Serve configuration
remain ticket 63. None of these decisions authorizes live sends or activation.

## Ticket 62: test evidence and observable closure

The Backend adds a purpose-specific Redis test reconciler beside its ordinary
PostgreSQL reconciler. The existing Brevo route authenticates and validates
before selecting either adapter. The established test marker identifies the
owning session, event, and pre-created attempt even after cleanup. Tagged test
evidence cannot fall through to production. Missing test Redis configuration,
outages, corrupt state, and missing active correlation retain bounded retry
responses. Verified closed, expired, replaced, or deleted sessions are
acknowledged without recreating evidence.

The consumer creates a session-scoped attempt index before transport. An atomic
callback script locates the exact email row, binds an immutable reference,
rejects collisions, and applies timestamp and outcome ordering. Submission
completion merges with that row rather than replacing callback evidence.
All attempt and reference indexes follow the original child-record deadline.
No callback inbox, PostgreSQL test record, or retained delivery history exists.

Known SMS references use the existing provider's authenticated status lookup
inside the isolated consumer. One reference is claimed per loop, with a
60-second interval per attempt and the existing bounded provider transport.
Polls have no submission authority. Unknown evidence cannot trigger a resend.
Accepted remains distinct from delivered; timestamp-free polls advance by
strength without fabricating provider event times.

Authorized polls share the existing `calls_until_ms` grace period. Closure
blocks new reservations and invalidates reads before waiting. Session responses
project waiting, deleting, failed, and complete phases from server state.
The control hash adds only closure and cleanup-completion timestamps, with
the existing fixed retention of 24 hours after the original deadline.
Business records still expire at that deadline. Cleanup failures remain closed,
and explicit retries are idempotent. Neither callback nor outcome nor poll
reconciliation can revive children after closure, expiry, or replacement.

The private UI preserves the accepted visual layout with real actions only.
There are no simulated completion buttons, prototype preview controls, or
persisted unfinished drafts. Final browser and controlled provider acceptance
remain separate from disposable workflow verification.

## Ticket 63: opt-in packaging and private Serve port

The UI build is copied into a dedicated Python control image derived from the
tested worker image. Node and build tools remain in the build stage. A separate
consumer uses the worker image and requires both its own Compose profile and
`ALERT_TEST_CONSUMER_ENABLED=true`. Neither private runtime receives production
worker configuration. The control process receives no provider credentials.

Python keeps its `127.0.0.1:4341` binding. A private relay uses the incumbent
`traefik:v3.7.13` image and shares its container network namespace with Python.
The relay listens on container port 4342 and forwards to namespace loopback
4341, preserving the original Host and Origin. Only the relay publishes
`127.0.0.1:4341:4342` on the host. This avoids changing Python's admission
boundary or granting host networking. The relay has no public-edge network,
Docker socket, dashboard, access log, or public route. Its own loopback ping
checks relay readiness; the control health probe reads the session through it.
The consumer marker records only its PID at startup. A probe checks that PID
and bounded Redis connectivity, without requiring an entire recipient batch
to finish within a health interval. It carries no scenario or delivery evidence
and cannot establish receipt or processing progress.

`compose.alert-testing.yml` is an explicit additional file. Normal release
automation omits it. Private services require named profiles; consumer startup
also fails unless enabled explicitly. All three runtimes select the same
explicit `ALERT_TEST_REDIS_URL`. The packaged `alert-test-redis` is a separate
instance on the private data network, without host ports, snapshots, or AOF.
Redis loss discards tests; operators must not replay uncertain submissions into
a new session. PostgreSQL remains unchanged and account access remains restricted.
The normal Backend Compose file passes the optional test URL during explicit manual activation.
Routine deployment overrides that URL to empty and stops private services under the 20 October 2026 amendment to ADR 0049.
Deployment stops private controls before checking cleanup, preventing new starts or submissions during that check.
If cleanup is incomplete or unverifiable, deployment restores the previously running controls and aborts before public application downtime.
After cleanup passes, deployment stops consumers, rechecks cleanup, and stops private Redis last.
The saved private URL remains available for a subsequent manual activation.

On the named VPS, Tailscale Serve uses private HTTPS 8443 to host loopback
4341. PgAdmin keeps HTTPS 443 to loopback 5050. Origin validation allows 8443
in addition to the existing HTTPS defaults; request Host/Origin equality
remains exact, including the configured port. Tailnet policy must admit only
authorized operators to TCP 8443. No identity is accepted from proxy headers.
Port-scoped Serve removal preserves the existing 443 route.

Initial activation, credentials, admission changes, and live sends still require
separate authorization. Private runtime releases remain manual and use tested
Git SHA images. End and deactivate tests before a routine main deployment or
schema maintenance window. Update private images only after normal application
checks pass; do not restart an old active session under a different release.
Keep compatible previous images for rollback. Schema revision changes require
repair forward under ADR 0049; no automatic database downgrade is introduced.
