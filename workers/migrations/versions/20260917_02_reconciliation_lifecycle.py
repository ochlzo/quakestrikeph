"""Add durable reconciliation identities and ingestion checkpoints."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_02"
down_revision = "20260916_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_ingestion_runs_retry_schedule",
        "ingestion_runs",
        "(status = 'retry_wait' AND next_attempt_at IS NOT NULL) OR "
        "(status <> 'retry_wait' AND next_attempt_at IS NULL)",
    )

    op.create_table(
        "earthquake_bulletin_event_identities",
        sa.Column("source_bulletin_id", sa.Text(), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["earthquake_events.event_id"],
            onupdate="RESTRICT",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source_bulletin_id = btrim(source_bulletin_id) AND source_bulletin_id <> '' "
            "AND source_bulletin_id = upper(source_bulletin_id)",
            name="ck_bulletin_event_identities_bulletin_id",
        ),
    )
    op.execute(
        "INSERT INTO earthquake_bulletin_event_identities (source_bulletin_id, event_id) "
        "SELECT source_bulletin_id, event_id FROM earthquake_event_revisions "
        "WHERE source_bulletin_id IS NOT NULL"
    )
    op.create_index(
        "ix_bulletin_event_identities_event_id",
        "earthquake_bulletin_event_identities",
        ["event_id"],
    )
    op.drop_index("uq_event_revisions_source_bulletin_id", table_name="earthquake_event_revisions")
    op.create_index(
        "ix_event_revisions_source_bulletin_id",
        "earthquake_event_revisions",
        ["source_bulletin_id"],
        postgresql_where=sa.text("source_bulletin_id IS NOT NULL"),
    )

    op.create_table(
        "ingestion_run_inputs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("input_key", sa.Text(), primary_key=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ingestion_runs.run_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["earthquake_events.event_id"], onupdate="RESTRICT", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "input_key = btrim(input_key) AND input_key <> ''",
            name="ck_ingestion_run_inputs_key_nonblank",
        ),
        sa.CheckConstraint(
            "outcome IN ('inserted', 'revised', 'unchanged', 'rejected')",
            name="ck_ingestion_run_inputs_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'rejected' AND event_id IS NULL) OR "
            "(outcome <> 'rejected' AND event_id IS NOT NULL)",
            name="ck_ingestion_run_inputs_outcome_event",
        ),
    )
    op.create_index(
        "ix_ingestion_run_inputs_run_outcome",
        "ingestion_run_inputs",
        ["run_id", "outcome"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_run_inputs_run_outcome", table_name="ingestion_run_inputs")
    op.drop_table("ingestion_run_inputs")
    op.drop_index("ix_event_revisions_source_bulletin_id", table_name="earthquake_event_revisions")
    op.create_index(
        "uq_event_revisions_source_bulletin_id",
        "earthquake_event_revisions",
        ["source_bulletin_id"],
        unique=True,
        postgresql_where=sa.text("source_bulletin_id IS NOT NULL"),
    )
    op.drop_index("ix_bulletin_event_identities_event_id", table_name="earthquake_bulletin_event_identities")
    op.drop_table("earthquake_bulletin_event_identities")
    op.drop_constraint("ck_ingestion_runs_retry_schedule", "ingestion_runs", type_="check")
    op.drop_column("ingestion_runs", "next_attempt_at")
