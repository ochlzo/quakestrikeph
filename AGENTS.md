# QuakeStrike PH agent instructions

QuakeStrike PH is a Philippine earthquake information, forecasting, and alert platform.

## Start here

- Read [README.md](README.md) for the repository map and local setup.
- Read [PRODUCT.md](PRODUCT.md) for product scope and implementation status.
- Before changing domain behavior or workflows, read [GLOSSARY.md](GLOSSARY.md) for terms and rules.

## Choose the relevant reference

Read the matching reference before changing the related area.

| Task | Reference |
| --- | --- |
| Change behavior, architecture, dependencies, data, queues, runtime, deployment, or interfaces | Relevant accepted records in [docs/adr/](docs/adr/) |
| Change interface layout, styling, or interaction | [DESIGN.md](DESIGN.md) |
| Change module boundaries, ownership, authentication, integrations, deployment architecture, or data flows | [Architecture specification](docs/system-design/ARCHITECTURE/ARCHITECTURE.md) |
| Change tables, types, constraints, indexes, transactions, retention, or data ownership | [Database design](docs/system-design/ERD/DATABASE-DESIGN.md) |
| Run, deploy, diagnose, or maintain services and databases | [Operations index](docs/operations/README.md) |
| Select checks or prepare a branch, commit, push, or pull request | [CONTRIBUTING.md](CONTRIBUTING.md) |

## Essential rules

- Follow relevant accepted ADRs unless a later ADR replaces the decision.
- Ignore `docs/system-design/ARCHITECTURE/system-architecture-layers.png`, `docs/system-design/ERD/ERD.png`, and all PNGs under `docs/system-design/CFD-DFD/`; they are stale.
- Use the written architecture specification, database design, and relevant accepted ADRs for design contracts.
- Verify implemented behavior in source. Written specifications, the glossary, and ADRs describe intended design; they do not prove implementation.
- Identify implementation deviations. Preserve documented ownership and security rules unless the design is intentionally changed.
- Before pushing any change, follow `CONTRIBUTING.md` for required checks and contribution conventions.

When changing PostgreSQL, Redis, bootstrap, ingestion, or dispatch behavior:

1. Run the isolated integration suite documented under [Local setup for contributor checks](CONTRIBUTING.md#local-setup-for-contributor-checks).
2. Use the documented `quakestrike-data-ingestion-test` Compose project. Fixtures migrate and truncate data; never use a development or production database.
3. Confirm the pytest summary shows integration tests ran. Host pytest skips them without the test database and Redis URLs.

If Docker is unavailable, report the integration suite as unverified and include the Docker error.
