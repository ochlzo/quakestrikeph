# Enable the local runtime through separate operator actions

**Status**: accepted

The local release path uses Compose. Migrations, SEIS 1.0.1 registration,
read-only release verification, historical bootstrap, and readiness are
separate operator commands. Dispatcher, Data Ingestor, and Beat have distinct
service commands. None of their startup paths performs initialization writes.
The operator explicitly provisions separate migration and worker database
roles before migration and grants only the worker table permissions needed by
the current runtime afterward. Init actions use the migration credential;
runtime containers receive only the worker credential. Team-built containers
carry a tested Git commit SHA image tag. The local build action checks that
the source checkout is clean and matches the configured SHA, and never
overwrites an existing tag. The previous tested image is kept for rollback.

The operator starts Dispatcher and Data Ingestor individually and waits for
service-specific health checks before enabling Beat. Beat is behind an explicit
Compose profile. Compose enforces their healthy dependencies when starting Beat;
the enable command checks them again after Beat becomes healthy and stops Beat
if either consumer failed during startup. Beat uses `restart: unless-stopped`
after initial enablement, as described in the amendment below. Dispatcher and
Data Ingestor retain automatic restart and durable recovery.

Worker health checks verify PostgreSQL, Redis, and migration state. The
Dispatcher records a local scan marker with its process ID only after a
successful scan; Data Ingestor health verifies ingestion-queue consumption.
The immediate-poll command runs in the Dispatcher container and checks that
the marked process is still alive before writing a run. Beat has its
own readiness health check, which Compose waits for when the operator enables
it. These health signals are operational metadata, not business records.

Beat uses UTC Unix-epoch-aligned boundaries for the configured poll interval.
Its first tick is strictly after startup, even if startup lands exactly on a
boundary. Missed boundaries are not replayed. An explicit immediate-poll
command requires runtime readiness and healthy consumers, then creates or
reuses the existing durable ingestion run and dispatch. It never shifts Beat's
schedule. If scheduled or manual work is already active, the command reports
the existing run and dispatch IDs and original trigger type.

Operator actions emit bounded structured results. PostgreSQL records remain
the durable work evidence; the ignored local readiness manifest retains
bootstrap and release proof. No additional report table or file is introduced.

## Amendment: retain an enabled Beat schedule after restart — 20 October 2026

This amendment replaces the original requirement that Beat have no automatic restart policy.
The shared release Compose file uses `unless-stopped` for Beat in both local and VPS runtimes.
An already-enabled Beat restarts after an unexpected process exit or Docker daemon restart.
An explicitly stopped Beat remains stopped until the operator enables it again.
The named profile and initial consumer-health checks remain required for first enablement.

Docker restarts do not rerun the Compose dependency checks or the enable helper.
Beat still evaluates its read-only startup gates on each process start.
Those gates check configuration, database migrations, model release, bootstrap evidence, PostgreSQL, and Redis; they do not prove consumer health.
Operators verify consumer health after recovery. Durable work records retain work while consumers recover.
Beat resumes at the next future UTC boundary and does not replay missed schedule ticks.
Routine deployment still preserves whether Beat was running before the release, under ADR 0049.
