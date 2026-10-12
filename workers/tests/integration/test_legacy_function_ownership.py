"""Legacy administrator-owned functions must remain editable by migrations."""

import re
import runpy
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_provisioning_transfers_legacy_functions_to_migration_role(migrated_engine):
    root = Path(__file__).resolve().parents[3]
    script = (root / "database/initialization/provision-roles.sh").read_text()
    block = re.search(r"DO \$function_ownership\$.*?\$function_ownership\$;", script, re.S)
    migration = runpy.run_path(
        str(root / "database/migrations/versions/20260924_08_maintenance_runs.py")
    )
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quakestrike_migration')
                    THEN CREATE ROLE quakestrike_migration; END IF;
                END $$;
                GRANT USAGE, CREATE ON SCHEMA public TO quakestrike_migration;
            """)
            )
            if block:
                connection.execute(text(block.group()))
            owners = (
                connection.execute(
                    text("""
                SELECT pg_get_userbyid(p.proowner)
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname IN (
                    'quakestrike_prediction_input_snapshot_sha256',
                    'quakestrike_prediction_jobs_snapshot_immutable'
                )
            """)
                )
                .scalars()
                .all()
            )
            assert owners == ["quakestrike_migration", "quakestrike_migration"]
            connection.execute(text("SET LOCAL ROLE quakestrike_migration"))
            connection.execute(
                text(migration["SNAPSHOT_FUNCTION"].replace("DIGEST_CALL", "public.digest"))
            )
        finally:
            transaction.rollback()
