from quakestrike.infrastructure.database.tables import (
    alert_jobs,
    audit_logs,
    forecasts,
    metadata,
)


def test_prediction_completion_tables_match_the_automatic_alert_contract() -> None:
    assert "forecast_reviews" not in metadata.tables
    assert "additional_output_json" not in forecasts.c
    assert set(alert_jobs.c.keys()) == {
        "alert_job_id",
        "forecast_id",
        "requested_at",
        "message_snapshot",
        "recipient_policy_snapshot",
        "status",
        "recipient_resolution_completed_at",
        "lease_expires_at",
        "worker_execution_id",
        "expires_at",
        "completed_at",
        "correlation_id",
    }
    assert alert_jobs.c.forecast_id.unique is True


def test_prediction_completion_tables_include_required_indexes_and_staging_guards() -> None:
    assert {index.name for index in alert_jobs.indexes} >= {
        "ix_alert_jobs_active_lease",
        "ix_alert_jobs_requested_at",
        "ix_alert_jobs_status_expiry",
    }
    assert {index.name for index in audit_logs.indexes} >= {
        "ix_audit_logs_actor_occurred_at",
        "ix_audit_logs_correlation_id",
        "ix_audit_logs_occurred_at",
        "ix_audit_logs_target_occurred_at",
    }
    assert {constraint.name for constraint in forecasts.constraints} >= {
        "ck_forecasts_supersedes_other"
    }
    assert {constraint.name for constraint in audit_logs.constraints} >= {
        "fk_audit_logs_actor_user"
    }
