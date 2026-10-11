# Geographic reference asset

GeoNames supplies the source under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Attribute [GeoNames](https://www.geonames.org/) when distributing this derivative.
The source is the [Philippines dump](https://download.geonames.org/export/dump/PH.zip).
The manifest pins its archive and catalog hashes, source snapshot, inspection time, and generator version.

The derivative retains 1,595 ADM3 municipality/city representative points across 82 reviewed provinces.
These points represent administrative places; they are not province boundaries or guaranteed city centres.
The explicit province crosswalk uses administrative identifiers reviewed against the PSA province list.
The exclusion file records NCR districts and independent cities reviewed against PSA HUC/ICC lists.
The derivative filters the source, applies these reviewed mappings, and normalizes the retained records.
Missing or ambiguous province metadata remains excluded.

The alert renderer selects the nearest suitable reference within inclusive 100 km.
The label says `near` because proximity does not establish containment.
The renderer preserves unchanged PHIVOLCS location text when no suitable point qualifies.
The display lookup does not affect recipient eligibility or forecast activity radius.

To reproduce the asset, run this command from the repository root with the pinned archive outside Git:

```powershell
python workers/scripts/build_alert_geography.py C:/path/to/pinned/PH.zip
```

The generator rejects a different archive hash.
The package contains the reviewed crosswalk, exclusions, derivative, manifest, and attribution.
Runtime rendering requires no GeoNames network access or ignored prototype asset.
The worker verifies the derivative hash before resolving labels.
