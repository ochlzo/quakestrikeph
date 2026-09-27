# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- The general public in the Philippines, across age groups, checking a recent earthquake and its forecast.
- Emergency response personnel who also need earthquake and forecast information through the public Bulletin. Their specific response workflow and information needs remain to be defined.
- Authorized operators use the separate Operations Console to inspect ingestion, prediction, alert, audit, and maintenance records.

## Product Purpose

QuakeStrike PH helps people understand recent earthquakes and their forecasts. It brings PHIVOLCS bulletins, reconciled event history, and model forecasts into a public Bulletin. People can read public earthquake information without an account. Planned personal accounts let people explicitly choose email and SMS alerts and set an observed-magnitude threshold with an optional nearby-only rule.

The public job is to help readers understand what was observed, what the model estimates as probabilities, and when that forecast applies. The forecast is not an exact prediction. The separate Console supports inspection of the system's processing and delivery evidence.

## Positioning

QuakeStrike PH connects source-linked PHIVOLCS observations and their corrections to versioned prediction inputs, traceable forecasts, and optional personal alerts. Observed earthquake details and model forecasts must remain clearly distinct.

## Operating Context

- Public readers may arrive immediately after an earthquake and need the latest available event details and forecast. Public reading never requires sign-in.
- A forecast window begins at the observed event time and ends 24 elapsed hours later. Its end must be communicated in Philippine time; it is not a fresh 24-hour period from the time someone views or receives it.
- A later PHIVOLCS correction can revise an event while preserving its event identity. Readers need to distinguish corrected observations from the earlier report.
- Bulletin accounts use Clerk email/password or Google sign-in for alert settings. Email and SMS are independent, explicit opt-ins. SMS also requires a verified phone and current network support.
- Console operators use a separate Cloudflare Access identity with MFA. The Console is an inspection surface with audited access to sensitive fields.

## Capabilities and Constraints

- Implemented: PHIVOLCS ingestion and event revision history, prediction jobs and forecasts, PostgreSQL and Redis worker flows, and read-only Backend event and forecast routes. The Bulletin currently has only an Astro/React scaffold.
- Planned: Bulletin data and account screens, Operations Console, automatic email and SMS delivery, and production monitoring. Do not present planned capabilities as live.
- The approved public web stack is Astro, React, and TypeScript. The public Bulletin reads through the Backend API; the Console is a separate application with restricted server-side database reads.
- Present forecasts as uncertain probabilities, never as exact predictions or with unverified accuracy claims. User-facing forecast language should say **further earthquake activity**, without calling predicted events confirmed aftershocks. Forecast probabilities must not imply a geographic area until the model target area is established and stated.
- An alert is tied to a current, unexpired live forecast for an observed event. Alert creation, provider acceptance, and delivery are different states. The intended alert message identifies the observed event before its forecast.
- The specific emergency response workflow, any role-specific Bulletin features, and the model forecast's geographic target area remain open decisions.

## Brand Commitments

- Product name: QuakeStrike PH. Public application name: QuakeStrike PH Bulletin. Operator application name: Operations Console.
- No approved visual identity, logo, typography, or palette is documented in the current Bulletin scaffold.

## Evidence on Hand

- `CONTEXT.md` defines the domain language; accepted records in `docs/adr/` and the repository specifications define intended behavior.
- PHIVOLCS bulletins are the observation source. The repository includes a versioned `SEIS 1.0.1` prediction runtime contract and model verification workflow; model artifacts are kept outside Git.
- The current Bulletin page contains only its title. The repository has no approved testimonials, public performance claims, or marketing proof assets to use as product claims.

## Product Principles

1. Make earthquake information understandable to the general public across age groups, including emergency response personnel, without requiring an account.
2. Separate observed source facts, corrections, and model forecasts so readers can understand each on its own terms.
3. Show the forecast's original time window and provenance clearly, and avoid geographic claims the evidence does not support.
4. Make alert enrollment a deliberate choice for each channel, with honest eligibility and delivery states.
5. Keep public reading and restricted operational inspection as distinct experiences.

## Accessibility & Inclusion

The public Bulletin must be usable by people across age groups. Explain observed events and forecast probabilities in plain language, with clear separation between established facts and uncertain estimates. A specific accessibility standard has not yet been established.
