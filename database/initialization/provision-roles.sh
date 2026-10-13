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
    'source_catalog_evidence',
    'earthquake_events', 'earthquake_bulletin_event_identities',
    'earthquake_event_revisions', 'model_releases', 'prediction_jobs',
    'prediction_attempts', 'forecasts', 'alert_jobs', 'alert_recipients',
    'alert_delivery_attempts', 'audit_logs',
    'job_dispatches', 'maintenance_runs', 'users'
  ) \gexec
SELECT format('ALTER TYPE %I.%I OWNER TO quakestrike_migration', n.nspname, t.typname)
FROM pg_type AS t
JOIN pg_namespace AS n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
  AND t.typtype = 'e'
  AND pg_get_userbyid(t.typowner) <> 'quakestrike_migration'
  AND t.typname IN (
    'ingestion_run_status', 'prediction_job_status', 'dispatch_status',
    'prediction_attempt_status', 'alert_job_status', 'alert_recipient_status',
    'alert_delivery_status', 'maintenance_run_status', 'account_status'
  ) \gexec
DO $function_ownership$
DECLARE app_function record;
BEGIN
    FOR app_function IN
        SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) AS arguments
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND pg_get_userbyid(p.proowner) <> 'quakestrike_migration'
          AND p.oid IN (
              to_regprocedure('public.quakestrike_prediction_input_snapshot_sha256(jsonb)'),
              to_regprocedure('public.quakestrike_prediction_jobs_snapshot_immutable()'),
              to_regprocedure('public.enforce_alert_assignment_and_snapshots_immutable()'),
              to_regprocedure('public.enforce_alert_recipient_evidence()'),
              to_regprocedure('public.enforce_alert_attempt_evidence()'),
              to_regprocedure('public.quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text)')
          )
    LOOP
        EXECUTE format('ALTER FUNCTION %I.%I(%s) OWNER TO quakestrike_migration',
                       app_function.nspname, app_function.proname, app_function.arguments);
    END LOOP;
END
$function_ownership$;
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
    earthquake_bulletin_event_identities, prediction_jobs,
    prediction_attempts, job_dispatches
TO quakestrike_worker;
GRANT DELETE ON TABLE ingestion_run_inputs TO quakestrike_worker;
GRANT SELECT, INSERT ON TABLE
    earthquake_event_revisions, forecasts, alert_jobs, audit_logs,
    source_catalog_evidence
TO quakestrike_worker;

REVOKE USAGE ON TYPE public.alert_recipient_status, public.alert_delivery_status FROM PUBLIC;
GRANT USAGE ON TYPE public.alert_recipient_status, public.alert_delivery_status TO quakestrike_worker;
GRANT SELECT, INSERT ON public.alert_recipients, public.alert_delivery_attempts TO quakestrike_worker;
GRANT UPDATE (status,recipient_resolution_completed_at,lease_expires_at,worker_execution_id,completed_at)
 ON public.alert_jobs TO quakestrike_worker;
GRANT UPDATE (status,next_attempt_at,delivered_at,last_error_code,processing_lease_expires_at,worker_execution_id)
 ON public.alert_recipients TO quakestrike_worker;
GRANT UPDATE (provider_message_id,status,finished_at,provider_status_at,error_code,error_message,provider_evidence_snapshot)
 ON public.alert_delivery_attempts TO quakestrike_worker;
GRANT SELECT (user_id,email,email_verified_at,email_enabled,mobile_number,mobile_verified_at,sms_enabled,
 alert_trigger_magnitude,nearby_alerts_only,alert_location_latitude,alert_location_longitude,
 alert_trigger_distance_km,account_status,onboarding_completed_at) ON public.users TO quakestrike_worker;

SQL
    then
      echo '{"action":"grant-worker","status":"ready"}'
    else
      echo '{"action":"grant-worker","status":"failed","reason":"worker_grant_failed"}'
      exit 2
    fi
    ;;
  create-alert-testing)
    if [ -z "${ALERT_TEST_DB_PASSWORD:-}" ]; then
      echo '{"action":"create-alert-testing","status":"failed","reason":"missing_password"}'
      exit 2
    fi
    if psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv alert_test_password ALERT_TEST_DB_PASSWORD
\getenv database_name POSTGRES_DB
SELECT format('CREATE ROLE quakestrike_alert_testing LOGIN NOINHERIT PASSWORD %L', :'alert_test_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_alert_testing') \gexec
ALTER ROLE quakestrike_alert_testing NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'alert_test_password';
ALTER ROLE quakestrike_alert_testing SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"database_name" TO quakestrike_alert_testing;
GRANT USAGE ON SCHEMA public TO quakestrike_alert_testing;
GRANT SELECT (user_id,display_name,email,email_verified_at,email_enabled,mobile_number,
 mobile_verified_at,sms_enabled,alert_trigger_magnitude,nearby_alerts_only,
 alert_location_latitude,alert_location_longitude,alert_trigger_distance_km,
 account_status,onboarding_completed_at) ON public.users TO quakestrike_alert_testing;
SQL
    then
      echo '{"action":"create-alert-testing","status":"ready"}'
    else
      echo '{"action":"create-alert-testing","status":"failed","reason":"role_provisioning_failed"}'
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
  create-backend)
    if [ -z "${BACKEND_DB_PASSWORD:-}" ]; then
      echo '{"action":"create-backend","status":"failed","reason":"missing_backend_password"}'
      exit 2
    fi
    if psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 >/dev/null 2>&1 <<'SQL'
\getenv backend_password BACKEND_DB_PASSWORD
\getenv database_name POSTGRES_DB
SELECT format('CREATE ROLE quakestrike_backend LOGIN NOINHERIT PASSWORD %L', :'backend_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_backend') \gexec
ALTER ROLE quakestrike_backend NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD :'backend_password';
ALTER ROLE quakestrike_backend SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE :"database_name" TO quakestrike_backend;
GRANT USAGE ON SCHEMA public TO quakestrike_backend;
GRANT SELECT (event_id, superseded_by_event_id) ON earthquake_events TO quakestrike_backend;
GRANT SELECT (event_id, event_revision_id, revision_number, event_time, magnitude,
  latitude, longitude, depth_km, location_description, origin, source_url, prediction_skip_reason)
  ON earthquake_event_revisions TO quakestrike_backend;
GRANT SELECT (job_id, event_revision_id, model_release_id, status, requested_at)
  ON prediction_jobs TO quakestrike_backend;
GRANT SELECT ON forecasts TO quakestrike_backend;
GRANT SELECT (model_release_id) ON model_releases TO quakestrike_backend;
GRANT SELECT ON users TO quakestrike_backend;
GRANT INSERT (user_id, clerk_user_id, display_name, email, email_verified_at)
  ON users TO quakestrike_backend;
GRANT UPDATE (display_name, email, email_verified_at, email_enabled, mobile_number,
  mobile_verified_at, sms_enabled, alert_trigger_magnitude, nearby_alerts_only,
  alert_location_latitude, alert_location_longitude, alert_trigger_distance_km,
  onboarding_completed_at, updated_at) ON users TO quakestrike_backend;
GRANT INSERT ON audit_logs TO quakestrike_backend;
-- The callback capability exists only after the approved forward migration.
DO $$ BEGIN
 IF to_regprocedure('public.quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text)') IS NOT NULL THEN
  REVOKE ALL ON FUNCTION public.quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text) FROM PUBLIC;
  GRANT EXECUTE ON FUNCTION public.quakestrike_reconcile_brevo_delivery(uuid,text,text,timestamptz,text) TO quakestrike_backend;
 END IF;
END $$;
SQL
    then
      echo '{"action":"create-backend","status":"ready"}'
    else
      echo '{"action":"create-backend","status":"failed","reason":"role_provisioning_failed"}'
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
GRANT SELECT ON ingestion_runs TO quakestrike_maintenance;
GRANT SELECT, DELETE ON ingestion_run_inputs TO quakestrike_maintenance;
SQL
    then
      echo '{"action":"create-maintenance","status":"ready"}'
    else
      echo '{"action":"create-maintenance","status":"failed","reason":"role_provisioning_failed"}'
      exit 2
    fi
    ;;
  *)
    echo 'Usage: provision-roles.sh create|grant-worker|create-alert-testing|create-observer|create-backend|create-maintenance' >&2
    exit 2
    ;;
esac
