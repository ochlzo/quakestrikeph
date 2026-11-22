from __future__ import annotations

import pytest

from quakestrike.infrastructure.phivolcs.urls import BulletinUrlRejected, canonicalize_bulletin_url


@pytest.mark.parametrize(
    "href",
    [
        "https://example.invalid/2025_Earthquake_Information/January/2025_0102_0304_B1.html",
        "http://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/January/2025_0102_0304_B1.html",
        "2025_Earthquake_Information/January/not-a-bulletin.html",
        "2025_Earthquake_Information/January/2025_0102_0304_B1.html?token=secret",
    ],
)
def test_canonicalize_bulletin_url_rejects_untrusted_or_unrecognized_links(href: str) -> None:
    with pytest.raises(BulletinUrlRejected):
        canonicalize_bulletin_url("https://earthquake.phivolcs.dost.gov.ph/", href, 2025)


def test_canonicalize_bulletin_url_normalizes_percent_encoding_and_discards_fragments() -> None:
    identity = canonicalize_bulletin_url(
        "https://earthquake.phivolcs.dost.gov.ph/",
        "https://EARTHQUAKE.PHIVOLCS.DOST.GOV.PH:443/2025%5FEarthquake_Information/"
        "January/2025_0102_0304_B1.html#source",
        2025,
    )

    assert identity.source_url == (
        "https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/"
        "January/2025_0102_0304_B1.html"
    )


def test_canonicalize_bulletin_url_accepts_only_the_recognized_group_only_shape() -> None:
    identity = canonicalize_bulletin_url(
        "https://earthquake.phivolcs.dost.gov.ph/",
        "2025_Earthquake_Information/January/2025_0102_0304.html",
        2025,
    )

    assert identity.source_bulletin_id is None
    assert identity.source_event_group_id == "2025_0102_0304"


@pytest.mark.parametrize(
    "href",
    [
        "https://earthquake.phivolcs.dost.gov.ph:444/2025_Earthquake_Information/January/2025_0102_0304_B1.html",
        "https://earthquake.phivolcs.dost.gov.ph:invalid/2025_Earthquake_Information/January/2025_0102_0304_B1.html",
    ],
)
def test_canonicalize_bulletin_url_rejects_non_default_or_invalid_ports(href: str) -> None:
    with pytest.raises(BulletinUrlRejected):
        canonicalize_bulletin_url("https://earthquake.phivolcs.dost.gov.ph/", href, 2025)


@pytest.mark.parametrize(
    "href",
    [
        "https://earthquake.phivolcs.dost.gov.ph/garbage/2025_0102_0304_B1.html",
        "https://earthquake.phivolcs.dost.gov.ph/2025_Earthquake_Information/January/2025_0102_0304_B1.exe",
        "2025_Earthquake_Information/January/2025_0102_0304_B1.html.exe",
        "2025_Earthquake_Information/January/2025_0102_0304_B1%2Esvg",
    ],
)
def test_canonicalize_bulletin_url_rejects_unrecognized_paths_and_extensions(href: str) -> None:
    with pytest.raises(BulletinUrlRejected):
        canonicalize_bulletin_url("https://earthquake.phivolcs.dost.gov.ph/", href, 2025)


@pytest.mark.parametrize("extension", ["html", "pdf", "jpg"])
def test_canonicalize_bulletin_url_accepts_scraper_supported_bulletin_extensions(
    extension: str,
) -> None:
    identity = canonicalize_bulletin_url(
        "https://earthquake.phivolcs.dost.gov.ph/",
        f"2025_Earthquake_Bulletins/January/2025_0102_0304_B1.{extension}",
        2025,
    )

    assert identity.source_bulletin_id == "2025_0102_0304_B1"
    assert identity.source_url.endswith(f"B1.{extension}")


def test_canonicalize_bulletin_url_accepts_bulletin_suffix_without_underscore() -> None:
    identity = canonicalize_bulletin_url(
        "https://earthquake.phivolcs.dost.gov.ph/",
        r"2026_Earthquake_Information\November\2026_1121_091033B3.html",
        2026,
    )

    assert identity.source_url == (
        "https://earthquake.phivolcs.dost.gov.ph/2026_Earthquake_Information/"
        "November/2026_1121_091033B3.html"
    )
    assert identity.source_bulletin_id == "2026_1121_091033B3"
    assert identity.source_event_group_id == "2026_1121_091033"
