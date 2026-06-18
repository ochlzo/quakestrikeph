# Recommended Model per Target

Classification picks are made on **calibrated probability quality at deployment
prevalence**, evaluated over the full 2025+ holdout pool. See
`src/outputs/seis/calibration/repick_report.json` (and the diagnostic
`calibration_report.json`) produced by the scripts in `src/seis/`.

> **All models retrained after a feature bug fix (2026-06).** The historical
> count features (`events_past_*`, `local_events_*`) were corrupted by a
> datetime-unit error in `build_training_dataset.py`: under pandas 3.0 the event
> times parse as microseconds, but the window arithmetic hardcoded nanoseconds,
> so the counts collapsed to the catalog row index (tens of thousands) instead of
> the true event count. Every family was trained on this garbage. After the fix
> (cast to `datetime64[ns]` before `int64`) and a full retrain, results improved
> substantially — most dramatically the magnitude regression
> (`max_aftershock_mag_24h` R² 0.43 -> 0.65) and across all classification AUCs.
> The numbers below are from the corrected models.

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
| `aftershock_24h` | **XGBoost** | 0.318 | 0.0423 | 0.008 | 0.982 | 0.972 |
| `aftershock_dist_0_10km_24h` | **XGBoost** | 0.258 | 0.0516 | 0.013 | 0.974 | 0.943 |
| `aftershock_dist_10_25km_24h` | **LightGBM** | 0.257 | 0.0362 | 0.008 | 0.986 | 0.968 |
| `aftershock_dist_25_50km_24h` | **Random Forest** | 0.228 | 0.0382 | 0.019 | 0.987 | 0.958 |
| `aftershock_dist_50_100km_24h` | **LightGBM** | 0.151 | 0.0604 | 0.056 | 0.960 | 0.851 |
| `aftershock_dist_100_200km_24h` | **XGBoost** | 0.080 | 0.0274 | 0.033 | 0.982 | 0.890 |
| `aftershock_dist_200_pluskm_24h` | **LightGBM** | 0.060 | 0.0232 | 0.019 | 0.950 | 0.823 |

### Regression targets

| Target | Recommended Model | Metric | Notes |
|---|---|---|---|
| `max_aftershock_mag_24h` | **XGBoost** | R² = 0.65, MAE = 0.521 | Best of the three (LightGBM 0.645, RF 0.639) — all now close after the feature fix lifted R² from ~0.43. |
| `max_aftershock_distance_km_24h` | **LightGBM** | R² = 0.58, MAE = 73.7 km | Only family trained for this target; predicts warning radius from epicenter (up from R² 0.43). |

## Changes from the previous recommendation

Picks were last set on the *corrupted-feature* models. After the feature fix and
retrain, selecting on calibrated metrics at deployment prevalence gives:

| Target | Was | Now | Reason |
|---|---|---|---|
| `aftershock_24h` | LightGBM | XGBoost | Best calibrated Brier (0.042) + best AUC/AP. Tight vs LightGBM (0.043). |
| `aftershock_dist_100_200km_24h` | Random Forest | XGBoost | Best calibrated Brier (0.027) + best AUC/AP after retrain. |
| `max_aftershock_mag_24h` (reg.) | Random Forest | XGBoost | Corrected features lifted all three to R² ~0.64; XGBoost now narrowly best. |

The other four classification bins keep their family. `aftershock_dist_0_10km_24h`
(XGBoost) and `aftershock_24h` (XGBoost) are near-ties with the runner-up on
calibrated Brier; picks break toward the family that also leads AUC/AP.

## Grouped by Model

- **XGBoost:** `aftershock_24h`, `aftershock_dist_0_10km_24h`,
  `aftershock_dist_100_200km_24h`, `max_aftershock_mag_24h` (regression)
- **LightGBM:** `aftershock_dist_10_25km_24h`, `aftershock_dist_50_100km_24h`,
  `aftershock_dist_200_pluskm_24h`, `max_aftershock_distance_km_24h` (regression)
- **Random Forest:** `aftershock_dist_25_50km_24h`

## Deployment

The SEIS hybrid predictor (`src/seis/predict.py`) realizes these picks via
`HYBRID_MODEL_MAPPING` and applies the matching isotonic calibrator to every
classification probability before output. Calibrators live in
`src/outputs/seis/calibration/calibrators/` (`{family}__{target}.joblib`); the
predictor **errors out** if a required calibrator is missing rather than reporting
uncalibrated probabilities.

## Caveats

- **Feature-count bug fixed (resolved).** The `events_past_*` / `local_events_*`
  features were corrupted by a datetime-unit error (microseconds vs nanoseconds)
  in `build_training_dataset.py`, collapsing them to the catalog row index. Fixed
  by casting `event_time` to `datetime64[ns]` before `int64` in
  `add_recent_global_features` / `add_recent_local_features`; train-vs-production
  feature parity is now ~0 (was ~10^5). All models retrained. This was the actual
  train/serve skew — an earlier note incorrectly attributed it to the parent /
  `eta` features, which in fact match the production path exactly.
- **Calibrated Brier is tight across families.** After equal calibration the
  per-bin gaps are small (e.g. `aftershock_24h`: 0.042 / 0.043 / 0.045). The
  large raw-Brier gaps that drove the old picks were mostly native calibration,
  not information content. Picks favor the family that also leads on ranking
  (AUC/AP) where calibrated Brier is close.
- **Magnitude regression is now usable.** After the feature fix,
  `max_aftershock_mag_24h` reaches R² ~0.65 (was ~0.43) and
  `max_aftershock_distance_km_24h` R² ~0.58 (was ~0.43). Still treat magnitude as
  an estimate with ±0.5 typical error (MAE 0.52), but it is no longer the weak
  spot it was.
