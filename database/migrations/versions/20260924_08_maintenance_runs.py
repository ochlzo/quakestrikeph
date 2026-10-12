"""Record host maintenance attempts and make snapshot checks restorable."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260924_08"
down_revision = "20260923_07"
branch_labels = None
depends_on = None

STATUSES = ("running", "succeeded", "failed", "abandoned")

SNAPSHOT_FUNCTION = """
CREATE OR REPLACE FUNCTION public.quakestrike_prediction_input_snapshot_sha256(snapshot jsonb)
RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN jsonb_typeof($1) <> 'object' THEN NULL
        ELSE encode(
            DIGEST_CALL(
                convert_to(
                    '{"features":{' || (
                        SELECT string_agg(
                            to_json(key)::text || ':' || CASE
                                WHEN jsonb_typeof($1 -> key) = 'number' THEN CASE
                                    WHEN value::numeric = trunc(value::numeric)
                                        THEN trunc(value::numeric)::text
                                    ELSE value::double precision::text
                                END
                                ELSE value
                            END,
                            ',' ORDER BY key COLLATE "C"
                        )
                        FROM jsonb_each_text($1) AS feature(key, value)
                    ) ||
                    '},"input_schema_version":"quakestrike.prediction-input.v1"}',
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        )
    END
$$
"""


def upgrade() -> None:
    postgresql.ENUM(*STATUSES, name="maintenance_run_status").create(op.get_bind())
    op.create_table(
        "maintenance_runs",
        sa.Column("maintenance_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*STATUSES, name="maintenance_run_status", create_type=False),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("affected_row_count", sa.BigInteger()),
        sa.Column("artifact_reference", sa.Text()),
        sa.Column("artifact_checksum", sa.Text()),
        sa.Column("related_backup_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("verification_summary", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["related_backup_run_id"],
            ["maintenance_runs.maintenance_run_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_type IN ('backup', 'restore_test', 'retention_cleanup')",
            name="ck_maintenance_runs_operation_type",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_maintenance_runs_finish",
        ),
        sa.CheckConstraint(
            "affected_row_count IS NULL OR affected_row_count >= 0",
            name="ck_maintenance_runs_count",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR operation_type <> 'backup' OR "
            "(artifact_reference IS NOT NULL AND artifact_checksum IS NOT NULL)",
            name="ck_maintenance_runs_backup_artifact",
        ),
        sa.CheckConstraint(
            "artifact_checksum IS NULL OR artifact_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_maintenance_runs_checksum",
        ),
        sa.CheckConstraint(
            "artifact_reference IS NULL OR "
            "(artifact_reference = btrim(artifact_reference) AND artifact_reference <> '')",
            name="ck_maintenance_runs_artifact_reference",
        ),
        sa.CheckConstraint(
            "operation_type <> 'restore_test' OR "
            "(related_backup_run_id IS NOT NULL AND related_backup_run_id <> maintenance_run_id)",
            name="ck_maintenance_runs_restore_backup",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR operation_type <> 'restore_test' OR "
            "verification_summary IS NOT NULL",
            name="ck_maintenance_runs_restore_summary",
        ),
        sa.CheckConstraint(
            "target = btrim(target) AND target <> ''", name="ck_maintenance_runs_target"
        ),
        sa.CheckConstraint(
            "verification_summary IS NULL OR "
            "(verification_summary = btrim(verification_summary) AND verification_summary <> '')",
            name="ck_maintenance_runs_verification_summary",
        ),
    )
    op.create_index(
        "ix_maintenance_runs_operation_started",
        "maintenance_runs",
        ["operation_type", "started_at"],
    )
    op.create_index(
        "ix_maintenance_runs_related_backup", "maintenance_runs", ["related_backup_run_id"]
    )
    op.create_index(
        "ix_maintenance_runs_artifact_reference", "maintenance_runs", ["artifact_reference"]
    )

    # pg_restore uses an empty search_path while loading COPY data.
    op.execute(SNAPSHOT_FUNCTION.replace("DIGEST_CALL", "public.digest"))


def downgrade() -> None:
    op.execute(SNAPSHOT_FUNCTION.replace("DIGEST_CALL", "digest"))
    op.drop_table("maintenance_runs")
    postgresql.ENUM(*STATUSES, name="maintenance_run_status").drop(op.get_bind())
