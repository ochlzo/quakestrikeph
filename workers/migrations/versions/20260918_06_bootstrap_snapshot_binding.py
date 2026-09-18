"""Bind each durable backfill run to its preserved snapshot hash."""

import sqlalchemy as sa
from alembic import op

revision = "20260918_06"
down_revision = "20260917_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing_backfills = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM ingestion_runs WHERE trigger_type = 'backfill'")
    )
    if existing_backfills:
        raise RuntimeError(
            "Existing backfill runs have no provable snapshot hash; "
            "archive or explicitly remediate them before this migration."
        )
    op.add_column(
        "ingestion_runs",
        sa.Column("bootstrap_snapshot_sha256", sa.Text(), nullable=True),
    )
    op.add_column(
        "ingestion_runs",
        sa.Column("bootstrap_enriched_snapshot_sha256", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_ingestion_runs_bootstrap_snapshot_hash",
        "ingestion_runs",
        "(trigger_type <> 'backfill' AND bootstrap_snapshot_sha256 IS NULL "
        "AND bootstrap_enriched_snapshot_sha256 IS NULL) OR "
        "(trigger_type = 'backfill' AND bootstrap_snapshot_sha256 IS NOT NULL "
        "AND bootstrap_snapshot_sha256 ~ '^[0-9a-f]{64}$' "
        "AND (bootstrap_enriched_snapshot_sha256 IS NULL OR "
        "bootstrap_enriched_snapshot_sha256 ~ '^[0-9a-f]{64}$'))",
    )
    op.create_index(
        "ix_ingestion_runs_bootstrap_snapshot_sha256",
        "ingestion_runs",
        ["bootstrap_snapshot_sha256"],
        unique=True,
        postgresql_where=sa.text("bootstrap_snapshot_sha256 IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_runs_bootstrap_snapshot_sha256", table_name="ingestion_runs")
    op.drop_constraint(
        "ck_ingestion_runs_bootstrap_snapshot_hash",
        "ingestion_runs",
        type_="check",
    )
    op.drop_column("ingestion_runs", "bootstrap_enriched_snapshot_sha256")
    op.drop_column("ingestion_runs", "bootstrap_snapshot_sha256")
