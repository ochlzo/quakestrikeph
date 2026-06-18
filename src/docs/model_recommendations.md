# Recommended Model per Target

Classification picks are made on **calibrated probability quality at deployment
prevalence**, evaluated over the full 2025+ holdout pool. See
`src/outputs/seis/calibration/repick_report.json` (and the diagnostic
`calibration_report.json`) produced by the scripts in `src/seis/`.

## Why this supersedes the earlier balanced-sample, raw-Brier picks

The previous version selected each bin by raw Brier score on a **balanced 500-row
sample**. That had three problems, all confirmed by the full-pool analysis:

1. **Wrong prevalence.** The balanced sample over-samples positives ~1.5x versus
   the real pool (e.g. `aftershock_24h` 0.50 sampled vs **0.318** in the pool;
   `aftershock_dist_200_pluskm_24h` 0.086 vs **0.060**). Brier and calibration are
   prevalence-dependent, so the balanced-sample numbers do not reflect deployment.
2. **Unequal preprocessing.** Random Forest was judged on its *uncalibrated*
   output against natively-calibrated boosting models and dismissed for "2x worse
   Brier." Applying the **same** isotonic calibration to all three families
   removes this confound — and RF then wins several distance bins outright.
3. **Inconsistent stated criteria.** The doc claimed ROC-AUC/AP as primary while
   actually picking on raw Brier.

The product outputs a **probability (percentage)**, so the right objective is a
well-calibrated probability. Calibration is a cheap post-hoc layer applied
equally to every family, not a property to select models on. The pipeline is
therefore: train -> calibrate on a held-out split -> select on calibrated
quality + ranking.

## Evaluation protocol

- **Features:** rebuilt with the production inference path per event (not the
  precomputed training-dataset features), so models and calibrators see the exact
  distribution served at inference. (Note a known train/serve skew in the parent /
  `eta` features — see Caveats.)
- **Calibrators:** per-family isotonic regression fit on the **2024 validation
  year** (`src/seis/fit_calibrators.py`) — data the models did not train on.
- **Selection set:** the full **2025+ pool (29,720 events)** at natural
  prevalence. Calibrators never saw this pool, so calibrated metrics are genuinely
  out-of-sample.
- **Primary criterion:** lowest calibrated Brier; ROC-AUC / AP reported alongside
  so ranking quality is visible. Bootstrap 95% CIs on the Brier difference guard
  against picking on noise (`src/seis/calibration_analysis.py`).

## Recommendation Summary (classification)

| Target | Recommended Model | Pool prevalence | Calibrated Brier | Calibrated ECE | ROC-AUC | Avg Precision |
|---|---|---|---|---|---|---|
| `aftershock_24h` | **LightGBM** | 0.318 | 0.0536 | 0.018 | 0.975 | 0.955 |
| `aftershock_dist_0_10km_24h` | **XGBoost** | 0.258 | 0.0630 | 0.038 | 0.967 | 0.922 |
| `aftershock_dist_10_25km_24h` | **LightGBM** | 0.257 | 0.0540 | 0.030 | 0.977 | 0.937 |
| `aftershock_dist_25_50km_24h` | **Random Forest** | 0.228 | 0.0458 | 0.026 | 0.972 | 0.922 |
| `aftershock_dist_50_100km_24h` | **LightGBM** | 0.151 | 0.0500 | 0.018 | 0.968 | 0.864 |
| `aftershock_dist_100_200km_24h` | **Random Forest** | 0.080 | 0.0339 | 0.034 | 0.963 | 0.766 |
| `aftershock_dist_200_pluskm_24h` | **LightGBM** | 0.060 | 0.0284 | 0.020 | 0.961 | 0.746 |

### Regression targets (unchanged — not affected by probability calibration)

| Target | Recommended Model | Metric | Notes |
|---|---|---|---|
| `max_aftershock_mag_24h` | **Random Forest** | R² = 0.43, MAE = 0.694 | Decisively best (XGBoost R² 0.28, LightGBM R² 0.09). Weak overall — treat as a rough estimate. |
| `max_aftershock_distance_km_24h` | **LightGBM** | R² = 0.43, MAE = 81.8 km | Only family trained for this target; predicts warning radius from epicenter. |

## Changes from the previous recommendation

4 of 7 classification picks change once selection is done on calibrated metrics at
deployment prevalence:

| Target | Was | Now | Reason |
|---|---|---|---|
| `aftershock_24h` | XGBoost | LightGBM | Best calibrated Brier + best AUC/AP (gap significant). |
| `aftershock_dist_25_50km_24h` | LightGBM | Random Forest | RF best calibrated Brier (0.046) **and** best AUC/AP — previously excluded only because it was uncalibrated. |
| `aftershock_dist_50_100km_24h` | XGBoost | LightGBM | Best calibrated Brier and AUC/AP. |
| `aftershock_dist_100_200km_24h` | XGBoost | Random Forest | Best calibrated Brier (0.034). |

`aftershock_dist_0_10km_24h` stays XGBoost, but it is a statistical tie with
LightGBM (calibrated Brier 0.0630 vs 0.0631).

## Grouped by Model

- **LightGBM:** `aftershock_24h`, `aftershock_dist_10_25km_24h`,
  `aftershock_dist_50_100km_24h`, `aftershock_dist_200_pluskm_24h`,
  `max_aftershock_distance_km_24h` (regression)
- **XGBoost:** `aftershock_dist_0_10km_24h`
- **Random Forest:** `aftershock_dist_25_50km_24h`,
  `aftershock_dist_100_200km_24h`, `max_aftershock_mag_24h` (regression)

## Deployment

The SEIS hybrid predictor (`src/seis/predict.py`) realizes these picks via
`HYBRID_MODEL_MAPPING` and applies the matching isotonic calibrator to every
classification probability before output. Calibrators live in
`src/outputs/seis/calibration/calibrators/` (`{family}__{target}.joblib`); the
predictor **errors out** if a required calibrator is missing rather than reporting
uncalibrated probabilities.

## Caveats

- **Train/serve feature skew (follow-up).** The training dataset assigns the
  parent event from the precomputed Zaliapin-Ben-Zion clustering (`parent_id_key`
  in `src/scripts/build_training_dataset.py`), whereas the production inference
  path re-derives the nearest-neighbor parent by scanning prior history
  (`compute_parent_features` in `src/lightgbm/predict_aftershock.py`). These
  produce different `eta` / `parent_*` features, so the deployed model sees a
  slightly different feature distribution than it trained on. All metrics here use
  the production path (deployment-faithful), but reconciling the two
  parent-assignment methods is an open item that could lift every model.
- **Calibrated Brier is tight across families.** After equal calibration the
  per-bin gaps are small (e.g. `aftershock_24h`: 0.0536 / 0.0559 / 0.0557). The
  large raw-Brier gaps that drove the old picks were mostly native calibration,
  not information content. Picks favor the family that also leads on ranking
  (AUC/AP) where calibrated Brier is close.
- **Magnitude regression is weak.** Best R² is 0.43; `max_aftershock_mag_24h`
  predictions are rough estimates and likely need more feature engineering
  regardless of model choice.
