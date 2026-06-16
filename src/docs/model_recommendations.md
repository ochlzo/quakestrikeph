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
| `aftershock_24h` | **XGBoost** | 0.967 | 0.961 | 0.069 | 0.920 | LightGBM edges AUC/AP marginally, but XGBoost has the best calibration and recall (0.920), preferred for an occurrence alarm where missed detections are costly. |
| `aftershock_dist_0_10km_24h` | **XGBoost** | 0.954 | 0.932 | 0.128 | 0.550 | Best on all three metrics. |
| `aftershock_dist_10_25km_24h` | **LightGBM** | 0.965 | 0.936 | 0.082 | 0.810 | Best on all three metrics. |
| `aftershock_dist_25_50km_24h` | **Random Forest** | 0.983 | 0.974 | 0.198 | 0.103 | Best ranking by a clear margin, but recall at 0.5 is only 0.103 — requires threshold tuning. Use only if ranking (AUC/AP) outweighs out-of-the-box recall; otherwise LightGBM (AUC 0.962 / AP 0.928 / Recall 0.370). |
| `aftershock_dist_50_100km_24h` | **LightGBM** | 0.918 | 0.780 | 0.100 | 0.465 | Random Forest wins ranking (AUC 0.939 / AP 0.833) but needs threshold tuning; LightGBM is the best well-calibrated choice. Prefer Random Forest if already threshold-tuning. |
| `aftershock_dist_100_200km_24h` | **XGBoost** | 0.936 | 0.689 | 0.065 | 0.433 | Best on all three metrics. |
| `aftershock_dist_200_pluskm_24h` | **LightGBM** | 0.907 | 0.652 | 0.052 | 0.302 | Best AUC and AP. |
| `max_aftershock_mag_24h` (regression) | **Random Forest** | R² = 0.41 | MAE = 0.706 | — | — | Decisively best (XGBoost R² 0.28, LightGBM R² 0.09). |

## Grouped by Model

- **XGBoost:** `aftershock_24h`, `aftershock_dist_0_10km_24h`, `aftershock_dist_100_200km_24h`
- **LightGBM:** `aftershock_dist_10_25km_24h`, `aftershock_dist_50_100km_24h`, `aftershock_dist_200_pluskm_24h`
- **Random Forest:** `aftershock_dist_25_50km_24h` (if ranking outweighs recall), `max_aftershock_mag_24h` (regression)

## Caveats

- **Random Forest calibration:** RF's ranking quality (AUC/AP) is competitive and sometimes best, but its probabilities are poorly calibrated — at a 0.5 threshold it predicts very few positives (e.g. `aftershock_24h` recall 0.42 vs 0.87 LightGBM / 0.92 XGBoost), and its Brier scores are 2–3× worse. Any RF classification deployment must tune the decision threshold or calibrate the probabilities rather than using 0.5. Its regression win needs no such caveat.
- **Magnitude regression is weak overall:** the best R² is only 0.41, so treat `max_aftershock_mag_24h` predictions as rough estimates. This target likely needs more feature engineering regardless of model choice.
