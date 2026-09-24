"""Pure rules for creating automatic alert work from a completed forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class AutomaticAlertCandidate:
    job_id: UUID
    job_release_id: UUID
    configured_release_id: UUID
    revision_id: UUID
    latest_revision_id: UUID
    latest_successful_job_id: UUID | None
    trigger_type: str
    event_superseded: bool
    magnitude: Decimal
    event_time: datetime
    window_end: datetime
    now: datetime


@dataclass(frozen=True, slots=True)
class AutomaticAlertSnapshots:
    message: str
    recipient_policy: dict[str, object]


def create_automatic_alert_snapshots(
    candidate: AutomaticAlertCandidate,
) -> AutomaticAlertSnapshots | None:
    """Return fixed batch content only for a current, live, unexpired M1+ forecast."""

    if (
        candidate.job_release_id != candidate.configured_release_id
        or candidate.event_superseded
        or candidate.latest_revision_id != candidate.revision_id
        or candidate.latest_successful_job_id != candidate.job_id
        or candidate.trigger_type not in {"scheduled", "manual"}
        or candidate.magnitude < 1
        or candidate.now >= candidate.window_end
    ):
        return None

    observed_at = candidate.event_time.astimezone(ZoneInfo("Asia/Manila"))
    magnitude = candidate.magnitude.normalize()
    return AutomaticAlertSnapshots(
        message=(
            f"QuakeStrike PH: M{magnitude} earthquake observed "
            f"{observed_at:%Y-%m-%d %H:%M} PHT. "
            "Check PHIVOLCS for official updates."
        ),
        recipient_policy={
            "version": "automatic_sms_v1",
            "observed_anchor_magnitude": float(candidate.magnitude),
            "account_status": "active",
            "verified_mobile_required": True,
            "sms_enabled_required": True,
            "trigger_rule": "observed_anchor_magnitude >= user.alert_trigger_magnitude",
        },
    )
