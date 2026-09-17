"""Construction of the reusable PHIVOLCS Requests session."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from quakestrike.infrastructure.phivolcs.certificate import phivolcs_ca_bundle

USER_AGENT = (
    "Mozilla/5.0 (compatible; quakestrikeph-scraper/1.0; +https://earthquake.phivolcs.dost.gov.ph/)"
)


def create_phivolcs_session() -> requests.Session:
    """Create a verified session that retries only documented transient failures."""

    retries = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        other=0,
        backoff_factor=0.5,
        status_forcelist=(429, *range(500, 600)),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    session.verify = str(phivolcs_ca_bundle())
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session
