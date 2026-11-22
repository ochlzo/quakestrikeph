from __future__ import annotations

from pathlib import Path

from quakestrike.infrastructure.phivolcs.certificate import phivolcs_ca_bundle
from quakestrike.infrastructure.phivolcs.session import USER_AGENT, create_phivolcs_session


def test_phivolcs_session_uses_verified_package_certificate_and_transient_retry_policy() -> None:
    session = create_phivolcs_session()
    retry = session.adapters["https://"].max_retries
    bundle_text = phivolcs_ca_bundle().read_text(encoding="ascii")
    intermediates = (
        Path(__file__).resolve().parents[2]
        / "src/quakestrike/infrastructure/phivolcs/phivolcs_intermediate.pem"
    ).read_text(encoding="ascii")

    assert session.headers["User-Agent"] == USER_AGENT
    assert USER_AGENT == (
        "Mozilla/5.0 (compatible; quakestrikeph-scraper/1.0; "
        "+https://earthquake.phivolcs.dost.gov.ph/)"
    )
    assert session.verify == str(phivolcs_ca_bundle())
    assert intermediates.count("BEGIN CERTIFICATE") == 2
    assert intermediates in bundle_text
    assert retry.allowed_methods == frozenset({"GET"})
    assert retry.total == retry.connect == retry.read == retry.status == 4
    assert retry.other == 0
    assert 429 in retry.status_forcelist
    assert set(range(500, 600)).issubset(retry.status_forcelist)
    assert 400 not in retry.status_forcelist
