# Isolate private alert testing and its temporary Redis session

**Status**: accepted implementation decision within issues 56 and 57, 13 October 2026.

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
