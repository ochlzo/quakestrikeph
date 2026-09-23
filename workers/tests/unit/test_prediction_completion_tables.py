from quakestrike.infrastructure.database.tables import alert_jobs, forecasts, metadata


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
