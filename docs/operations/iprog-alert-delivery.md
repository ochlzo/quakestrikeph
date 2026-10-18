# Check IPROG SMS delivery

Use this reference when SMS submission, delivery polling, or charging evidence needs investigation.
For activation commands, use [alert runtime](alert-runtime.md). A configured token alone does not enable delivery.

| Observation | Meaning or next check |
| --- | --- |
| Numeric body status 200 and usable message ID | Accepted for submission; receipt remains unverified. |
| Pending poll result | Provider acceptance. |
| Completed poll result | Provider delivery evidence. |
| Failed poll result | Terminal provider failure. |
| Unknown result with a message ID | Preserve the result; reconcile using the retained reference. |
| Unknown result without a message ID | Preserve uncertainty; do not resend automatically. |
| Verified phone but unsupported sender network | Phone verification does not establish ordinary sender support. |

The server-only `IPROG_API_TOKEN` selects the existing shared sender.
Known Globe/TM and DITO results are supported. Smart/TNT is excluded; unknown support defers resolution or skips sending.
Live messages and shared database changes require approval for the specific environment.

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

Frozen content retains the full forecast URL and whitespace. New SMS snapshots omit the application header because the provider template supplies branding.
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

Before activation, verify branding appears exactly once on the approved destination.
Verify sender behavior, full-link navigation, received text, delivery reconciliation and observed charging.
Simulate credential, credit and rate-limit failures without exhausting real credits.
Automated tests use injected responses and never contact live providers.

References: [IPROG API](https://www.iprogsms.com/api/v1/documentation),
[provider guide](https://www.iprogsms.com/blog/building-sms-notifications-into-your-app-developers-guide).
