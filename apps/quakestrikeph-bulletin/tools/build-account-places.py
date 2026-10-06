"""Derive a small attributed Philippine search index from GeoNames PH.zip."""

import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    source, destination = map(Path, sys.argv[1:])
    with zipfile.ZipFile(source) as archive:
        rows = [
            line.split("\t")
            for line in archive.read("PH.txt").decode("utf-8").splitlines()
        ]
    provinces = {(r[10], r[11]): r[1] for r in rows if r[7] == "ADM2"}
    regions = {r[10]: r[1] for r in rows if r[7] == "ADM1"}
    places = {}
    for r in rows:
        if r[7] not in {"ADM1", "ADM3"}:
            continue
        context = "Philippines" if r[7] == "ADM1" else provinces.get(
            (r[10], r[11]), regions.get(r[10], "Philippines")
        )
        latitude, longitude = float(r[4]), float(r[5])
        aliases = sorted({r[1], r[2], *r[3].split(",")} - {""})[:10]
        places[(r[1], latitude, longitude)] = [
            r[1],
            context,
            latitude,
            longitude,
            ",".join(aliases),
        ]
    index = sorted(places.values(), key=lambda p: (p[0].casefold(), p[1]))
    destination.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(index)} places; retain GeoNames CC BY attribution.")


if __name__ == "__main__":
    main()
