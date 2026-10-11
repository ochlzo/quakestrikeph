"""Build the pinned province-reference asset locally, without network requests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ARCHIVE_SHA256 = "6ff0c68fdbf4ab049dd0a325ed4201209eccf7ce5054e4c5cca07b4d540e0cb4"
ASSETS = Path(__file__).resolve().parents[1] / "src/quakestrike/infrastructure/geography/assets"


def build(archive: Path, output: Path = ASSETS) -> None:
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError("The archive differs from the reviewed GeoNames source.")
    crosswalk = json.loads((ASSETS / "province-crosswalk.json").read_text(encoding="utf-8-sig"))
    exclusions = json.loads(
        (ASSETS / "independent-city-exclusions.json").read_text(encoding="utf-8-sig")
    )
    provinces = {p["key"]: p for p in crosswalk["provinces"]}
    excluded_ids = {r["geoname_id"] for r in exclusions["excluded_records"]}
    with ZipFile(archive) as zipped:
        catalog = zipped.read("PH.txt")
    rows = [line.split("\t") for line in catalog.decode("utf-8").splitlines()]
    admins = {int(r[0]): r for r in rows if len(r) == 19 and r[7] == "ADM2"}
    for province in provinces.values():
        row = admins.get(province["geoname_id"])
        if row is None or ".".join([row[8], row[10], row[11]]) != province["key"]:
            raise ValueError("A reviewed province does not match its administrative key.")
    points = []
    for r in rows:
        if len(r) != 19 or r[7] != "ADM3":
            continue
        key = ".".join([r[8], r[10], r[11]])
        province = provinces.get(key)
        if (
            province is None
            or int(r[0]) in excluded_ids
            or r[10] in exclusions["exclude_admin1_codes"]
            or province["geoname_id"] in exclusions["exclude_admin2_geoname_ids"]
        ):
            continue
        points.append(
            {
                "geoname_id": int(r[0]),
                "reference_name": r[1],
                "feature_code": r[7],
                "latitude": float(r[4]),
                "longitude": float(r[5]),
                "country_code": r[8],
                "admin1_code": r[10],
                "admin2_code": r[11],
                "admin3_code": r[12],
                "admin2_geoname_id": province["geoname_id"],
                "admin2_name": province["source_name"],
                "province_code": key,
                "province_name": province["label"],
                "source_modified": r[18],
            }
        )
    points.sort(key=lambda point: point["geoname_id"])
    if len({p["province_code"] for p in points}) != 82:
        raise ValueError("The derivative must retain all 82 reviewed provinces.")
    output.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(points, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    (output / "province-points.json").write_bytes(payload)
    manifest = {
        "version": crosswalk["version"],
        "lookup_policy_version": "geonames-nearest-province-v1",
        "reference_semantics": (
            "ADM3 city/municipality representative points; proximity, not containment"
        ),
        "source_url": "https://download.geonames.org/export/dump/PH.zip",
        "source_archive_sha256": archive_hash,
        "source_catalog_sha256": hashlib.sha256(catalog).hexdigest(),
        "source_snapshot_zip_date": "2026-10-10 (ZIP local timestamp; timezone unspecified)",
        "source_inspected_at_utc": "2026-10-11T01:38:41.4343954Z",
        "reviewed_at": crosswalk["review_date"],
        "license": "CC BY 4.0",
        "attribution": "GeoNames geographical database, https://www.geonames.org/",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "modifications": (
            "ADM3 filtering; explicit PSA province mapping; independent-city exclusions"
        ),
        "generator_version": "build-alert-geography-v1",
        "record_count": len(points),
        "excluded_adm3_count": sum(len(r) == 19 and r[7] == "ADM3" for r in rows) - len(points),
        "province_count": 82,
        "asset_sha256": hashlib.sha256(payload).hexdigest(),
        "crosswalk_sha256": hashlib.sha256(
            (ASSETS / "province-crosswalk.json").read_bytes()
        ).hexdigest(),
        "exclusions_sha256": hashlib.sha256(
            (ASSETS / "independent-city-exclusions.json").read_bytes()
        ).hexdigest(),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=ASSETS)
    arguments = parser.parse_args()
    build(arguments.archive, arguments.output)
