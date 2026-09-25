from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from quakestrike.domain.alerts import AutomaticAlertCandidate, create_automatic_alert_snapshots


def test_historical_recovery_never_creates_alert_even_inside_forecast_window():
    now = datetime(2026, 9, 25, 4, tzinfo=UTC)
    job_id, release_id, revision_id = uuid4(), uuid4(), uuid4()
    candidate = AutomaticAlertCandidate(
        job_id=job_id,
        job_release_id=release_id,
        configured_release_id=release_id,
        revision_id=revision_id,
        latest_revision_id=revision_id,
        latest_successful_job_id=job_id,
        trigger_type="manual",
        event_superseded=False,
        magnitude=Decimal("4.2"),
        event_time=now - timedelta(hours=2),
        window_end=now + timedelta(hours=22),
        now=now,
        historical_recovery=True,
    )
    assert create_automatic_alert_snapshots(candidate) is None
