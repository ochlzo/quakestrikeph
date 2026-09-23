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
if either consumer failed during startup. For this local release path, Beat has
no automatic restart policy: after a stack restart the operator checks consumer
health and enables it again. This is the local exception to the general long-running-container
restart policy in the architecture specification. Dispatcher and Data Ingestor
retain automatic restart and durable recovery.

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
