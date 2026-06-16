# Recommended Model per Target

Based on the backtest results in `src/outputs/{lightgbm,random-forest,xgboost}/backtests_mc_1_0/backtest_metrics.json`.

All three models were evaluated under identical conditions, so the metrics are directly comparable:

- **Test holdout:** events from 2025 onward (`test_start_year: 2025`)
- **Sample:** balanced, 500 rows (`max_events: 500`, `sample_mode: balanced`) from 29,720 candidates
- **Minimum magnitude:** mc = 1.0

Primary selection criteria: ROC-AUC and Average Precision (threshold-independent ranking quality), with Brier score for calibration.

## Recommendation Summary

| Target | Recommended Model | ROC-AUC | Avg Precision | Brier | Recall @ 0.5 | Notes |
|---|---|---|---|---|---|---|
| `aftershock_24h` | **XGBoost** | 0.967 | 0.961 | 0.069 | 0.920 | LightGBM edges AUC/AP marginally, but XGBoost has the best calibration (Brier 0.069) and recall (0.920), preferred for an occurrence alarm where missed detections are costly. |
| `aftershock_dist_0_10km_24h` | **XGBoost** | 0.954 | 0.932 | 0.128 | 0.550 | Best on all three metrics, including calibration (Brier 0.128). |
| `aftershock_dist_10_25km_24h` | **LightGBM** | 0.965 | 0.936 | 0.082 | 0.810 | Best on all three metrics, including calibration (Brier 0.082). |
| `aftershock_dist_25_50km_24h` | **LightGBM** | 0.962 | 0.928 | 0.146 | 0.370 | Best calibration (Brier 0.146 vs RF 0.196) and highest out-of-the-box recall. Highly recommended for physical probability output. |
| `aftershock_dist_50_100km_24h` | **XGBoost** | 0.915 | 0.756 | 0.098 | 0.500 | Best calibration (Brier 0.098 vs LightGBM 0.100) and highest default recall (0.500). |
| `aftershock_dist_100_200km_24h` | **XGBoost** | 0.936 | 0.689 | 0.065 | 0.433 | Best on all three metrics, including calibration (Brier 0.065). |
| `aftershock_dist_200_pluskm_24h` | **LightGBM** | 0.907 | 0.652 | 0.052 | 0.302 | Best Brier score (0.052), ROC-AUC, and AP. |
| `max_aftershock_mag_24h` (regression) | **Random Forest** | R² = 0.43 | MAE = 0.694 | — | — | Decisively best (XGBoost R² 0.28, LightGBM R² 0.09). |

## Grouped by Model

- **XGBoost:** `aftershock_24h`, `aftershock_dist_0_10km_24h`, `aftershock_dist_50_100km_24h`, `aftershock_dist_100_200km_24h`
- **LightGBM:** `aftershock_dist_10_25km_24h`, `aftershock_dist_25_50km_24h`, `aftershock_dist_200_pluskm_24h`
- **Random Forest:** `max_aftershock_mag_24h` (regression)

## Caveats

- **Random Forest calibration:** RF's ranking quality (AUC/AP) is competitive and sometimes best. By applying probability calibration (Isotonic Regression calibrated on validation split), we improved its `aftershock_24h` recall at 0.5 to **0.60** (up from 0.42) and Brier to **0.141** (down from 0.171). However, its Brier scores are still 2x worse than XGBoost and LightGBM. Therefore, we prefer XGBoost and LightGBM for the distance classification bins to ensure well-calibrated physical probabilities.
- **Magnitude regression is weak overall:** the best R² is 0.43 (improved from 0.41 by setting `min_samples_leaf=4`), so treat `max_aftershock_mag_24h` predictions as rough estimates. This target likely needs more feature engineering regardless of model choice.
