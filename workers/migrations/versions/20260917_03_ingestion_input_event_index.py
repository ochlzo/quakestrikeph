"""Add the ingestion input event lookup index."""

from alembic import op

revision = "20260917_03"
down_revision = "20260917_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_ingestion_run_inputs_event_id",
        "ingestion_run_inputs",
        ["event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_run_inputs_event_id", table_name="ingestion_run_inputs")
