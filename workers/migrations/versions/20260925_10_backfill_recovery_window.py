"""Allow a new backfill run after the prior run's retry checkpoints expire."""

import sqlalchemy as sa
from alembic import op

revision = "20260925_10"
down_revision = "20260925_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_ingestion_runs_bootstrap_snapshot_sha256", table_name="ingestion_runs")
    op.create_index(
        "ix_ingestion_runs_bootstrap_snapshot_sha256",
        "ingestion_runs",
        ["bootstrap_snapshot_sha256"],
        postgresql_where=sa.text("bootstrap_snapshot_sha256 IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_bootstrap_snapshot_sha256", table_name="ingestion_runs")
    op.create_index(
        "ix_ingestion_runs_bootstrap_snapshot_sha256",
        "ingestion_runs",
        ["bootstrap_snapshot_sha256"],
        unique=True,
        postgresql_where=sa.text("bootstrap_snapshot_sha256 IS NOT NULL"),
    )
