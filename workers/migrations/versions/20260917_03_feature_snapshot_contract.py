"""Persist feature-snapshot skip reasons and history query index."""

import sqlalchemy as sa
from alembic import op

revision = "20260917_03"
down_revision = "20260916_01"
branch_labels = None
depends_on = None

_SKIP_REASONS = (
    "magnitude_below_m1",
    "history_coverage_unavailable",
    "incomplete_feature_history",
    "history_starts_after_required_window",
    "history_ends_before_anchor",
    "model_release_unavailable",
)


def upgrade() -> None:
    op.add_column(
        "earthquake_event_revisions",
        sa.Column("prediction_skip_reason", sa.Text(), nullable=True),
    )
    reasons = ", ".join(f"'{reason}'" for reason in _SKIP_REASONS)
    op.create_check_constraint(
        "ck_event_revisions_prediction_skip_reason",
        "earthquake_event_revisions",
        f"prediction_skip_reason IS NULL OR prediction_skip_reason IN ({reasons})",
    )
    op.create_index(
        "ix_event_revisions_event_time",
        "earthquake_event_revisions",
        ["event_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_revisions_event_time", table_name="earthquake_event_revisions")
    op.drop_constraint(
        "ck_event_revisions_prediction_skip_reason",
        "earthquake_event_revisions",
        type_="check",
    )
    op.drop_column("earthquake_event_revisions", "prediction_skip_reason")
