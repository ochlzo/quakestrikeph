# QuakeStrikePH Agent Notes

Use current repo files as the source of truth. Keep answers and changes concise,
practical, and implementation-focused. Verify before assuming.

## Project Context

This project builds a Zaliapin-style clustered earthquake dataset, then derives
ML training datasets for aftershock prediction. The clustering implementation is
C++ for performance. The project adapts the Zaliapin & Ben-Zion nearest-neighbor
approach for aftershock-mainshock sequence identification; do not claim it is an
exact implementation of the paper.

Read these docs for clustering context when needed:

- `docs/zaliapin-ben-zion-2013a-algorithm.md`
- `docs/zaliapin-ben-zion-conceptual-guide.md`
- `docs/ml_ready_clustered_dataset_schema.md`
- `src/docs/massive_earthquakes_modeling_reference.md`

`./examples/` contains old or sample code. Ignore it unless explicitly asked.

## Current Pipeline Decisions

- Validate clustered CSVs with:
  `python scripts\validate_clustered_dataset.py <path>`
- Philippines + USGS M1 clustered output:
  `src\outputs\philippines_phivolcs_usgs_m1\clustered_philippines_phivolcs_usgs_mc_1_0.csv`
- USGS analog M1 deduped clustered output:
  `src\outputs\usgs_analog_m1_deduped\clustered_usgs_analog_m1_deduped_mc_1_0.csv`
- Both clustered outputs must include `catalog_source` and `source_region`.
- `catalog_source` is the provider, for example `USGS` or `PHIVOLCS`.
- `source_region` is the geographic or analog region, for example
  `philippines`, `japan`, or `indonesia`.
- If clustering is rerun from C++, verify `catalog_source` and `source_region`
  are still present. The current C++ clustered writer may drop source metadata
  unless it is patched or metadata is rejoined after clustering.

## Training Dataset Contract

`src\scripts\build_training_dataset.py` should:

- Preserve `catalog_source` and `source_region` as metadata columns.
- Emit numeric one-hot learning features for them, such as
  `catalog_source_usgs` and `source_region_philippines`.
- Include `m5_plus_aftershock_24h` as a binary classification target.
- Include `aftershock_count_24h` as an integer count regression target.
- Keep existing 24h probability, distance, spatial-zone, and max-magnitude
  targets unless explicitly changing the target contract.

Use Poisson-style objectives for `aftershock_count_24h` in boosting models that
support count objectives. For models that do not support Poisson directly, use a
careful fallback such as standard regression or a `log1p` variant only when the
training code is explicitly updated to support it.

Keep the Philippines/local path and USGS analog path as separate model paths
unless explicitly running a joint-training experiment. Their catalog biases,
feature manifests, validation reports, and model directories should remain
separate.
