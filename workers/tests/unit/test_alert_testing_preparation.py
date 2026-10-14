import copy

import pytest

from quakestrike.alert_testing.infrastructure.preparation import PreparationSigner


def test_signature_survives_browser_numbers_and_binds_reviewed_inputs():
    signer = PreparationSigner("test-only-preparation-key-at-least-32-bytes")
    scenario = {"event": {"magnitude": 5.0}, "observations": [{"latitude": 9.86123}]}
    inputs = {"magnitude": "5.0"}
    scenario["preparation_token"] = signer.token(scenario, inputs)
    browser = copy.deepcopy(scenario)
    browser["event"]["magnitude"] = 5
    signer.verify(browser, inputs)
    with pytest.raises(ValueError):
        signer.verify(browser, {"magnitude": "5"})
    browser["observations"][0]["latitude"] += 0.01
    with pytest.raises(ValueError):
        signer.verify(browser, inputs)


def test_malformed_preparation_fails_with_bounded_validation_error():
    signer = PreparationSigner("test-only-preparation-key-at-least-32-bytes")
    nested = []
    for _ in range(800):
        nested = [nested]
    for payload in (
        None,
        {},
        {"preparation_token": "é" * 64},
        {"preparation_token": "a" * 64, "event": {"magnitude": float("nan")}},
        {"preparation_token": "a" * 64, "extra": nested},
    ):
        with pytest.raises(ValueError, match="preparation"):
            signer.verify(payload, {})
