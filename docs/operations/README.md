# Team operations

Choose the task you need. Each guide contains prerequisites, commands, checks, and supporting reference details.
The [visual operations handbook](pretty-operations-documentation.html) presents selected workflows for teammates who prefer a visual page.
Its current coverage is Docker.

## Start or develop locally

| Task | Guide |
| --- | --- |
| Start Bulletin and the Backend; initialize or operate workers | [Local runtime](local-runtime.md) |
| Configure accounts and run account checks | [Bulletin accounts](bulletin-accounts.md) |
| Run unit tests, integration tests, or checks before pushing | [Contributor checks](../../CONTRIBUTING.md#local-setup-for-contributor-checks) |
| Preview private alert testing with disposable data | [Private alert testing](alert-testing.md#local-browser-acceptance-with-disposable-redis) |

## Deploy or maintain the VPS

| Task | Guide |
| --- | --- |
| Understand CI or deploy a tested release | [CI and deployment](continuous-deployment.md) |
| Set up, verify, or recover the Backend | [Backend API](backend-api.md) |
| Change database passwords or open private pgAdmin | [Database maintenance](database-maintenance.md) |
| Configure backups or check a restore test | [PostgreSQL backups](postgres-backups.md) |
| Install or check checkpoint cleanup | [Checkpoint retention](ingestion-checkpoint-retention.md) |
| Recover forecasts for a selected historical run | [Historical prediction recovery](historical-prediction-recovery.md) |

## Operate alerts

| Task | Guide |
| --- | --- |
| Activate, stop, or recover ordinary alert delivery | [Alert runtime](alert-runtime.md) |
| Check provider evidence and remaining verification limits | [Forecast alert verification](forecast-alert-verification.md) |
| Diagnose SMS acceptance, delivery, or charging evidence | [IPROG delivery](iprog-alert-delivery.md) |
| Set up or operate the private testing tool | [Private alert testing](alert-testing.md) |

## Read commands correctly

- **Local** means your development machine. PowerShell commands start at the repository root unless a step specifies another folder.
- **VPS** means the production server. Bash commands start at `/srv/quakestrikeph` unless a step specifies another folder.
- **Disposable tests** use the separate `quakestrike-data-ingestion-test` Compose project. Its fixtures migrate and truncate test data.
- A **tested SHA** is the full Git commit ID whose required checks passed.
- Replace values such as `<run-uuid>` before running a command.
- Stop a command sequence when a command fails. Read the error before continuing.

Local Bulletin and workers share the `infrastructure` Compose project, PostgreSQL, and Redis.
Stop only the services needed for your task. Removing shared data services also interrupts other local applications.

Keep credentials, model weights, source snapshots, and generated readiness manifests outside Git.
Follow each guide's conditions before database changes, production activation, or real provider sends.

## Use the right reference

The Markdown guides contain the complete operating procedures and verification limits.
The HTML guide presents selected workflows visually; its scope currently covers Docker.
Use [the repository map](../../README.md) to find implementation and system design documents.
