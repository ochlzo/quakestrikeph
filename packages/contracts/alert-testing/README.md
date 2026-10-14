# Private alert-testing session contract, version 1

These routes exist only on the separate private control origin, never the
public Backend. Session responses follow `session-v1.ts`; Python owns runtime
mapping. Non-inactive responses include the owning UUID, start, deadline,
server time, and cleanup state. Times use UTC Unix milliseconds.

| Method and path | JSON input | Result |
| --- | --- | --- |
| `GET /api/test/session` | None | Shared state; detects expiry before responding. |
| `POST /api/test/session/start` | `{}` | Existing active session or one new fixed four-hour session. |
| `POST /api/test/session/end` | `{"session_id":"<UUID>"}` | Close first, then advance scoped cleanup. |
| `POST /api/test/session/cleanup` | `{"session_id":"<UUID>"}` | Retry or advance cleanup of that closed session. |

All requests require the configured Host. POST additionally requires the exact
Origin, `Content-Type: application/json`, and `X-QuakeStrike-Test: 1`.
JSON input is limited to 512 bytes. No CORS policy admits other origins.

Responses use `Cache-Control: no-store`. `200` reports server-confirmed state,
including incomplete cleanup. `400` rejects input, `403` rejects origin or
Host, `404` rejects routes, `409` rejects stale ownership or unfinished
cleanup, and `503` reports dependency-unavailable without asserting inactivity
or success. Error bodies contain a bounded `error` code; Redis outages add
`dependency: "Redis"`. Starting sends nothing and never creates child records.

The server may return `ending` or `expired` with pending/running cleanup.
Polling observes maintenance progress. Explicit cleanup retries recover failed
cleanup; requests must keep the owning UUID. Cleanup completion never reopens
a session. A later Start creates a fresh UUID after cleanup completes.

Closure responses also include `closure_phase` (`none`, `waiting`, `deleting`,
`failed`, or `complete`), `calls_until_ms`, `closed_at_ms`, and
`cleanup_completed_at_ms`. Zero timestamps mean the corresponding action has
not occurred. Waiting uses the conservative authorized-call deadline, not a
count of still-running requests. Cleanup completion and closure times contain
only lifecycle metadata. Their retention never extends on reads or retries.

Hosting and storage decisions: [ADR 0050](../../../docs/adr/0050-private-alert-testing-session-runtime.md).

## Test delivery evidence, ticket 62

The Brevo callback remains `POST /api/v1/callbacks/brevo` on the Backend.
Its existing Bearer authentication, JSON limits, timestamp validation, and
bounded retry responses apply before routing. Production markers and absent
markers retain the ordinary PostgreSQL route. Test emails must carry
`quakestrike-attempt:test:<session UUID>:<event UUID>:<attempt UUID>` in
`X-Mailin-custom`; test reconciliation never falls through to PostgreSQL.

Redis uses one `attempts:<event>` hash to map pre-created attempt UUIDs to
recipient slots (`<user UUID>:<channel>`), one `recipients:<event>` hash for
private rows, and a session-wide `references` hash mapping
`<channel>:<provider reference>` to `<event UUID>:<attempt UUID>`.
Every index expires at the original session deadline. All keys remain under
the owning `quakestrike:alert-testing:<session UUID>:` prefix.

Callback updates atomically validate active ownership, the original deadline,
the email attempt token, and immutable reference correlation. Early callbacks
use the attempt index established before transport. A conflicting reference
returns 409. Missing active correlation and unavailable storage return 429
with `Retry-After: 60`. Verified inactive, expired, replaced, or deleted
sessions return 204 without writing records. An outage never proves absence.

Older callback timestamps are ignored. Equal timestamps prefer delivered over
failed over accepted. Delivered cannot regress, and accepted cannot reopen
failed. Submission completion preserves previously authenticated evidence.
Results expose only the existing masked fields plus an optional bounded
`evidence_note` for reference conflicts.

The isolated consumer also polls known SMS references. A `sms-polls` sorted
set schedules at most one reference per consumer pass, with at least 60 seconds
between claims for that attempt. Polls cannot submit messages. Unknown polls
preserve the outcome; authenticated provider responses can advance unknown to
accepted, accepted to failed, or either to delivered. Polls have no fabricated
provider event timestamp. Their bounded authorization uses `calls_until_ms`
so closure waits for transport but never permits late writes or child revival.

## Tester account reads, version 1

`POST /api/test/testers` accepts `session_id`, `query`, `selected`, `page`,
`size`, and `event`. `testers-v1.ts` describes account results. The route
requires the existing exact Host, Origin, JSON type, and custom header.
The body is limited to 64 KiB; session POST retains its 512-byte limit.
Using POST keeps search terms and selected identities out of URLs. The
operation is read-only and all responses remain private and no-store.

Search text has a 100-character limit and literal substring matching on
name or email. `selected` is null for all accounts or at most 500 distinct
canonical account UUIDs for the selected filter. `size` is 5, 10, 25, or 50;
`page` is 1 through 10000 and the returned page is clamped to available rows.
`event` contains magnitude, latitude, and longitude as editable strings.
Invalid event values return explicit provisional eligibility explanations.

Accounts expose names, masked destinations, enabled/verified flags, account
status, onboarding completion, magnitude threshold, and nearby distance limit.
They expose no saved coordinates, complete destinations, or Clerk identities.
SMS support remains unknown; the control server makes no provider requests.
Inactive, ended, expired, or replacement sessions return `409 session-conflict`.
Account dependency or privilege failure returns `503 dependency-unavailable`
with `dependency: "Accounts"`, rather than claiming an empty account list.

The user's 13 October amendment keeps unfinished inputs and selections in
browser memory. There is no draft API or draft persistence contract. Editing
creates no Redis child record, job, or provider submission. Scenario saving
belongs to the later explicit Simulate and Send workflow in ticket 61.

## Scenario preparation, version 1

`POST /api/test/scenarios/prepare` accepts exactly `session_id` and `inputs`.
`scenarios-v1.ts` defines the editable string fields and immutable response.
The request requires the existing exact Host, Origin, JSON type, and custom
header. Its body limit is 8 KiB. Responses remain private and no-store.
Malformed payloads return `400 invalid-request`. Invalid scenario values return
`400 invalid-scenario` with a bounded `fields` map for inline errors.
Ownership conflicts return `409 session-conflict`; Redis failures return
`503 dependency-unavailable` without claiming preparation succeeded.

Application checks active ownership before validation and after generation.
Domain receives the session's server time and fresh application-supplied
randomness. Preparation writes no Redis child record and publishes no work.
The browser retains the returned event, forecast, replay parameters, and exact
observation array in tab-local memory. It freezes the response recursively.
Changing scenario inputs invalidates preparation. Request identities and
workspace revisions reject older responses, including edits back to the same
values. Tester selection changes preserve preparation. Closure, expiry, and
replacement clear inputs, selection, and preparation. Internal navigation
retains them; reload may discard them.

Probabilities use fractions in the response and percentages in editable inputs.
Quantiles are complete finite ordered values or null, following production
rules. The forecast lasts exactly 86,400,000 milliseconds from event time.
Past anchors generate successors through the earlier of preparation time and
forecast end. Future anchors generate future observations inside that same
forecast window; a later public replay must apply its real-time clock.
Ticket 61 must validate the forecast again before sending.

Local counts are 1–100, background counts are 0–100, and spillover is smaller
than the local count. Spread is 0–100 percent. Magnitude is 1–10 and depth is
0–700 km. Radius must be positive and below the maximum great-circle distance
minus 0.001 km, approximately 20,015.11 km. That geometry bound leaves room
for observations outside the radius. It does not alter production forecasts.
The prototype supplies the illustrative distribution; the values are not
calibrated earthquake predictions. Every observation includes an identity,
time, coordinates, magnitude, depth, location description, and diagram geometry.

The diagram consumes those exact observations without regeneration or a seed.
Randomize replay changes editable settings and requests fresh spatial values.
Prepare scenario also generates a new replay from the edited settings.
No public link, scenario persistence, submission, or provider call exists
in preparation. Ticket 61 must persist the exact reviewed values unchanged.

## Submitted public record, version 1 (ticket 60)

`SubmittedScenarioRecord` in `scenarios-v1.ts` defines the producer contract.
Store one immutable JSON string at
`quakestrike:alert-testing:<session_id>:scenario:<event_id>`.
The envelope contains `version: 1`, `submitted: true`, `submitted_at_ms`,
`event_revision_id`, `forecast_id`, `model_release_id`, and `scenario`.
`scenario` is the exact reviewed `PreparedScenario`, including its observation
identities and values. Do not regenerate observations or replace reviewed values.
Use canonical lowercase UUIDs and millisecond integers. Preserve the session's
original `expires_at_ms`; expire the key at that same deadline with `PEXPIREAT`.
Keep the record below 256 KiB, with at most 200 observations.
Private recipients and delivery records belong in separate session-owned keys.
Public projections ignore unknown fields and never return the raw envelope.

Ticket 61 must atomically validate active ownership and deadline, write once
with no overwrite, and queue the submitted identity. Allocate globally unique
event UUIDs; never reuse an event UUID across sessions. Persist submission,
revision, forecast, and model identities once. The submitted time follows
preparation and precedes the deadline. Validation and queueing are not
implemented by ticket 60. No HTTP route creates fixtures or submits scenarios.

The Backend's `SyntheticScenarioReader.findSubmitted(eventId)` is the read
interface. Its Redis adapter atomically reads the active control hash, checks
Redis time against the deadline, and reads only that session's scenario key.
It never extends expiry, updates lifecycle, scans keys, creates records, or
contacts the private control server. Closed, expired, missing, and unsubmitted
records return absence. Storage outages and corrupt submitted records return
503 because they cannot establish absence. No production fallback exists.

`GET /api/v1/earthquakes/{eventId}?test=true` returns the incumbent detail shape
and `expiresAt`. Synthetic revision/forecast/model UUIDs come from the envelope;
the source URL is the real PHIVOLCS bulletin index. Observation summaries have
no independent forecast. `POST /api/v1/earthquakes/{eventId}/observations?test=true`
accepts `dateFrom`, `dateTo`, optional `limit` (1–100), and optional `cursor`.
The half-open window is at most 24 hours. Pagination uses descending occurrence
time and UUID, matching ordinary search. All saved observation kinds remain
included without distance, location, or magnitude filtering. Readers return
stored future values; the incumbent replay clock hides them until occurrence.
Both routes use `Cache-Control: no-store`, including absence and failures.
Production search remains unchanged and never reads this storage.

## Submission and delivery, version 1 (ticket 61)

| Private POST path | JSON input | Result |
| --- | --- | --- |
| `/api/test/scenarios/submit` | `session_id`, `inputs`, `scenario`, `selected` | Saved identity, queue status, independent channel results. |
| `/api/test/scenarios/history` | `session_id`, optional `page` | Shared submitted scenarios, newest first, 50 per page. |
| `/api/test/scenarios/results` | `session_id`, `event_id` | Saved event and approved recipient projection, or `missing: true`. |

All routes require the incumbent exact private Host/Origin, JSON type, and custom
header. Submission permits 256 KiB; History and Results permit 512 bytes.
Responses remain private and no-store. Validation returns 400; inactive or stale
ownership returns 409; unavailable dependencies return 503 without claiming success.
`delivery-v1.ts` defines the request and result types. `selected` contains 1–500
distinct canonical account UUIDs. Only those identities may become recipients.
History pages are integers from 1 through 10000, clamped to the available pages.
The response includes `page` and `pages`; paging retains earlier forecast links.

New preparation responses contain `preparation_token`, a server-generated HMAC.
The optional TypeScript field preserves compatibility with older public fixtures;
real submission requires a valid token. Submit the exact reviewed scenario and
the input strings used to prepare it. Changing either invalidates the signature.
The server also checks session ownership, preparation time, the original deadline,
and forecast expiry. No draft or preparation record exists in Redis.

The preparation's event UUID identifies the logical request and job. Repeated
identical submissions preserve the submitted envelope and all allocated UUIDs.
A changed selected-ID set cannot reuse that UUID. Lost-response retries retain
one frozen browser request. While its result remains uncertain or queue-pending,
editing and new preparation are blocked. Confirmed validation rejection retains
the reviewed workspace and releases that lock. After successful queue acceptance,
Prepare new replay creates the next deliberate submission identity.

`queue_status: pending` confirms saving only. `enqueued` confirms Stream acceptance,
not provider execution. The immutable public envelope uses the documented key;
private `job:<event>`, `recipients:<event>`, `history`, `outbox`, and `queue` keys share
the session prefix and original deadline. The Stream command contains exactly
`message_version: "1"`, `session_id`, `event_id`, and `job_id` (equal to event ID).
Consumer group recovery and atomic per-account/channel reservations deduplicate
commands. Unavailable queue publication stays pending for repair or identical retry.
The private job contains the original public-envelope JSON for recovery of an
interrupted initial save. Repair never allocates new public UUIDs or overwrites
the submitted key. The outbox index limits each publication-repair pass to 50
pending jobs and removes an entry only after queue acceptance is recorded.

Results expose selected account IDs, display names, masked destinations, channel,
status, and a bounded explanation. Complete destinations, coordinates, content,
provider references, and attempt tokens remain server-side. Pending means no
attempt started; skipped explains current eligibility; failed means explicit
rejection. Accepted confirms provider submission only. An authorized but
interrupted attempt is unknown and cannot be resent automatically. Delivered
requires later provider evidence, implemented by ticket 62.

The control server serves a static Results shell at `/results/<eventId>`.
History and Results remain separate Astro pages using the accepted prototype's
desktop table and stacked mobile outcomes. See ADR 0050 for the bounded
authorization grace and late-write rules.
