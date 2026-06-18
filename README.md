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

Run prediction for one event from command-line fields:

```powershell
python src\xgboost\predict_aftershock.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\xgboost\predict_aftershock.py --event-csv path\to\one_event.csv --output-json src\outputs\xgboost\prediction.json
```

Compare LightGBM and Random Forest prediction outputs and runtime using the
same input event:

```powershell
python src\scripts\compare_predict_aftershock.py
```

Compare LightGBM, Random Forest, and XGBoost prediction outputs and runtime:

```powershell
python src\scripts\compare_predict_aftershock.py --include-xgboost
```

Compare both predictors with a one-row event CSV:

```powershell
python src\scripts\compare_predict_aftershock.py --event-csv path\to\one_event.csv
```

### CatBoost

Train CatBoost classifiers and the regressors (train -> validate -> test split,
mirroring the other families' hyperparameters):

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

CatBoost is evaluated as a fourth family by the SEIS selection pipeline
(walk-forward folds and the validation-based re-pick) and is served directly by
SEIS where it wins; it does not ship a standalone `predict`/`backtest` CLI.

### SEIS (Hybrid Multi-Model Ensemble)

SEIS is the unified multi-model predictor that combines the best-in-class models (XGBoost, LightGBM, Random Forest, and CatBoost). Each target's deployed family is chosen honestly on the 2024 validation year by `src/seis/repick_bins.py` (written to `src/outputs/seis/calibration/repick_report.json`); the 2025+ holdout is reserved for the backtest and never used for selection.

Run prediction for one event using command-line fields:

```powershell
python src\seis\predict.py --date-time "26 April 2026 - 03:20 PM" --latitude 10.0 --longitude 125.0 --depth 20 --magnitude 4.5
```

Run prediction for one event from a one-row CSV:

```powershell
python src\seis\predict.py --event-csv path\to\one_event.csv --output-json src\outputs\seis\prediction.json
```

Run the sampled backtest to calculate combined hybrid metrics:

```powershell
python src\seis\backtest.py
```

Default output:

```powershell
src\outputs\seis\backtests_mc_1_0\
```

## Reports

Generate the Random Forest report and LightGBM-vs-Random-Forest comparison
report:

```powershell
python src\reports\generate_random_forest_reports.py
```

Outputs:

```powershell
src\reports\random_forest_model_report.html
src\reports\lightgbm_vs_random_forest_comparison_report.html
```

This report generator expects the model-comparison CSVs to already exist under:

```powershell
src\outputs\model-comparison\mc_1_0\
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
python -m py_compile scripts\run_zaliapin_clustering.py scripts\run_nn_diagnostics_for_mc.py scripts\validate_clustered_dataset.py src\scripts\build_training_dataset.py src\scripts\compare_predict_aftershock.py src\lightgbm\train_lightgbm_aftershock_models.py src\lightgbm\predict_aftershock.py src\lightgbm\backtest_aftershock_predictions.py src\random_forest\train_random_forest_aftershock_models.py src\random_forest\predict_aftershock.py src\random_forest\backtest_aftershock_predictions.py src\xgboost\train_xgboost_aftershock_models.py src\xgboost\predict_aftershock.py src\xgboost\backtest_aftershock_predictions.py src\catboost\train_catboost_aftershock_models.py src\seis\predict.py src\seis\backtest.py src\seis\fit_calibrators.py src\seis\calibration_score.py src\seis\repick_bins.py src\seis\pick_on_test.py src\seis\calibration_analysis.py src\seis\significance_check.py src\seis\walk_forward_pick.py src\seis\build_html_report.py src\seis\build_findings_report.py
```
