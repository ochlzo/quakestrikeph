"""Keep only the Bulletin account display name."""

from alembic import op

revision = "20261004_12"
down_revision = "20261002_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
            DROP COLUMN first_name,
            DROP COLUMN middle_name,
            DROP COLUMN last_name;
    """)


def downgrade() -> None:
    # Restore the nullable schema only; dropped name values cannot be recovered.
    op.execute("""
        ALTER TABLE users
            ADD COLUMN first_name text,
            ADD COLUMN middle_name text,
            ADD COLUMN last_name text;
    """)
