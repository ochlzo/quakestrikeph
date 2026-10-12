# Database initialization

This directory contains explicit database setup and release preparation scripts.
Compose mounts this directory at `/opt/quakestrike` in PostgreSQL containers.

- `provision-roles.sh` provisions the existing restricted database roles and grants.
- `create-observer.py` provisions the private read-only observer through Compose.
- `prepare-release-database.sh` applies reviewed migrations and grants during deployment.

The worker CLI owns model release registration, verification, bootstrap, and readiness checks.
Those commands use the existing worker Application and Infrastructure layers.
Their implementation stays in `workers/src/quakestrike/`.

Follow the [local runtime guide](../../docs/operations/local-runtime.md) for initial setup.
Follow the [deployment guide](../../docs/operations/continuous-deployment.md) for repeat releases.
Follow the [database maintenance guide](../../docs/operations/database-maintenance.md) for observer access.

Migrations use `database/alembic.ini` and `database/migrations/`.
Worker images build from the repository root and retain the same directory relationship.
Service startup only checks readiness; it never applies migrations or imports history.
