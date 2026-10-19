# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Public readers in the Philippines who check recent earthquakes and forecasts without signing in.
- Bulletin account holders who manage personal email/SMS alerts, a magnitude threshold, and an optional nearby-only rule.
- Emergency response personnel who use the public Bulletin. Their specific response workflow and role-specific needs remain undefined.
- Authorized test operators who use the separate private alert-testing tool with selected Bulletin accounts.
- Intended Console operators who inspect processing, delivery, audit, and maintenance records. The Operations Console remains planned.

## Product Purpose

QuakeStrike PH brings PHIVOLCS observations, event history, and model forecasts into a public Bulletin.
Readers can inspect an earthquake, follow its source, and open its forecast without an account.
Account holders can choose email and SMS alerts independently and control when an observed earthquake qualifies.

The Bulletin separates observed facts from uncertain model estimates.
A forecast describes possible further earthquake activity; it does not predict an exact earthquake.
Private alert testing supports controlled synthetic scenarios. The planned Console supports inspection of ordinary system records.

## Positioning

QuakeStrike PH connects source-linked observations and corrections to versioned model inputs, traceable forecasts, and optional personal alerts.
Observed earthquake details, model estimates, and delivery evidence have separate meanings and presentations.

## Operating Context

- Readers may arrive immediately after an earthquake and need the latest available source details and forecast.
- Public reading never requires sign-in. Clerk email/password or Google sign-in protects personal account settings.
- A forecast starts at the observed event time and ends 24 elapsed hours later. Viewing, replaying, or receiving it does not restart that window.
- Forecast pages show the original window in Philippine time. New alert messages link to the forecast page and omit the explicit window line.
- PHIVOLCS corrections preserve the event identity while adding revisions. Public reads use the latest revision's available forecast for the configured model release.
- Email and SMS require separate opt-ins and verified destinations. SMS also requires supported sender coverage; verification alone does not enable alerts.
- Nearby-only alerts compare the observed epicenter with a saved alert location. They do not track a device or use the forecast activity radius.
- Private test operators enter through Tailscale. Testers are selected Bulletin accounts; their ordinary channel settings still determine eligibility.
- The planned Console uses separate Cloudflare Access identity with MFA and audited access to sensitive fields.

## Capabilities and Constraints

Implementation status below reflects repository source reviewed on **19 October 2026**.
An implementation does not prove that a deployment or provider is ready.

| Area | Implemented capabilities |
| --- | --- |
| Data pipeline | PHIVOLCS ingestion, event revisions, durable work records, model verification, forecasts, and PostgreSQL/Redis worker flows. |
| Public Bulletin | API-backed earthquake list and interactive map, location/date/magnitude filters, pagination, selection, and PHIVOLCS source links. |
| Forecast pages | Event-specific forecasts, probability explanations, available model outputs, observation replay, and explicit processing/unavailable/failure states. |
| Bulletin accounts | Signup, sign-in, recovery, onboarding, independent channel settings, magnitude threshold, saved alert location, and nearby-only distance. |
| Account security | Phone verification/change/removal, password changes, recent verification for sensitive actions, and signed-in device management. |
| Backend | Public event/forecast reads, authenticated account operations, and restricted delivery callback reconciliation. The Backend is not globally read-only. |
| Ordinary alerts | Automatic alert jobs, frozen message content, email/SMS consumers, reconciliation, health checks, and audited legacy-job retirement. Delivery gates default to disabled. |
| Private alert testing | Shared four-hour sessions, independent autosaved workspaces, synthetic preparation/public preview, selected-account delivery, Results/History, and session cleanup. |
| Operations | Shared local Docker runtime, CI checks, gated application deployment, encrypted PostgreSQL backups, isolated restore tests, and checkpoint retention. |

**Planned or unavailable:** Operations Console, production monitoring, account email change, and account removal.
Email-change and account-removal destinations show unavailable screens; they provide no corresponding account mutation route.

- The public web stack is Astro, React, and TypeScript. Bulletin reads through the Backend API.
- The planned Console remains a separate application with restricted server-side database reads.
- Production deployment and real provider delivery require environment-specific setup and verification. CI deploys only when enabled and required checks pass.
- Ordinary alert activation remains explicit. Private testing uses a separate manual rollout and temporary Redis records.
- Alerts require a current, unexpired live forecast and per-user eligibility. Historical recovery and backfill do not create automatic alerts.
- Alert messages identify the observed earthquake before presenting its forecast. Frozen messages retain their original content; linked pages can show newer information.
- Alert creation, provider acceptance, recorded delivery, and human receipt are distinct. Accepted or uncertain submissions never authorize automatic resend.
- Public forecast language uses **further earthquake activity**. Observations in replay are not necessarily aftershocks of the selected event.
- Forecast probabilities must not imply an unsupported geographic area. An activity radius is not shaking distance, a damage estimate, or a safety boundary.
- Emergency response workflows, role-specific Bulletin features, and the model probability's geographic target area remain open decisions.

## Brand Commitments

- Product name: **QuakeStrike PH**. Public application: **QuakeStrike PH Bulletin**. Planned operator application: **Operations Console**.
- The implemented identity uses a shared Earth-icon mark, QuakeStrike PH wordmark, and application subtitle.
- [DESIGN.md](DESIGN.md) documents the light interface, white surfaces, teal actions, pale teal accents, and Geist Variable typography.
- Shared logo and theme sources live in [packages/ui](packages/ui/). The private testing tool reuses them with an Alert testing subtitle.

## Evidence on Hand

- [GLOSSARY.md](GLOSSARY.md) defines product and workflow terms. Repository specifications describe intended behavior; source files establish implementation.
- [Bulletin source](apps/quakestrikeph-bulletin/src/) contains the map/list interface, forecast pages, replay, and account screens.
- [Backend source](apps/backend-api/src/) contains public reads, account operations, and callback handling.
- [Private testing source](apps/quakestrikeph-alert-testing/src/) and [its Python module](workers/src/quakestrike/alert_testing/) implement synthetic testing.
- PHIVOLCS supplies observations. The versioned `SEIS 1.0.1` runtime verifies the model manifest and artifact hashes; model artifacts remain outside Git.
- [Operations guides](docs/operations/README.md) record setup, checks, recovery procedures, and provider verification limits.
- Recorded provider observations do not establish readiness for another environment or release. No approved testimonials or public performance claims are established here.

## Product Principles

1. Make public earthquake information understandable across age groups without requiring an account.
2. Separate source observations, corrections, and model forecasts.
3. Explain the original forecast window and uncertainty without unsupported geographic or accuracy claims.
4. Make each alert channel a deliberate choice and report eligibility and delivery states honestly.
5. Keep public reading, personal settings, private synthetic testing, and planned operational inspection distinct.

## Accessibility & Inclusion

Use plain language and clear labels for observations, probabilities, and unavailable information.
Support desktop and mobile layouts, keyboard operation, visible focus, readable contrast, and reduced motion.
Do not rely on map color alone to communicate earthquake or forecast information.
The repository does not yet establish a specific accessibility conformance standard or a completed conformance audit.
