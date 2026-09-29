# QuakeStrike PH agent instructions

## Read first: repository context and ADRs

Read `CONTEXT.md` before working on the related domain behavior or workflow.
It defines the terms and rules used by the current implementation.

Read the relevant records in `docs\adr\` before changing behavior, architecture,
dependencies, data, queues, runtime, deployment, or interfaces. ADRs are
binding decisions for this repository. Follow them unless a later ADR replaces
the decision.

Before pushing any change, follow `CONTRIBUTING.md` for checks, branch, commit,
and pull request conventions. Use `docs/operations/local-runtime.md` when
enabling or maintaining the full worker runtime, and
`docs/operations/database-maintenance.md` for database passwords or private
production database access.

## Integration tests

When changing PostgreSQL, Redis, bootstrap, ingestion, or dispatch behavior,
run the isolated integration suite using the three Compose commands in
`CONTRIBUTING.md` under "Local setup for contributor checks". The Compose
`test-runner` sets `TEST_DATABASE_URL` and `TEST_REDIS_URL`; running pytest on
the host without those variables skips integration tests. Confirm the pytest
summary shows the integration tests ran.

Use the documented `quakestrike-data-ingestion-test` Compose project. The test
fixtures migrate and truncate its database, so never point `TEST_DATABASE_URL`
at a development database. If Docker is unavailable, report the integration
suite as unverified with the Docker error.

## Project

This repository is the implementation target for QuakeStrike PH, a Philippine
earthquake information, forecasting, and alert platform. The current code
ingests and reconciles PHIVOLCS bulletins, stores events and processing records,
and generates forecasts with approved Python model artifacts. The public web
apps, Backend API, automatic SMS delivery, and production monitoring remain
planned. See `README.md` for the current scope and repository map.

The planned system has two web applications—QuakeStrike PH Bulletin and
Operations Console—a Backend API, and background workers for scheduling,
PHIVOLCS ingestion, prediction, and alert delivery.
The system-level architecture is client-server. Backend and worker code uses
Interface, Application, Domain, and Infrastructure layers within a monorepo;
these are code boundaries, not separate physical tiers.

The baseline technology and runtime decisions are Astro/React/TypeScript for
the web applications, Node.js/Express/TypeScript for the Backend, Python for
the prediction worker, PostgreSQL for durable application/audit/run/job/
delivery records and selected technical logs, Redis for background work,
Clerk for identity, and Cloudflare Tunnel plus Traefik at the public edge.
Deployable modules run in separate Docker containers on one VPS.

## Design references

Before changing architecture, module boundaries, data ownership, database
schema, authentication/roles, integrations, deployment, or data flow, consult
the relevant repository design material:

- Read `docs\system-design\ARCHITECTURE\ARCHITECTURE.md` for the intended
  monorepo, module ownership, dependency direction, technology stack,
  containers, networks, security, logging, maintenance, and deployment rules.
- Use `docs\system-design\ARCHITECTURE\system-architecture-layers.png` as the
  visual system and layered architecture diagram. The written specification
  and ADRs control when the diagram omits detail.
- Read `docs\system-design\ERD\DATABASE-DESIGN.md` before changing tables,
  PostgreSQL types, constraints, indexes, transactions, retention, or data
  ownership. It is the authoritative database contract.
- Use `docs\system-design\ERD\ERD.png` to inspect entity relationships. The
  database design document controls exact fields and rules when the diagram is
  less specific.
- Use `docs\system-design\CFD-DFD\CFD.png` for the system boundary and flows
  between QuakeStrike PH and external actors or systems.
- Use `docs\system-design\CFD-DFD\DFD-Level1.png` for the top-level processes,
  data stores, and flows across the platform.
- Use `docs\system-design\CFD-DFD\DFD-Level2_P1.png` through
  `DFD-Level2_P8.png` for the detailed decomposition of each Level 1 process.
  Consult the matching Level 2 diagram when changing that process or its data
  flow.

The repository specifications, diagrams, `CONTEXT.md`, and accepted ADRs
describe intended design; they do not prove that behavior is implemented. If
implementation must deviate, identify the deviation and preserve documented
ownership and security rules unless the design is intentionally changed.

Original design provenance remains under
`C:\Projects\SAM_Capstone\capstone`. Consult it only when repository documents
or ADRs point there for historical rationale. Repository specifications and
accepted ADRs control implementation.
