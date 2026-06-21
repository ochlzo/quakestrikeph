# Candidate Prediction Targets

What else this dataset can plausibly predict, beyond the nine targets currently
trained (`src/training_set/training_dataset_mc_1_0.targets.txt`).

The assessment is grounded in columns that already exist in
`src/outputs/clustered_ml_ready_mc_1_0.csv` (the Zaliapin-Ben-Zion clustered
catalog) and the leakage-safe feature/target construction in
`src/scripts/build_training_dataset.py`.

## Ground rules (why some targets are feasible and others are traps)

1. **Features are strictly backward-looking.** Every feature is computed from
   events *before* the current one (`filter_history_for_prediction`,
   `events_past_*`, `parent_*` from a prior parent). Any new target must be
   forward-looking and must not leak into the features.
2. **Targets come from cluster membership over a forward window.** The existing
   `add_forecast_targets` walks each cluster forward `forecast_hours` and labels
   what happens. New targets that reuse this machinery are cheap and low-risk.
3. **Leakage watch.** Some clustered columns (`is_strong_link`, `link_type`,
   `event_role`, `is_family_member`, `mainshock_id`) are assigned by clustering
   that sees the *whole* catalog, including the future. They are safe as **target
   labels** but must never become **features** for a forward prediction.

## Source columns available but currently unused as targets

| Column | Meaning | Distribution (124,047 events) |
|---|---|---|
| `event_role` | single / aftershock / mainshock / foreshock | 81,374 / 34,761 / 4,075 / 3,837 |
| `link_type` | weak / strong ZBZ link | 85,449 / 38,598 |
| `cluster_type` | single / family | 81,374 / 42,673 |
| `aftershock_count_in_family` | family aftershock productivity | mean 485, median 0, 33.5% > 0 |
| `foreshock_count_in_family` | family foreshock count | median 0, only 9.6% > 0 |
| `mainshock_magnitude` | magnitude of the family's mainshock | — |

---

## Tier 1 — High feasibility, high value (recommended next)

These reuse the existing forward-window machinery and have enough positive signal
to train well.

### 1. Aftershock **count** in next 24h (regression / count)
- **What:** number of aftershocks within 24h, not just yes/no or max distance.
- **Why feasible:** identical construction to `max_aftershock_mag_24h` — count the
  `future_positions` instead of taking max. Captures Omori-Utsu productivity,
  which the local-history features (`local_events_*`, `local_log10_energy_*`)
  are well suited to drive.
- **Label source:** count of forward in-cluster aftershocks in the window.
- **Caveat:** heavy-tailed; model as count (Poisson/Tweedie objective) or predict
  `log1p(count)`.

### 2. Multi-horizon versions of existing targets (48h / 72h / 7d)
- **What:** `aftershock_48h`, `aftershock_72h`, distance bins and max-mag at longer
  horizons.
- **Why feasible:** a one-line change to `--forecast-hours`; the same pipeline,
  calibration, and SEIS predictor all generalize. Longer windows have *more*
  positives, so they are typically easier than 24h.
- **Value:** lets the alarm speak to "next 3 days" not just "next 24h".

### 3. Escalation flag: max aftershock magnitude ≥ M5 in 24h (binary)
- **What:** a thresholded binary on top of the (now strong, R² ≈ 0.65) magnitude
  regressor — "is a damaging aftershock likely?".
- **Why feasible:** derived from `max_aftershock_mag_24h`; pairs naturally with the
  calibrated-probability framing already in place.
- **Caveat:** class imbalance grows with the threshold — calibrate and report at
  deployment prevalence, exactly as the distance bins already do.

---

## Tier 2 — Feasible, moderate signal

### 4. Foreshock probability — "is this event followed by a larger one?"
- **What:** probability that a strictly larger event occurs in the next N hours/days
  (operationally, that the current event is a foreshock).
- **Why valuable:** this is the single most useful operational question in
  short-term forecasting.
- **Why only Tier 2:** rare (foreshocks are ~3% of events) and intrinsically hard;
  expect modest AUC and low precision. Frame as relative risk elevation, not a
  hard alarm.
- **Leakage watch:** label from "a larger event follows in-window"; do **not** feed
  `event_role`/`link_type` as features.

### 5. Time-to-next-aftershock (regression)
- **What:** hours until the first forward aftershock (Omori timing).
- **Why feasible:** the window walk already finds the first `future_position`;
  emit its time delta.
- **Caveat:** only defined when an aftershock exists — train conditionally (on
  `aftershock_24h == 1`) or jointly with a hurdle model.

### 6. Will this event belong to a cluster / family? (binary)
- **What:** `is_family_member` as a forward-safe label (event ends up in a
  multi-event family rather than isolated).
- **Why feasible:** 34% of events are family members — healthy balance.
- **Leakage watch:** only the *forward* part of family membership is predictable;
  if the event is a family member solely because of a *prior* parent, that's
  already encoded in `has_parent`/`eta` and is trivial. Define the label as
  "spawns ≥1 forward in-window child" to keep it meaningful.

---

## Tier 3 — Possible but caveat-heavy

### 7. Mainshock probability
- Predicting that the current event is a cluster's mainshock requires knowing no
  larger event follows — heavily future-dependent and rare (~3%). Better expressed
  as the inverse of the foreshock target (#4).

### 8. Total family aftershock productivity (`aftershock_count_in_family`)
- A whole-cluster quantity, not a clean per-event forward window. The distribution
  is dominated by a few mega-clusters (max 5,295), so it is ill-posed as a direct
  per-event target. Prefer the windowed count (#1).

### 9. Foreshock count in next window
- Only 9.6% of events have any family foreshocks and the per-event forward signal
  is very sparse — likely too thin to learn reliably at mc = 1.0.

---

## Suggested order of work

1. **Aftershock count (24h)** and **multi-horizon targets** — cheapest, reuse the
   whole pipeline (build → train → calibrate → SEIS), immediately useful.
2. **M5+ escalation flag** — small addition, high operational value now that the
   magnitude regressor is strong.
3. **Foreshock probability** — higher effort, frame carefully as risk elevation.

All Tier 1 items flow through the existing
`build_training_dataset.py -> train_*_aftershock_models.py -> src/seis/*`
calibration pipeline with no architectural change; only `add_forecast_targets`
and the target lists need extending. See [model_recommendations.md](model_recommendations.md)
for the calibrate-then-select protocol any new classification target should follow.
