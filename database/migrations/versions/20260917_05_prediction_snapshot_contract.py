"""Enforce the canonical prediction snapshot at the PostgreSQL boundary."""

# ruff: noqa: E501

from alembic import op

revision = "20260917_05"
down_revision = "20260917_04"
branch_labels = None
depends_on = None

_SNAPSHOT_KEYS_ARRAY = (
    "ARRAY['anchor_magnitude', 'anchor_depth_km', 'anchor_latitude', "
    "'anchor_longitude', 'anchor_time_is_minute_precision', "
    "'catalog_m1_plus_count_past_1h', 'catalog_m1_plus_count_past_24h', "
    "'catalog_m1_plus_count_past_7d', "
    "'local_m1_plus_count_past_24h_within_50km', "
    "'local_m1_plus_count_past_24h_within_100km']"
)

_SNAPSHOT_KEYS_CHECK = (
    "CASE WHEN jsonb_typeof(input_snapshot_json) = 'object' THEN "
    f"input_snapshot_json ?& {_SNAPSHOT_KEYS_ARRAY} "
    f"AND input_snapshot_json - {_SNAPSHOT_KEYS_ARRAY} = '{{}}'::jsonb "
    "ELSE FALSE END"
)

_SNAPSHOT_VALUES_CHECK = (
    "CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_magnitude') = 'number' THEN "
    "(input_snapshot_json ->> 'anchor_magnitude')::numeric NOT IN "
    "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
    "AND (input_snapshot_json ->> 'anchor_magnitude')::numeric BETWEEN -999.99 AND 999.99 "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_depth_km') = 'number' THEN "
    "(input_snapshot_json ->> 'anchor_depth_km')::numeric NOT IN "
    "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
    "AND (input_snapshot_json ->> 'anchor_depth_km')::numeric BETWEEN 0 AND 9999999.999 "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_latitude') = 'number' THEN "
    "(input_snapshot_json ->> 'anchor_latitude')::numeric NOT IN "
    "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
    "AND (input_snapshot_json ->> 'anchor_latitude')::numeric BETWEEN -90 AND 90 "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_longitude') = 'number' THEN "
    "(input_snapshot_json ->> 'anchor_longitude')::numeric NOT IN "
    "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
    "AND (input_snapshot_json ->> 'anchor_longitude')::numeric BETWEEN -180 AND 180 "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'anchor_time_is_minute_precision') = 'number' THEN "
    "(input_snapshot_json ->> 'anchor_time_is_minute_precision') ~ '^[01]$' "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'catalog_m1_plus_count_past_1h') = 'number' THEN "
    "(input_snapshot_json ->> 'catalog_m1_plus_count_past_1h') ~ '^[0-9]+$' "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'catalog_m1_plus_count_past_24h') = 'number' THEN "
    "(input_snapshot_json ->> 'catalog_m1_plus_count_past_24h') ~ '^[0-9]+$' "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'catalog_m1_plus_count_past_7d') = 'number' THEN "
    "(input_snapshot_json ->> 'catalog_m1_plus_count_past_7d') ~ '^[0-9]+$' "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'local_m1_plus_count_past_24h_within_50km') = 'number' THEN "
    "(input_snapshot_json ->> 'local_m1_plus_count_past_24h_within_50km') ~ '^[0-9]+$' "
    "ELSE FALSE END "
    "AND CASE WHEN jsonb_typeof(input_snapshot_json -> 'local_m1_plus_count_past_24h_within_100km') = 'number' THEN "
    "(input_snapshot_json ->> 'local_m1_plus_count_past_24h_within_100km') ~ '^[0-9]+$' "
    "ELSE FALSE END"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION quakestrike_prediction_input_snapshot_sha256(snapshot jsonb)
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
            SELECT CASE
                WHEN jsonb_typeof($1) <> 'object' THEN NULL
                ELSE encode(
                    digest(
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
    )
    op.create_check_constraint(
        "ck_prediction_jobs_snapshot_keys",
        "prediction_jobs",
        _SNAPSHOT_KEYS_CHECK,
    )
    op.create_check_constraint(
        "ck_prediction_jobs_snapshot_value_types",
        "prediction_jobs",
        _SNAPSHOT_VALUES_CHECK,
    )
    op.create_check_constraint(
        "ck_prediction_jobs_snapshot_hash",
        "prediction_jobs",
        "input_snapshot_hash = quakestrike_prediction_input_snapshot_sha256(input_snapshot_json)",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION quakestrike_prediction_jobs_snapshot_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.input_snapshot_json IS DISTINCT FROM OLD.input_snapshot_json
               OR NEW.input_snapshot_hash IS DISTINCT FROM OLD.input_snapshot_hash THEN
                RAISE EXCEPTION 'Prediction input snapshots are immutable.'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prediction_jobs_snapshot_immutable
        BEFORE UPDATE OF input_snapshot_json, input_snapshot_hash ON prediction_jobs
        FOR EACH ROW
        EXECUTE FUNCTION quakestrike_prediction_jobs_snapshot_immutable()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_prediction_jobs_snapshot_immutable ON prediction_jobs")
    op.execute("DROP FUNCTION quakestrike_prediction_jobs_snapshot_immutable()")
    op.drop_constraint(
        "ck_prediction_jobs_snapshot_hash",
        "prediction_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_prediction_jobs_snapshot_value_types",
        "prediction_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_prediction_jobs_snapshot_keys",
        "prediction_jobs",
        type_="check",
    )
    op.execute("DROP FUNCTION quakestrike_prediction_input_snapshot_sha256(jsonb)")
