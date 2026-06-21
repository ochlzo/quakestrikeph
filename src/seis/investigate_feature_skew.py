"""Quantify the train/serve feature skew and its impact on predictions.

For a sample of 2024 events we compare, per feature:
  * TRAINING-path values   -- the columns stored in the training dataset
                              (parent assigned from the precomputed Zaliapin
                              cluster in build_training_dataset.py)
  * PRODUCTION-path values -- rebuilt per event via build_prediction_features
                              (nearest-neighbor parent re-derived from history,
                              exactly what predict.py feeds the model at serving)

Then we feed BOTH feature representations to the trained aftershock_24h model and
measure how much the skew shifts the predicted probability and whether it breaks
calibration against the true labels. If production-path predictions stay
well-calibrated, the skew is harmless for a calibration-free (Path B) model.
"""

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

SEIS_DIR = Path(__file__).resolve().parent
LIGHTGBM_DIR = SEIS_DIR.parent / "lightgbm"
for p in (str(SEIS_DIR), str(LIGHTGBM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from predict_aftershock import (  # noqa: E402
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    build_prediction_features,
    filter_history_for_prediction,
    normalize_raw_catalog,
)

DF = Path("src/training_set/training_dataset_mc_1_0.csv")
FEATS_TXT = Path("src/training_set/training_dataset_mc_1_0.features.txt")
HIST = Path("dataset/phivolcs_earthquake_2018_2026.csv")
MODEL = Path("src/outputs/xgboost/models_mc_1_0/aftershock_24h.joblib")

PARENT_FEATURES = {
    "eta", "log10_eta", "is_strong_link", "has_parent",
    "parent_time_gap_days", "parent_distance_km", "parent_magnitude", "parent_depth_km",
}


def ece(y, p, n_bins=10):
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.sum() / len(p) * abs(y[m].mean() - p[m].mean())
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--n", type=int, default=800)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    feats = [l.strip() for l in open(FEATS_TXT) if l.strip()]
    df = pd.read_csv(DF, low_memory=False)
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    pool = df[(df.event_year == args.year) & (df.magnitude >= DEFAULT_MIN_MAGNITUDE)].dropna(
        subset=["event_time", "latitude", "longitude", "depth_km", "magnitude"]
    )
    if len(pool) > args.n:
        pool = pool.sample(n=args.n, random_state=args.seed)
    pool = pool.sort_values("event_time").reset_index(drop=True)
    print(f"year={args.year}  sampled {len(pool)} events\n")

    history = normalize_raw_catalog(pd.read_csv(HIST, low_memory=False))
    feat_args = argparse.Namespace(
        b_value=DEFAULT_B_VALUE,
        fractal_dimension=DEFAULT_FRACTAL_DIMENSION,
        log10_eta0=DEFAULT_LOG10_ETA0,
    )

    prod_rows = []
    for _, row in pool.iterrows():
        event = {
            "event_time": row["event_time"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "depth_km": float(row["depth_km"]),
            "magnitude": float(row["magnitude"]),
        }
        ph = filter_history_for_prediction(history, event["event_time"], DEFAULT_MIN_MAGNITUDE)
        prod_rows.append(build_prediction_features(ph, event, feat_args, feats).iloc[0])
    prod = pd.DataFrame(prod_rows, columns=feats).reset_index(drop=True)
    train = pool[feats].reset_index(drop=True)

    # ---- 1) per-feature skew ----
    print("=== PER-FEATURE SKEW (training vs production), parent features first ===")
    print("  %-42s %8s %9s %9s" % ("feature", "corr", "med_abs", "%exact"))
    order = [f for f in feats if f in PARENT_FEATURES] + [f for f in feats if f not in PARENT_FEATURES]
    summary = []
    for f in order:
        a = pd.to_numeric(train[f], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(prod[f], errors="coerce").to_numpy(dtype=float)
        mask = ~(np.isnan(a) | np.isnan(b))
        if mask.sum() < 5:
            continue
        aa, bb = a[mask], b[mask]
        corr = np.corrcoef(aa, bb)[0, 1] if np.std(aa) > 0 and np.std(bb) > 0 else float("nan")
        med_abs = float(np.median(np.abs(aa - bb)))
        pct_exact = float(np.mean(np.isclose(aa, bb, rtol=1e-3, atol=1e-6)) * 100)
        tag = "  <-- parent" if f in PARENT_FEATURES else ""
        summary.append((f, corr, med_abs, pct_exact))
        print("  %-42s %8.3f %9.3f %8.1f%s" % (f, corr, med_abs, pct_exact, tag))

    # ---- 2) impact on the model's prediction ----
    print("\n=== IMPACT ON aftershock_24h PREDICTIONS ===")
    mdl = joblib.load(MODEL)
    p_train = mdl.predict_proba(train[feats])[:, 1]
    p_prod = mdl.predict_proba(prod[feats])[:, 1]
    y = pool["aftershock_24h"].to_numpy()
    from sklearn.metrics import brier_score_loss
    print(f"  mean |d prob| (train-feats vs prod-feats): {np.mean(np.abs(p_train - p_prod)):.4f}")
    print(f"  median |d prob|                          : {np.median(np.abs(p_train - p_prod)):.4f}")
    print(f"  90th pct |d prob|                        : {np.percentile(np.abs(p_train - p_prod), 90):.4f}")
    print(f"  corr(prob_train, prob_prod)              : {np.corrcoef(p_train, p_prod)[0,1]:.4f}")
    print()
    print(f"  Brier vs truth -- training-feats : {brier_score_loss(y, p_train):.4f}  ECE {ece(y, p_train):.4f}")
    print(f"  Brier vs truth -- production-feats: {brier_score_loss(y, p_prod):.4f}  ECE {ece(y, p_prod):.4f}")
    print(f"  mean pred train-feats {p_train.mean():.3f} | prod-feats {p_prod.mean():.3f} | truth {y.mean():.3f}")


if __name__ == "__main__":
    main()
