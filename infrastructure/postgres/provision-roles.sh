#!/bin/sh
set -eu

case "${1:-}" in
  create)
    if psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv migration_password MIGRATION_DB_PASSWORD
\getenv worker_password WORKER_DB_PASSWORD
\getenv database_name POSTGRES_DB
SELECT format('CREATE ROLE quakestrike_migration LOGIN PASSWORD %L', :'migration_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_migration') \gexec
SELECT format('CREATE ROLE quakestrike_worker LOGIN PASSWORD %L', :'worker_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_worker') \gexec
ALTER ROLE quakestrike_migration PASSWORD :'migration_password';
ALTER ROLE quakestrike_worker PASSWORD :'worker_password';
GRANT CONNECT ON DATABASE :"database_name" TO quakestrike_migration, quakestrike_worker;
GRANT CREATE ON DATABASE :"database_name" TO quakestrike_migration;
GRANT USAGE, CREATE ON SCHEMA public TO quakestrike_migration;
GRANT USAGE ON SCHEMA public TO quakestrike_worker;
SELECT format('ALTER TABLE %I.%I OWNER TO quakestrike_migration', schemaname, tablename)
FROM pg_tables
WHERE schemaname = 'public'
  AND tableowner <> 'quakestrike_migration'
  AND tablename IN (
    'alembic_version', 'ingestion_runs', 'ingestion_run_inputs',
    'earthquake_events', 'earthquake_bulletin_event_identities',
    'earthquake_event_revisions', 'model_releases', 'prediction_jobs',
    'prediction_attempts', 'forecasts', 'alert_jobs', 'audit_logs',
    'job_dispatches', 'maintenance_runs'
  ) \gexec
SELECT format('ALTER TYPE %I.%I OWNER TO quakestrike_migration', n.nspname, t.typname)
FROM pg_type AS t
JOIN pg_namespace AS n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typtype = 'e'
  AND pg_get_userbyid(t.typowner) <> 'quakestrike_migration'
  AND t.typname IN (
    'ingestion_run_status', 'prediction_job_status', 'dispatch_status',
    'prediction_attempt_status', 'alert_job_status', 'maintenance_run_status'
  ) \gexec
SQL
    then
      echo '{"action":"provision-db-roles","status":"ready"}'
    else
      echo '{"action":"provision-db-roles","status":"failed","reason":"role_provisioning_failed"}'
      exit 2
    fi
    ;;
  grant-worker)
    if psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
GRANT SELECT ON TABLE alembic_version, model_releases TO quakestrike_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE
    ingestion_runs, ingestion_run_inputs, earthquake_events,
    prediction_jobs, prediction_attempts, job_dispatches
TO quakestrike_worker;
GRANT SELECT, INSERT ON TABLE
    earthquake_bulletin_event_identities, earthquake_event_revisions,
    forecasts, alert_jobs, audit_logs
TO quakestrike_worker;
SQL
    then
      echo '{"action":"grant-worker","status":"ready"}'
    else
      echo '{"action":"grant-worker","status":"failed","reason":"worker_grant_failed"}'
      exit 2
    fi
    ;;
  create-observer)
    if [ -z "${OBSERVER_DB_PASSWORD:-}" ]; then
      echo '{"action":"create-observer","status":"failed","reason":"missing_observer_password"}'
      exit 2
    fi
    if psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv observer_password OBSERVER_DB_PASSWORD
\getenv database_name POSTGRES_DB
SELECT format('CREATE ROLE quakestrike_observer LOGIN PASSWORD %L', :'observer_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_observer') \gexec
ALTER ROLE quakestrike_observer PASSWORD :'observer_password';
ALTER ROLE quakestrike_observer SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"database_name" TO quakestrike_observer;
GRANT USAGE ON SCHEMA public TO quakestrike_observer;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO quakestrike_observer;
ALTER DEFAULT PRIVILEGES FOR ROLE quakestrike_migration IN SCHEMA public
  GRANT SELECT ON TABLES TO quakestrike_observer;
SQL
    then
      echo '{"action":"create-observer","status":"ready"}'
    else
      echo '{"action":"create-observer","status":"failed","reason":"role_provisioning_failed"}'
      exit 2
    fi
    ;;
  create-maintenance)
    if psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv database_name POSTGRES_DB
SELECT 'CREATE ROLE quakestrike_backup LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_backup') \gexec
SELECT 'CREATE ROLE quakestrike_maintenance LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_maintenance') \gexec
ALTER ROLE quakestrike_backup NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD NULL;
ALTER ROLE quakestrike_maintenance NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS PASSWORD NULL;
GRANT CONNECT ON DATABASE :"database_name" TO quakestrike_backup, quakestrike_maintenance;
GRANT pg_read_all_data TO quakestrike_backup;
GRANT USAGE ON SCHEMA public TO quakestrike_maintenance;
GRANT SELECT, INSERT, UPDATE ON maintenance_runs TO quakestrike_maintenance;
SQL
    then
      echo '{"action":"create-maintenance","status":"ready"}'
    else
      echo '{"action":"create-maintenance","status":"failed","reason":"role_provisioning_failed"}'
      exit 2
    fi
    ;;
  *)
    echo 'Usage: provision-roles.sh create|grant-worker|create-observer|create-maintenance' >&2
    exit 2
    ;;
esac
