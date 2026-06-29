# Welcome to QuakestrikePH Clustering Phase

This is a project on creating an application backed by machine learning approaches to predict the likelihood of an eathequake aftershock sequence based on the historical data presented in ./dataset/phivolcs_earthquake_2018_2026.csv

This is the clustering phase as the current dataset is not yet appropriate for machine learning phase because the features are still lacking. The target clustering algorithm is the Nearest-Neighbor Declustering Algorithm (Zaliapin & Ben-Zion, 2013a). But this project will not claim it to be the exact algorithm, rather it will adapt it to be more accurate on identifying aftershock-mainshock sequences.

Navigate to:
./docs/zaliapin-ben-zion-2013a-algorithm.md
./docs/zaliapin-ben-zion-conceptual-guide.md
./docs/ml_ready_clustered_dataset_schema.md
for more info about the algorithm

'./examples/' contains old files or code, or sample codes for testing. You don't need to worry about this unless you are told to read it.

We are going to implement this clustering using C++ for best performance

OVERRIDE 300 LINES CODE RULE - it's okay here

## Current pipeline decisions

- Use current repo files as the source of truth. Do not let memory or old files in
  `./examples/` override the live pipeline.
- The C++ clustering output is the base dataset for ML training. Validate any
  clustered CSV with `python scripts\validate_clustered_dataset.py <path>`.
- For the Philippines + USGS M1 run, the clustered output is:
  `src\outputs\philippines_phivolcs_usgs_m1\clustered_philippines_phivolcs_usgs_mc_1_0.csv`.
- For the USGS analog M1 deduped run, the clustered output is:
  `src\outputs\usgs_analog_m1_deduped\clustered_usgs_analog_m1_deduped_mc_1_0.csv`.
- These two clustered datasets must include `catalog_source` and `source_region`.
  If clustering is rerun from C++, verify these columns still exist; the current
  C++ writer may drop source metadata unless it is patched or metadata is rejoined
  after clustering.
- `catalog_source` means the catalog provider, for example `USGS` or `PHIVOLCS`.
  `source_region` means the geographic/analog source region, for example
  `philippines`, `japan`, or `indonesia`.
- `src\scripts\build_training_dataset.py` should preserve `catalog_source` and
  `source_region` as metadata and emit numeric one-hot learning features such as
  `catalog_source_usgs` and `source_region_philippines`.
- Training targets now include `m5_plus_aftershock_24h` as a binary
  classification target and `aftershock_count_24h` as an integer count regression
  target. Use Poisson-style objectives for count-capable boosting models.
- Keep the Philippines/local path and USGS analog path as separate model paths
  unless explicitly running a joint-training experiment. Their catalog biases,
  feature manifests, validation reports, and model directories should stay
  separate.

