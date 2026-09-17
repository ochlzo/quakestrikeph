"""TLS verification support for PHIVOLCS's required intermediate certificate."""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

import certifi


@lru_cache(maxsize=1)
def phivolcs_ca_bundle() -> Path:
    """Return a certifi bundle extended by the package-owned intermediate."""

    intermediate = Path(__file__).with_name("phivolcs_intermediate.pem")
    content = Path(certifi.where()).read_bytes() + b"\n" + intermediate.read_bytes()
    bundle = Path(tempfile.gettempdir()) / "quakestrikeph-phivolcs-ca-bundle.pem"
    if not bundle.exists() or bundle.read_bytes() != content:
        bundle.write_bytes(content)
    return bundle
