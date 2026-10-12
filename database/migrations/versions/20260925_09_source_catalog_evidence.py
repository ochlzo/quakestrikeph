"""Bind validated live source coverage to one ingestion run."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260925_09"
down_revision = "20260924_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_catalog_evidence",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_runs.run_id", onupdate="RESTRICT", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("catalog_sha256", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coverage_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "source_url = btrim(source_url) AND source_url <> ''",
            name="ck_source_catalog_evidence_url",
        ),
        sa.CheckConstraint(
            "catalog_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_source_catalog_evidence_sha256",
        ),
        sa.CheckConstraint(
            "coverage_start < coverage_end AND coverage_end <= retrieved_at",
            name="ck_source_catalog_evidence_coverage",
        ),
        sa.CheckConstraint("accepted_rows > 0", name="ck_source_catalog_evidence_rows"),
    )
    op.create_index(
        "ix_source_catalog_evidence_coverage_end",
        "source_catalog_evidence",
        ["coverage_end"],
    )


def downgrade() -> None:
    op.drop_table("source_catalog_evidence")
