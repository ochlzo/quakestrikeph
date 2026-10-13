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
