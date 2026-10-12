"""Create Bulletin accounts and enable transactional user audits."""

from alembic import op

revision = "20261002_11"
down_revision = "20260925_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE account_status AS ENUM ('active', 'suspended', 'closed');
        CREATE TABLE users (
            user_id uuid PRIMARY KEY,
            clerk_user_id text NOT NULL UNIQUE,
            first_name text,
            middle_name text,
            last_name text,
            display_name text NOT NULL,
            email text NOT NULL,
            email_verified_at timestamptz,
            email_enabled boolean NOT NULL DEFAULT false,
            mobile_number text UNIQUE,
            mobile_verified_at timestamptz,
            sms_enabled boolean NOT NULL DEFAULT false,
            alert_trigger_magnitude numeric(3,1) NOT NULL DEFAULT 4.5,
            nearby_alerts_only boolean NOT NULL DEFAULT false,
            alert_location_latitude numeric(9,6),
            alert_location_longitude numeric(10,6),
            alert_trigger_distance_km numeric(10,3),
            account_status account_status NOT NULL DEFAULT 'active',
            onboarding_completed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_users_names CHECK (
                clerk_user_id = btrim(clerk_user_id) AND clerk_user_id <> ''
                AND display_name = btrim(display_name) AND length(display_name) BETWEEN 1 AND 100
                AND email = btrim(email) AND email <> ''),
            CONSTRAINT ck_users_phone CHECK ((mobile_number IS NULL) = (mobile_verified_at IS NULL)
                AND (mobile_number IS NULL OR mobile_number ~ '^\\+639[0-9]{9}$')),
            CONSTRAINT ck_users_magnitude CHECK (alert_trigger_magnitude BETWEEN 1 AND 10),
            CONSTRAINT ck_users_location CHECK (
                (alert_location_latitude IS NULL) = (alert_location_longitude IS NULL)
                AND (alert_location_latitude IS NULL OR alert_location_latitude BETWEEN -90 AND 90)
                AND (alert_location_longitude IS NULL
                     OR alert_location_longitude BETWEEN -180 AND 180)
                AND (alert_trigger_distance_km IS NULL
                     OR alert_trigger_distance_km BETWEEN 1 AND 1000)),
            CONSTRAINT ck_users_nearby CHECK (NOT nearby_alerts_only OR
                (alert_location_latitude IS NOT NULL AND alert_location_longitude IS NOT NULL
                 AND alert_trigger_distance_km IS NOT NULL)),
            CONSTRAINT ck_users_onboarding CHECK (onboarding_completed_at IS NOT NULL OR
                (NOT email_enabled AND NOT sms_enabled)),
            CONSTRAINT ck_users_destinations CHECK (
                (NOT sms_enabled OR mobile_verified_at IS NOT NULL)
                AND (NOT email_enabled OR email_verified_at IS NOT NULL)),
            CONSTRAINT ck_users_closed CHECK (account_status <> 'closed' OR
                (NOT email_enabled AND NOT sms_enabled AND mobile_number IS NULL
                 AND mobile_verified_at IS NULL))
        );
        ALTER TABLE audit_logs DROP CONSTRAINT ck_audit_logs_user_actor_deferred;
        ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_actor_user
            FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON DELETE RESTRICT;
    """)


def downgrade() -> None:
    # Retained user audits must be explicitly handled before destructive rollback.
    op.execute("""
        ALTER TABLE audit_logs DROP CONSTRAINT fk_audit_logs_actor_user;
        ALTER TABLE audit_logs ADD CONSTRAINT ck_audit_logs_user_actor_deferred
            CHECK (actor_type <> 'user');
        DROP TABLE users;
        DROP TYPE account_status;
    """)
