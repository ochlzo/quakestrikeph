# Protect the Operations Console with Cloudflare Access and direct server-side reads

**Status**: accepted

The Operations Console is a separate Astro application behind a dedicated
Cloudflare Access application on its HTTPS hostname. Access is the sole
authority for operator admission: its policy allows named Google identities,
requires independent MFA on every new login, and limits the application
session to eight hours. Do not offer email one-time PIN or a bypass policy for
the Console. Operators can use a phone or another device through its browser
after that device completes the same Access login. The public Bulletin and
Backend routes do not inherit the Console policy.

Cloudflare Tunnel and Traefik route only the protected Console hostname to its
server. Every Console page and data request verifies the signed
`Cf-Access-Jwt-Assertion` application token, including signature, issuer,
audience, and expiry, before using the identity. The origin uses the verified
Access `sub` and email for audit records; it never trusts a bare identity
header or browser-supplied actor. The Console has no Clerk login, local
operator roles, or application-managed whitelist. Remove the planned
`user_role_assignments`, `operations_viewer`, `access_administrator`, and
Backend role-administration paths. Public `users` remain separate Clerk-backed
Bulletin accounts and cannot grant Console access.

The Console server performs bounded, parameterized PostgreSQL reads with a
dedicated database role. It has `SELECT` only on the approved operational
tables and linked event context named in the database contract, plus narrow
`INSERT` and `SELECT` grants on `operator_access_events`. It has no business
table write or schema grants, queue publisher, Docker socket, arbitrary SQL
screen, general table browser, export, retry, or maintenance control. Browser
code never receives database credentials or opens a database connection.
The shared Backend keeps public information and account mutations, but no
Console operations API is needed. Console server handlers are part of the
Console application, not a public Backend API.

The first Console screens cover ingestion runs and checkpoints, source catalog
evidence, dispatch and prediction work, forecasts and model releases, alert
jobs and delivery evidence, business audits, selected technical logs,
maintenance results, and Bulletin users. Linked earthquake events and
revisions supply context. The Users screen has a paginated list and lookup by
user ID or partial phone number. Operational status is visible; name, email,
phone, and saved alert location are hidden until an explicit reveal. A reveal
returns only requested
fields after the operator supplies a reason. All Access-allowed operators may
reveal. Do not pre-render hidden values in HTML or browser state. No bulk
export is provided.

The Console records a verified operator, time, route template, and selected
record ID for each page load and detail open. It records the field category
and operator-entered reason for a sensitive reveal, never the value or a raw
search query. Page visits, detail opens, and reveals must be committed before
their protected data is returned; audit failure denies that response.
Background polling and filter changes do not create page-visit events. Keep
these events for 180 days with bounded cleanup. Cloudflare's authentication
logs remain the evidence for login attempts, including denials at Access.
Active run and log screens may poll about every 30 seconds while open; other
screens use manual refresh and show the last successful refresh time. A run
may retain its summary after its ingestion checkpoints expire, so the
Console must show expired detail as unavailable, not as an empty run.

The separate pgAdmin path in [ADR 0029](0029-private-production-database-browser.md)
remains available through Tailscale for emergency read-only investigation if
the Console or Access is unavailable. It is not an Access bypass for the
Console. This decision changes the intended architecture and database
contract; it does not claim that the planned web applications or roles have
already been implemented.

References: [Cloudflare Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/),
[independent MFA](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/mfa-requirements/).
