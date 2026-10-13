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

Hosting and storage decisions: [ADR 0050](../../../docs/adr/0050-private-alert-testing-session-runtime.md).

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
