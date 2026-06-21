# QuakeStrikePH Zaliapin Clustering

This repo builds a Zaliapin-style clustered earthquake dataset, then derives a
shared training set for aftershock models.

The main source catalog is:

```powershell
dataset\phivolcs_earthquake_2018_2026.csv
```

Current generated outputs are written under:

```powershell
src\outputs\
```

## Setup

Install model dependencies as needed:

```powershell
python -m pip install -r requirements-lightgbm.txt
python -m pip install -r requirements-random-forest.txt
python -m pip install -r requirements-xgboost.txt
python -m pip install -r requirements-catboost.txt
```

The clustering runners compile C++ code with `g++`, so make sure `g++` is on
your PATH before running clustering commands.

## Zaliapin Clustering

Run the full nearest-neighbor diagnostics plus clustered dataset generation:

```powershell
python scripts\run_zaliapin_clustering.py
```

Default input:

```powershell
dataset\phivolcs_earthquake_2018_2026.csv
```

Default output:

```powershell
src\outputs\clustered_ml_ready_mc_1_0.csv
```

Run nearest-neighbor diagnostics for one or more magnitude cutoffs:

```powershell
python scripts\run_nn_diagnostics_for_mc.py 1.0 1.5 2.0
```

This writes diagnostic CSVs, GMM threshold files, and plots under
`src\outputs\nn_diagnostics_mc_*`.

Validate a clustered dataset:

```powershell
python scripts\validate_clustered_dataset.py
```

By default this validates:

```powershell
src\outputs\clustered_ml_ready_mc_1_0.csv
```

Validate a specific clustered CSV:

```powershell
python scripts\validate_clustered_dataset.py path\to\clustered.csv
```

Summarize aftershock timing windows from the clustered output:

```powershell
python scripts\analyze_aftershock_time_windows.py
```

Generate or refresh log10-eta histogram plots:

```powershell
python scripts\visualize_log10_eta_histograms.py src\outputs\nn_diagnostics_mc_1_0\log10_eta_histogram.csv
```

Generate an overlay comparison plot for multiple diagnostics:

```powershell
python scripts\visualize_log10_eta_histograms.py "src\outputs\nn_diagnostics_mc_*\log10_eta_histogram.csv" --overlay --overlay-output src\outputs\nn_histogram_comparison.png
```

## Shared Training Dataset

Build the shared model training dataset from the latest clustered dataset:

```powershell
python src\scripts\build_training_dataset.py
```

Default input:

```powershell
src\outputs\clustered_ml_ready_mc_1_0.csv
```

Default outputs:

```powershell
src\training_set\training_dataset_mc_1_0.csv
src\training_set\training_dataset_mc_1_0.features.txt
src\training_set\training_dataset_mc_1_0.targets.txt
```

This dataset is shared by LightGBM, Random Forest, XGBoost, and CatBoost.

### Shared feature engineering

All input-feature logic lives in one module so training and serving never drift:

```powershell
src\scripts\feature_engineering.py
```

`build_training_dataset.py` and every family's `predict_aftershock.py` /
`backtest_aftershock_predictions.py` import their feature builders from it. It is
a library, not a CLI — you do not run it directly; change a feature here and both
training and inference update together.

### Methodology (Path B)

All four families are trained at the catalog's **natural prevalence** (no class
weighting) with log loss, so the raw model probabilities are already calibrated —
there is no post-hoc isotonic step. The chronological split is **train ≤ 2024,
validate 2025, test 2026**. The targets are:

- Classification: `aftershock_24h` plus cumulative containment
  `aftershock_within_{10,25,50,100,200}km_24h`.
- Regression: `max_aftershock_mag_24h` (natural scale) and
  `nearest_/median_/p90_aftershock_distance_km_24h` (trained in `log1p` km space,
  back-transformed to km on output).

## Models

### LightGBM

Train LightGBM classifiers and the magnitude regressor:

```powershell
python src\lightgbm\train_lightgbm_aftershock_models.py
```

Default input:

```powershell
src\training_set\training_dataset_mc_1_0.csv
```

Default output:

```powershell
src\outputs\lightgbm\models_mc_1_0\
```

Run the default production-style sampled backtest:

```powershell
python src\lightgbm\backtest_aftershock_predictions.py
```

Default output:

```powershell
src\outputs\lightgbm\backtests_mc_1_0\
```

Run the backtest across all matching 2025+ events:

```powershell
python src\lightgbm\backtest_aftershock_predictions.py --max-events 0
```

Build the self-contained HTML backtest report (reads the backtest output above):

```powershell
python src\lightgbm\build_backtest_report.py
```

Default output:

```powershell
src\docs\lightgbm_backtest_report.html
```

Run prediction for one event from command-line fields:

```powershell
python src\lightgbm\predict_aftershock.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\lightgbm\predict_aftershock.py --event-csv path\to\one_event.csv --output-json src\outputs\lightgbm\prediction.json
```

### Random Forest

Train Random Forest classifiers and the magnitude regressor:

```powershell
python src\random_forest\train_random_forest_aftershock_models.py
```

Default input:

```powershell
src\training_set\training_dataset_mc_1_0.csv
```

Default output:

```powershell
src\outputs\random-forest\models_mc_1_0\
```

Run a faster sampled training pass while iterating:

```powershell
python src\random_forest\train_random_forest_aftershock_models.py --max-train-rows 20000 --max-validation-rows 5000 --max-test-rows 5000
```

Run the default production-style sampled backtest:

```powershell
python src\random_forest\backtest_aftershock_predictions.py
```

Default output:

```powershell
src\outputs\random-forest\backtests_mc_1_0\
```

Run the backtest across all matching 2025+ events:

```powershell
python src\random_forest\backtest_aftershock_predictions.py --max-events 0
```

Build the self-contained HTML backtest report (reads the backtest output above):

```powershell
python src\random_forest\build_backtest_report.py
```

Default output:

```powershell
src\docs\random-forest_backtest_report.html
```

Run prediction for one event from command-line fields:

```powershell
python src\random_forest\predict_aftershock.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\random_forest\predict_aftershock.py --event-csv path\to\one_event.csv --output-json src\outputs\random-forest\prediction.json
```

### XGBoost

Train XGBoost classifiers and the magnitude regressor:

```powershell
python src\xgboost\train_xgboost_aftershock_models.py
```

Default input:

```powershell
src\training_set\training_dataset_mc_1_0.csv
```

Default output:

```powershell
src\outputs\xgboost\models_mc_1_0\
```

Run a faster sampled training pass while iterating:

```powershell
python src\xgboost\train_xgboost_aftershock_models.py --max-train-rows 20000 --max-validation-rows 5000 --max-test-rows 5000
```

Run the default production-style sampled backtest:

```powershell
python src\xgboost\backtest_aftershock_predictions.py
```

Default output:

```powershell
src\outputs\xgboost\backtests_mc_1_0\
```

Run the backtest across all matching 2025+ events:

```powershell
python src\xgboost\backtest_aftershock_predictions.py --max-events 0
```

Build the self-contained HTML backtest report (reads the backtest output above):

```powershell
python src\xgboost\build_backtest_report.py
```

Default output:

```powershell
src\docs\xgboost_backtest_report.html
```

Run prediction for one event from command-line fields:

```powershell
python src\xgboost\predict_aftershock.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\xgboost\predict_aftershock.py --event-csv path\to\one_event.csv --output-json src\outputs\xgboost\prediction.json
```

### CatBoost

Train CatBoost classifiers and the regressors (CatBoost-native defaults; same
Path B split and target schema as the other families):

```powershell
python src\catboost\train_catboost_aftershock_models.py
```

Default input:

```powershell
src\training_set\training_dataset_mc_1_0.csv
```

Default output:

```powershell
src\outputs\catboost\models_mc_1_0\
```

Run the default production-style sampled backtest:

```powershell
python src\catboost\backtest_aftershock_predictions.py
```

Default output:

```powershell
src\outputs\catboost\backtests_mc_1_0\
```

Run the backtest across all matching 2025+ events:

```powershell
python src\catboost\backtest_aftershock_predictions.py --max-events 0
```

Build the self-contained HTML backtest report (reads the backtest output above):

```powershell
python src\catboost\build_backtest_report.py
```

Default output:

```powershell
src\docs\catboost_backtest_report.html
```

Run prediction for one event from command-line fields:

```powershell
python src\catboost\predict_aftershock.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\catboost\predict_aftershock.py --event-csv path\to\one_event.csv --output-json src\outputs\catboost\prediction.json
```

### SEIS (Hybrid Multi-Model Ensemble)

SEIS is the unified multi-model predictor that serves the best-in-class model per
target across the four families (XGBoost, LightGBM, Random Forest, and CatBoost).
Each target's deployed family is the strongest on the 2025 backtest (production
inference path, Path B / natural prevalence): classification picks minimize Brier,
regression picks maximize R². The picks are assembled from the four families'
backtests into a single report:

```powershell
python src\seis\build_pick_report_from_backtests.py
```

Default output:

```powershell
src\outputs\seis\backtest_pick_report.json
```

That report is the source of truth for the static `HYBRID_MODEL_MAPPING` in
`src/seis/predict.py` (regenerate the report and update the mapping after any
re-train). SEIS reports raw Path B probabilities — there is no isotonic
calibration layer.

Run prediction for one event using command-line fields:

```powershell
python src\seis\predict.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\seis\predict.py --event-csv path\to\one_event.csv --output-json src\outputs\seis\prediction.json
```

Backtest the assembled ensemble end-to-end (rebuilds each event's features
through the production path and scores it with the per-target chosen model, on the
Path B target schema):

```powershell
python src\seis\backtest.py
```

Run across all matching 2025+ events:

```powershell
python src\seis\backtest.py --max-events 0
```

Default output:

```powershell
src\outputs\seis\backtests_mc_1_0\
```

## Reports

Each family ships a self-contained HTML backtest report builder (documented in its
section above); they read that family's `backtests_mc_1_0\` output and write to
`src\docs\<family>_backtest_report.html`:

```powershell
python src\lightgbm\build_backtest_report.py
python src\random_forest\build_backtest_report.py
python src\xgboost\build_backtest_report.py
python src\catboost\build_backtest_report.py
```

The cross-family recommended-model-per-target picks are assembled by the SEIS pick
builder:

```powershell
python src\seis\build_pick_report_from_backtests.py
```

Output:

```powershell
src\outputs\seis\backtest_pick_report.json
```

## Utility Commands

Show yearly event percentages for a catalog:

```powershell
python scripts\yearly_event_percentages.py dataset\phivolcs_earthquake_2018_2026.csv --output src\outputs\mc_diagnostics\yearly_event_percentages.csv
```

Run existing compiled C++ tests:

```powershell
build\tests\test_clustering.exe
build\tests\test_nearest_neighbor_diagnostics.exe
build\tests\test_magnitude_diagnostics.exe
```

Syntax-check the main Python scripts:

```powershell
python -m py_compile scripts\run_zaliapin_clustering.py scripts\run_nn_diagnostics_for_mc.py scripts\validate_clustered_dataset.py scripts\analyze_aftershock_time_windows.py scripts\visualize_log10_eta_histograms.py scripts\yearly_event_percentages.py src\scripts\build_training_dataset.py src\scripts\feature_engineering.py src\lightgbm\train_lightgbm_aftershock_models.py src\lightgbm\predict_aftershock.py src\lightgbm\backtest_aftershock_predictions.py src\lightgbm\build_backtest_report.py src\random_forest\train_random_forest_aftershock_models.py src\random_forest\predict_aftershock.py src\random_forest\backtest_aftershock_predictions.py src\random_forest\build_backtest_report.py src\xgboost\train_xgboost_aftershock_models.py src\xgboost\predict_aftershock.py src\xgboost\backtest_aftershock_predictions.py src\xgboost\build_backtest_report.py src\catboost\train_catboost_aftershock_models.py src\catboost\predict_aftershock.py src\catboost\backtest_aftershock_predictions.py src\catboost\build_backtest_report.py src\seis\predict.py src\seis\backtest.py src\seis\build_pick_report_from_backtests.py
```
