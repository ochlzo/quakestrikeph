"""Fit per-(family, target) isotonic probability calibrators on the 2024 validation year.

The deployed SEIS predictor outputs probabilities, so each model's raw scores are
passed through an isotonic calibrator before being shown. Calibrators are fit on
the 2024 validation year because:

  * the models were not trained on it (2024 was only used for early stopping), so
    it is a leak-free calibration set, and
  * it is separate from the 2025+ selection/test pool, so re-picking bins on the
    pool remains an honest out-of-sample comparison.

Crucially, features for 2024 are rebuilt with the *production* feature path
(same as ``calibration_score.py``), so the calibrators see the exact distribution
the deployed model produces -- fixing, not inheriting, the train/serve skew.

Calibration is applied EQUALLY to all three families, removing the
unequal-preprocessing confound that previously favored the boosting models.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SEIS_DIR = Path(__file__).resolve().parent
if str(SEIS_DIR) not in sys.path:
    sys.path.insert(0, str(SEIS_DIR))

from calibration_score import (  # noqa: E402
    DEFAULT_FEATURE_COLUMNS,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_LABELED_CSV,
    FAMILY_DIRS,
    build_feature_matrix,
    load_all_family_models,
    score_families,
)
from predict_aftershock import (  # noqa: E402
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    load_feature_columns,
    normalize_raw_catalog,
)
from predict import CLASSIFICATION_TARGETS, require_dependencies  # noqa: E402

DEFAULT_CALIBRATORS_DIR = Path("src/outputs/seis/calibration/calibrators")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labeled-csv", type=Path, default=DEFAULT_LABELED_CSV)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--calibrators-dir", type=Path, default=DEFAULT_CALIBRATORS_DIR)
    parser.add_argument("--validation-year", type=int, default=2024)
    parser.add_argument("--minimum-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--b-value", type=float, default=DEFAULT_B_VALUE)
    parser.add_argument("--fractal-dimension", type=float, default=DEFAULT_FRACTAL_DIMENSION)
    parser.add_argument("--log10-eta0", type=float, default=DEFAULT_LOG10_ETA0)
    return parser.parse_args()


def load_validation(labeled_csv, validation_year, minimum_magnitude):
    df = pd.read_csv(labeled_csv, low_memory=False)
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    df = df.dropna(subset=["event_time", "latitude", "longitude", "depth_km", "magnitude"])
    val = df[
        (df["event_year"] == validation_year) & (df["magnitude"] >= minimum_magnitude)
    ].copy()
    return val.sort_values(["event_time", "event_id"], kind="mergesort").reset_index(drop=True)


def main():
    args = parse_args()
    deps = require_dependencies()
    from sklearn.isotonic import IsotonicRegression
    import joblib

    feature_columns = load_feature_columns(args.feature_columns)

    print("Loading historical catalog...", flush=True)
    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))

    val = load_validation(args.labeled_csv, args.validation_year, args.minimum_magnitude)
    print(f"Validation pool: {len(val)} events (year={args.validation_year})", flush=True)

    print("Loading models for all three families...", flush=True)
    models = load_all_family_models(args, deps)

    print("Building production features for validation year...", flush=True)
    X, _meta, labels = build_feature_matrix(val, history, args, feature_columns)

    print("Scoring families on validation...", flush=True)
    probs_df = score_families(models, X)

    args.calibrators_dir.mkdir(parents=True, exist_ok=True)
    print("Fitting isotonic calibrators...", flush=True)
    for family in FAMILY_DIRS:
        for target in CLASSIFICATION_TARGETS:
            y = labels[target].to_numpy(dtype=int)
            p = probs_df[f"prob_{family}_{target}"].to_numpy(dtype=float)
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(p, y)
            out_path = args.calibrators_dir / f"{family}__{target}.joblib"
            joblib.dump(iso, out_path)
    print(f"Wrote {len(FAMILY_DIRS) * len(CLASSIFICATION_TARGETS)} calibrators to "
          f"{args.calibrators_dir}", flush=True)

    # Also persist the raw validation predictions for reproducibility/auditing.
    val_out = pd.concat([labels, probs_df], axis=1)
    val_csv = args.calibrators_dir / "validation_raw_predictions.csv"
    val_out.to_csv(val_csv, index=False)
    print(f"Wrote {val_csv}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
