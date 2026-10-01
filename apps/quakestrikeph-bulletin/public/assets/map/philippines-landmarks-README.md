# Philippines mountain and landmark labels

`philippines-landmarks.geojson` contains 2,264 GeoNames mountain and selected
landmark points across the Philippines. It excludes populated places and
administrative areas. Native OpenFreeMap Liberty labels remain enabled and have
higher collision priority; extras supplement them without changing basemap colors.

Source: [GeoNames PH.zip](https://download.geonames.org/export/dump/PH.zip),
downloaded 2026-10-01 at 11:29:17 UTC.
[Source schema](https://download.geonames.org/export/dump/readme.txt).
[GeoNames](https://www.geonames.org/) data is licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The asset is a filtered conversion; names and coordinates were not manually corrected.

Included feature codes: mountains, ranges, peaks and volcanoes, plus the selected
historical sites, monuments, museums, castles, universities, churches and religious
sites from the reference converter. Source codes and modification dates are retained
in each feature. Coordinates are WGS84 reference points, not official boundaries
or hazard information. Community coverage and accuracy are not guaranteed.

Nearby native point labels with matching normalized names suppress extras within
1 km. Case, accents, punctuation and Mount/Mt./Volcano variations are normalized.
Different aliases or larger position errors can still produce duplicates. Identical
names at distant locations remain eligible. Visibility also depends on zoom and
collision placement. A failed asset fetch leaves the native map functional.

To refresh from the local handoff artifacts, run
`apps/quakestrikeph-bulletin/.impeccable/mock/download-philippines-labels.py`,
then extract only `properties.category === "landmarks"` from its
`philippines-labels.geojson` into this asset. Update the snapshot metadata and
record count here and in `tests/map-landmarks.mjs`. The ignored prototype is
not a deployment dependency; the tracked GeoJSON here is served directly.

Verification: `node --experimental-strip-types tests/map-landmarks.mjs` from the
Bulletin app directory, plus the app checks and `tests/mobile-map.cjs`.
