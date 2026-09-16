# Standardize the first worker runtime and operational mechanics

**Status**: accepted

The first worker implementation uses Python 3.12 with a `pyproject.toml` and a
locked dependency set. Application persistence uses synchronous SQLAlchemy 2
with hand-reviewed Alembic migrations. Domain code remains independent of
both libraries.

The Scheduler module has one Beat process that creates durable pending runs.
A separate long-lived dispatcher claims pending `job_dispatches` rows from
PostgreSQL and publishes stable job identifiers to Redis. Beat does not publish
directly. Celery handlers use at-least-once delivery with late acknowledgement,
worker-loss rejection, database processing leases, and idempotent claims.
Celery result storage is not the source of job state; PostgreSQL is.

The history bootstrap is an explicit, resumable CLI operation that runs after
migrations and before Beat is enabled. Tests use deterministic PHIVOLCS
fixtures and local PostgreSQL/Redis integration services. Continuous
integration does not depend on the live PHIVOLCS website.
