from __future__ import annotations

import pytest

from quakestrike.infrastructure.phivolcs.urls import BulletinUrlRejected, canonicalize_bulletin_url


@pytest.mark.parametrize(
    ("page_url", "href", "event_year", "expected_url", "bulletin_id"),
    [
        (
            "https://earthquake.phivolcs.dost.gov.ph/",
            "2026_Earthquake_Information/August/2026_0818_1350_B2html",
            2026,
            "https://earthquake.phivolcs.dost.gov.ph/2026_Earthquake_Information/August/2026_0818_1350_B2.html",
            "2026_0818_1350_B2",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/",
            "2018_Earthquake_Information\\March\\2018_0314__1632_B1.html",
            2018,
            "https://earthquake.phivolcs.dost.gov.ph/2018_Earthquake_Information/March/2018_0314_1632_B1.html",
            "2018_0314_1632_B1",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/",
            "2026_Earthquake_Information\\September\\2026_0919_1525_B1_NL.html",
            2026,
            "https://earthquake.phivolcs.dost.gov.ph/2026_Earthquake_Information/September/2026_0919_1525_B1_NL.html",
            "2026_0919_1525_B1_NL",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/EQLatest-Monthly/2023/2023_August.html",
            "_Information\\August\\2023_0731_1640_B1.html",
            2023,
            "https://earthquake.phivolcs.dost.gov.ph/2023_Earthquake_Information/August/2023_0731_1640_B1.html",
            "2023_0731_1640_B1",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/EQLatest-Monthly/2019/2019_February.html",
            "2019_Earthquake_Information\\February\\2019_0228_1708_B2.html",
            2019,
            "https://earthquake.phivolcs.dost.gov.ph/2019_Earthquake_Information/February/2019_0228_1708_B2.html",
            "2019_0228_1708_B2",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/EQLatest-Monthly/2017/2017_January.html",
            "../2016_Earthquake_Bulletins/December/2016_1231_2239_B2.html",
            2016,
            "https://earthquake.phivolcs.dost.gov.ph/2016_Earthquake_Bulletins/December/2016_1231_2239_B2.html",
            "2016_1231_2239_B2",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/EQLatest-Monthly/2018/2018_July.html",
            "2018_Earthquake_Information\\July2018_0731_2005_B2.html",
            2018,
            "https://earthquake.phivolcs.dost.gov.ph/2018_Earthquake_Information/July/2018_0731_2005_B2.html",
            "2018_0731_2005_B2",
        ),
        (
            "https://earthquake.phivolcs.dost.gov.ph/EQLatest-Monthly/2018/2018_July.html",
            "2018_Earthquake_Information\\July\\018_0731_1644_B3F.html",
            2018,
            "https://earthquake.phivolcs.dost.gov.ph/2018_Earthquake_Information/July/2018_0731_1644_B3F.html",
            "2018_0731_1644_B3F",
        ),
    ],
)
def test_canonicalize_bulletin_url_repairs_known_legacy_paths(
    page_url: str,
    href: str,
    event_year: int,
    expected_url: str,
    bulletin_id: str,
) -> None:
    identity = canonicalize_bulletin_url(page_url, href, event_year)

    assert identity.source_url == expected_url
    assert identity.source_bulletin_id == bulletin_id
    assert identity.source_event_group_id == bulletin_id.rsplit("_B", 1)[0]


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


@pytest.mark.parametrize("extension", ["html", "htm", "pdf", "jpg", "jpeg"])
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
