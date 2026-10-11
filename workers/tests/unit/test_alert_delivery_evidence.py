from quakestrike.application.alert_delivery import SubmissionResult, normalize_submission


def test_submission_boundary_retains_trusted_retry_timing_without_private_evidence():
    result = normalize_submission(
        SubmissionResult(
            "transient",
            retry_after_seconds=90,
            evidence={"retry_delay_seconds": 45, "private": "TOKEN"},
        )
    )
    assert result.retry_after_seconds == 90
    assert result.evidence == {"retry_delay_seconds": 90}
    assert normalize_submission(
        SubmissionResult("unknown", evidence={"retry_delay_seconds": 60})
    ).evidence == {"retry_delay_seconds": 60}
    huge = normalize_submission(SubmissionResult("transient", retry_after_seconds=1e300))
    assert huge.retry_after_seconds == 1e300
    assert huge.evidence == {}


def test_sms_count_is_separate_from_credit_charging_and_rejects_fractional_counts():
    result = normalize_submission(
        SubmissionResult("unknown", evidence={"provider_sms_count": 2, "charging_units": 1.5})
    )
    assert result.evidence == {"provider_sms_count": 2, "charging_units": 1.5}
    assert (
        normalize_submission(
            SubmissionResult("unknown", evidence={"provider_sms_count": 1.5})
        ).evidence
        == {}
    )
