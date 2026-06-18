# Recommended Model per Target

Each target is served by one of three families (XGBoost, LightGBM, Random
Forest). The family is **selected on 2024** — the most recent data available at
decision time — and the **2025+ holdout is used only to confirm** how the pick
performs out-of-sample. Selection never looks at the holdout.

- **Classification:** pick the family with the lowest **5-fold out-of-fold
  isotonic-calibrated Brier on 2024** (`src/seis/repick_bins.py`, reading
  `validation_raw_predictions.csv`). Out-of-fold calibration avoids in-sample
  optimism and treats every family identically.
- **Regression:** pick the family with the highest **2024 validation R²**
  (`metrics.json`).
- **Confirmation:** per-family scores on the full 2025+ pool come from
  `src/seis/backtest.py` (`backtest_metrics.json`) — calibrated, out-of-sample,
  at natural deployment prevalence.

> **This supersedes the earlier holdout-selected picks.** The previous version
> chose each family by calibrated Brier **on the 2025+ pool itself**, then
> reported that same pool — circular hindsight selection. Selecting on 2024
> instead changed **6 of 9** picks (see below). The honest picks are sometimes
> *not* the family that ended up best on 2025; that gap is the unavoidable price
> of choosing without seeing the future, and is reported under "Cost of honest
> selection".

> **All models retrained after a feature bug fix (2026-06).** The historical
> count features (`events_past_*`, `local_events_*`) were corrupted by a
> datetime-unit error in `build_training_dataset.py` (microseconds vs
> nanoseconds), collapsing the counts to the catalog row index. After the fix
> (cast to `datetime64[ns]` before `int64`) and a full retrain, results improved
> substantially (magnitude regression R² ~0.43 → ~0.65). The numbers below are
> from the corrected models.

## Recommendation summary (classification)

Brier columns: **2024 OOF** is the selection metric; **2025** is out-of-sample
confirmation. AUC/AP are on the 2025+ pool.

| Target | Pick | Prev. (2025) | 2024 OOF Brier (selection) | 2025 Brier | 2025 ROC-AUC | 2025 AP |
|---|---|---|---|---|---|---|
| `aftershock_24h` | **XGBoost** | 0.318 | 0.0446 | 0.0423 | 0.982 | 0.969 |
| `aftershock_dist_0_10km_24h` | **XGBoost** | 0.258 | 0.0557 | 0.0516 | 0.973 | 0.938 |
| `aftershock_dist_10_25km_24h` | **XGBoost** | 0.257 | 0.0412 | 0.0378 | 0.986 | 0.966 |
| `aftershock_dist_25_50km_24h` | **XGBoost** | 0.228 | 0.0340 | 0.0405 | 0.988 | 0.960 |
| `aftershock_dist_50_100km_24h` | **Random Forest** | 0.151 | 0.0370 | 0.0618 | 0.968 | 0.843 |
| `aftershock_dist_100_200km_24h` | **Random Forest** | 0.080 | 0.0291 | 0.0346 | 0.976 | 0.836 |
| `aftershock_dist_200_pluskm_24h` | **Random Forest** | 0.060 | 0.0092 | 0.0246 | 0.964 | 0.789 |

### Regression targets

| Target | Pick | 2024 val R² (selection) | 2025 R² | 2025 MAE |
|---|---|---|---|---|
| `max_aftershock_mag_24h` | **XGBoost** | 0.455 | 0.654 | 0.521 |
| `max_aftershock_distance_km_24h` | **Random Forest** | 0.571 | 0.600 | 67.5 km |

## Grouped by model

- **XGBoost:** `aftershock_24h`, `aftershock_dist_0_10km_24h`,
  `aftershock_dist_10_25km_24h`, `aftershock_dist_25_50km_24h`,
  `max_aftershock_mag_24h` (regression)
- **Random Forest:** `aftershock_dist_50_100km_24h`,
  `aftershock_dist_100_200km_24h`, `aftershock_dist_200_pluskm_24h`,
  `max_aftershock_distance_km_24h` (regression)
- **LightGBM:** *none.* Under honest 2024 selection LightGBM is not the best
  family for any target (it was previously deployed for three bins on hindsight).
  It stays competitive and is retained as a candidate.

## Changes from the previous recommendation

Previous picks were selected on the 2025+ pool; these are selected on 2024.
**6 of 9 changed:**

| Target | Was (2025-selected) | Now (2024-selected) |
|---|---|---|
| `aftershock_dist_10_25km_24h` | LightGBM | **XGBoost** |
| `aftershock_dist_25_50km_24h` | Random Forest | **XGBoost** |
| `aftershock_dist_50_100km_24h` | LightGBM | **Random Forest** |
| `aftershock_dist_100_200km_24h` | XGBoost | **Random Forest** |
| `aftershock_dist_200_pluskm_24h` | LightGBM | **Random Forest** |
| `max_aftershock_distance_km_24h` | XGBoost | **Random Forest** |

`aftershock_24h`, `aftershock_dist_0_10km_24h`, and `max_aftershock_mag_24h`
(all XGBoost) are unchanged — those families win honestly on 2024 too.

## Cost of honest selection

The deployed picks (chosen on 2024) average a **2025 calibrated Brier of 0.0419**
across the seven classification bins. If you could instead pick the family that
turned out best on 2025 — foreknowledge you do not have at decision time — the
average would be **0.0399**. The **+0.0020** gap is the price of honesty.

Concretely, the honest pick is *not* the 2025 winner on 5 of 7 bins (most
visibly `aftershock_dist_100_200km_24h`, where the 2024 pick Random Forest scores
0.0346 on 2025 while XGBoost scores 0.0274). That lead is only knowable after the
fact, so it is not deployable — exactly the trap the old selection fell into.

## Deployment

`src/seis/predict.py` realizes these picks via `HYBRID_MODEL_MAPPING` and applies
the matching isotonic calibrator (fit on 2024) to every classification
probability before output. Calibrators live in
`src/outputs/seis/calibration/calibrators/`; the predictor errors out if a
required calibrator is missing rather than reporting uncalibrated probabilities.

## Ensemble (out of scope here)

An equal-weight ensemble of the three calibrated families (`mean_cal`) beats this
single-model-per-target deployment on the same honest basis (~0.0401 vs 0.0419
mean 2025 Brier). Ensembling is being developed in a dedicated sibling project
and is intentionally **not** part of this single-model recommendation.

## Caveats

- **Honest selection underperforms hindsight on rare bins.** Where positives are
  scarce (50–100 km and beyond), the 2024 estimate is noisier and the 2024 pick
  can lag the 2025 winner. This is expected and is the correct trade — see "Cost
  of honest selection".
- **Feature-count bug fixed (resolved).** `events_past_*` / `local_events_*`
  were corrupted by a datetime-unit error; fixed by casting `event_time` to
  `datetime64[ns]` before `int64`. Train-vs-production feature parity is now ~0.
- **Production feature path.** Confirmation metrics use the deployed inference
  path (features rebuilt per event), so they reflect what the served model
  actually sees, including the parent / `eta` features.
