"""PHIVOLCS bulletin URL repair and canonical identity extraction."""

from __future__ import annotations

import posixpath
import re
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from quakestrike.domain.source_rows import SourceIdentity

OFFICIAL_HOST = "earthquake.phivolcs.dost.gov.ph"
_ARCHIVE_BULLETIN_PATH = re.compile(
    r"^/EQLatest-Monthly/(?:\d{4}/)?(?P<bulletin_path>\d{4}_Earthquake_(?:Information|Bulletins)/.+)$",
    re.IGNORECASE,
)
_MISSING_YEAR_PREFIX = re.compile(
    r"^/EQLatest-Monthly/(?P<year>\d{4})/_Information/(?P<bulletin_path>.+)$",
    re.IGNORECASE,
)
_MISSING_MONTH_SEPARATOR = re.compile(
    r"^/\d{4}_Earthquake_Information/(?:January|February|March|April|May|June|July|August|September|October|November|December)(?=\d{4}_\d{3,4}_\d{4,8})",
    re.IGNORECASE,
)
_TRUNCATED_YEAR = re.compile(r"^(?P<year_suffix>\d{3})(?P<rest>_\d{3,4}_\d{4,8}.*)$")
_MISSING_HTML_SEPARATOR = re.compile(
    r"^(?P<stem>\d{4}_\d{3,4}_\d{4,8}_[^/]+)(?<!\.)html$", re.IGNORECASE
)
_DUPLICATE_TIMESTAMP_SEPARATOR = re.compile(r"^(?P<date>\d{4}_\d{3,4})__(?P<rest>\d{4,8}_[^/]+)$")
_RECOGNIZED_BULLETIN_PATH = re.compile(
    r"^/\d{4}_Earthquake_(?:Information|Bulletins)/"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)/"
    r"(?P<bulletin>(?P<group>\d{4}_\d{3,4}_\d{4,8})_B[A-Z0-9]+)\.(?:html?|pdf|jpe?g)$",
    re.IGNORECASE,
)


class BulletinUrlRejected(ValueError):
    """A link cannot safely identify an official PHIVOLCS bulletin."""


def canonicalize_bulletin_url(page_url: str, href: str, event_year: int | None) -> SourceIdentity:
    """Repair known legacy paths and return an official canonical bulletin link."""

    candidate = urljoin(page_url, href.replace("\\", "/"))
    parsed = urlsplit(candidate)
    try:
        port = parsed.port
    except ValueError as error:
        raise BulletinUrlRejected("bulletin URL port is invalid") from error
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != OFFICIAL_HOST
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
    ):
        raise BulletinUrlRejected("bulletin URL is not an official canonical HTTPS URL")

    path = _canonical_path(parsed.path)
    path = _repair_path(path, page_url, event_year)
    recognized = _RECOGNIZED_BULLETIN_PATH.fullmatch(path)
    if recognized is None:
        raise BulletinUrlRejected("bulletin URL does not match a recognized bulletin path")
    bulletin_id = recognized.group("bulletin").upper()
    group_id = recognized.group("group").upper()

    return SourceIdentity(
        source_url=urlunsplit(("https", OFFICIAL_HOST, path, "", "")),
        source_bulletin_id=bulletin_id,
        source_event_group_id=group_id,
    )


def _canonical_path(value: str) -> str:
    decoded = unquote(value)
    if not decoded.startswith("/") or any(character.isspace() for character in decoded):
        raise BulletinUrlRejected("bulletin URL path is invalid")
    normalized = posixpath.normpath(decoded)
    if normalized in {".", "/"} or normalized.startswith("../"):
        raise BulletinUrlRejected("bulletin URL path is invalid")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return quote(normalized, safe="/._-")


def _repair_path(path: str, page_url: str, event_year: int | None) -> str:
    archive_path = _ARCHIVE_BULLETIN_PATH.match(path)
    if archive_path is not None:
        path = f"/{archive_path.group('bulletin_path')}"

    missing_year_prefix = _MISSING_YEAR_PREFIX.match(path)
    if missing_year_prefix is not None:
        path = (
            f"/{missing_year_prefix.group('year')}_Earthquake_Information/"
            f"{missing_year_prefix.group('bulletin_path')}"
        )

    missing_separator = _MISSING_MONTH_SEPARATOR.match(path)
    if missing_separator is not None:
        path = f"{path[: missing_separator.end()]}/{path[missing_separator.end() :]}"

    expected_year = event_year or _page_year(page_url)
    directory, _, filename = path.rpartition("/")
    truncated = _TRUNCATED_YEAR.match(filename)
    if (
        truncated is not None
        and expected_year is not None
        and str(expected_year).endswith(truncated.group("year_suffix"))
    ):
        filename = f"{expected_year}{truncated.group('rest')}"

    duplicate = _DUPLICATE_TIMESTAMP_SEPARATOR.match(filename)
    if duplicate is not None:
        filename = f"{duplicate.group('date')}_{duplicate.group('rest')}"

    missing_html = _MISSING_HTML_SEPARATOR.match(filename)
    if missing_html is not None:
        filename = f"{missing_html.group('stem')}.html"
    return f"{directory}/{filename}"


def _page_year(page_url: str) -> int | None:
    match = re.search(r"/EQLatest-Monthly/(?P<year>\d{4})/", urlsplit(page_url).path, re.I)
    return int(match.group("year")) if match is not None else None
