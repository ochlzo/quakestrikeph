"""Verified local geographic labels; reference proximity never proves containment."""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")
EARTH_RADIUS_KM = 6371.0088


@lru_cache(maxsize=1)
def _dataset() -> tuple[dict, list[dict]]:
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    payload = (ASSETS / "province-points.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["asset_sha256"]:
        raise ValueError("The geographic asset hash differs from its manifest.")
    points = json.loads(payload)
    if len(points) != manifest["record_count"]:
        raise ValueError("The geographic record count differs from its manifest.")
    return manifest, points


def resolve_province_label(
    latitude: float, longitude: float, source_location: str
) -> dict[str, object]:
    if (
        not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise ValueError("The observed coordinates are invalid.")
    manifest, points = _dataset()
    lat, lon = math.radians(latitude), math.radians(longitude)
    nearest = None
    for point in points:
        p_lat, p_lon = math.radians(point["latitude"]), math.radians(point["longitude"])
        haversine = (
            math.sin((p_lat - lat) / 2) ** 2
            + math.cos(lat) * math.cos(p_lat) * math.sin((p_lon - lon) / 2) ** 2
        )
        distance = 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1, max(0, haversine))))
        if distance <= 100 and (
            nearest is None
            or (distance, point["geoname_id"]) < (nearest[0], nearest[1]["geoname_id"])
        ):
            nearest = distance, point
    evidence: dict[str, object] = {
        "geographic_lookup_policy_version": manifest["lookup_policy_version"],
        "geographic_dataset_version": manifest["version"],
        "geographic_dataset_sha256": manifest["asset_sha256"],
        "geographic_lookup_limit_km": 100,
        "location_label": source_location,
        "location_source": "phivolcs",
        "reference_geoname_id": None,
        "reference_distance_km": None,
        "province_code": None,
        "province_name": None,
    }
    if nearest is not None:
        distance, point = nearest
        evidence.update(
            location_label="near " + point["province_name"],
            location_source="geonames_nearest_province",
            reference_geoname_id=point["geoname_id"],
            reference_distance_km=distance,
            province_code=point["province_code"],
            province_name=point["province_name"],
        )
    return evidence
