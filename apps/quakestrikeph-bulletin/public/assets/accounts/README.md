# Account screen assets

The Philippine illustration and its prompt sidecar preserve the approved
Map & sheet mockup. Geist Variable is redistributed with `Geist-LICENSE`.

`philippine-places.json` is a compact derived [GeoNames](https://www.geonames.org/)
Philippine place index, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
It contains 46,766 populated and named places, including selected mountains,
beaches and airports. Rows contain name, province/district context, latitude,
longitude and search aliases. Coordinates are internal; the interface displays
place names and map pins. This is neither an address directory nor complete
barangay coverage. Administrative context is the source context, not a claim
that every administrative boundary is current.

For refreshed source data, download `PH.zip` from the
[GeoNames export](https://download.geonames.org/export/dump/PH.zip) and run:

```powershell
python tools/build-account-places.py path/to/PH.zip public/assets/accounts/philippine-places.json
```

Run this from the Bulletin directory. The raw archive stays outside Git.
Review refreshed names, aliases and context before replacing the shipped index;
different source snapshots can change results. The generator only writes a
static JSON asset and never accesses a database.
