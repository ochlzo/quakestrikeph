# IPROG forecast delivery

The SMS adapter uses the server-only `IPROG_API_TOKEN` setting.
The adapter sends ordinary messages through the existing shared sender.
Network checks permit known Globe/TM and DITO results under ADR 0042.
Smart/TNT is excluded. Unknown support defers resolution or skips sending.
Successful phone verification does not prove ordinary sender support.

Ticket 49 provides the submission and polling boundaries.
The normal Alert Worker does not enable ordinary submission merely because the token exists.
Runtime activation, health checks and rollout belong to ticket 51.
Unrestricted delivery requires the separate rollout gate.
Shared database migrations and live messages remain separately authorized.

## Submission evidence

The adapter makes one POST with a fixed HTTPS endpoint, JSON credentials and frozen text.
Redirects and internal submission retries are disabled.
Connect and read timeouts are three and eight seconds.
The lifecycle records a sending attempt before the external request.

Numeric body status 200 and a usable message ID establish acceptance.
String OTP success does not establish ordinary SMS acceptance.
Acceptance does not establish delivery.
The documented combined invalid-token/no-balance rejection remains one permanent category.
An explicit HTTP rate-limit rejection uses validated Retry-After timing.
Generic server failures, malformed acceptance and transport uncertainty remain unknown.
Unknown submissions never authorize automatic resend.

Frozen content retains the full forecast URL, whitespace and QuakeStrike PH header.
The local segment estimate uses GSM-7 default and extension characters or UTF-16 code units.
The adapter never truncates required content.
Provider-added text, encoding changes and charging differences remain unverified.

## Reconciliation

`poll_iprog_deliveries` selects accepted or unknown IPROG attempts with known message IDs.
The caller retains `next_after` across bounded passes and wraps when the page is exhausted.
This cursor prevents persistent pending records from starving later candidates.
A process restart safely begins another sweep from PostgreSQL evidence.
The cursor does not provide send authority or change the schema.

The default page permits 20 polls within a 240-second execution budget.
The caller can use a smaller page or deadline.
The adapter constructs status requests from the fixed endpoint and stored ID.
Returned credential-bearing links are never followed or logged.
Pending establishes acceptance, completed establishes delivery, and failed records terminal provider failure.
Polling failures preserve the previous durable outcome.

Recipient and attempt outcomes commit atomically.
Duplicate or older responses cannot regress delivered evidence.
Late outcomes remain eligible after forecast expiry.
Late delivery does not reopen the job or dispatch.
Unknown records without references remain unknown and make no status request.
Periodic job maintenance remains necessary when polling has no candidates or fails.

The documented status response has no verified event timestamp.
`provider_status_at` remains null when timestamp evidence is unavailable.
Local delivery observation supplies `delivered_at` without claiming the exact handset receipt time.

## Safe diagnostics and controlled checks

Diagnostics retain operation, numeric HTTP/body codes, normalized errors and bounded timing.
They exclude destinations, tokens, message text, response prose and credential-bearing URLs.
`charging_units` retains documented `sms_rate` credit evidence.
`provider_sms_count` retains the separate numeric `sms_count` value.
SMS count does not establish billed segments or credits.
Controlled checks must compare both values with the received message and account evidence.

Before activation, verify the header appears exactly once on designated test destinations.
Verify sender behavior, full-link navigation, received text, delivery reconciliation and observed charging.
Simulate credential, credit and rate-limit failures without exhausting real credits.
Automated tests use injected responses and never contact live providers.

References: [IPROG API](https://www.iprogsms.com/api/v1/documentation),
[provider guide](https://www.iprogsms.com/blog/building-sms-notifications-into-your-app-developers-guide),
[ADR 0047](../adr/0047-forecast-alert-content-and-delivery-evidence.md).
